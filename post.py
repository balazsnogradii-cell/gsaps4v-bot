"""
gsaps4v napi poszt, pufferrel.

Minden futaskor:
  1. a queue es queue_red mappaba feltoltott uj kepeket JPEG-re alakitja es beszamozza
  2. general egy uj kepet, es a sor VEGERE teszi (piros napon nem)
  3. kiposztolja a sor ELEJEN allo kepet, majd atrakja a posted mappaba
     Piros napon (01.01, 02.02 ... 12.12) a queue_red sorbol posztol.
"""
import datetime
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import time

import requests
from PIL import Image

# ---------- Beallitasok ----------
BASE_PROMPT = "GSAPS4V style portrait painting"
# Kulonleges nap: amikor a honap es a nap szama megegyezik (01.01, 02.02 ... 12.12)
RED_PROMPT = "GSAPS4V style portrait painting, smoking a pipe, red background"
RED_RESERVE = 2

# Bonusz nap: a piros nap utani nap (01.02, 02.03 ... 12.13). Idezet nelkul megy ki.
# A kep az eredeti masterbol (bonus_reference.png) keszul, FLUX.2 [max] szerkesztovel.
BONUS_MODEL = "fal-ai/flux-2-max/edit"
BONUS_PROMPT = ("Create a new variation of this painting. Keep the exact same style, colors, brushwork "
                "and composition, but paint a completely different man's face with a new expression.")
BONUS_RESERVE = 2  # ennyi piros kepet tart mindig keszletben
LORA_SCALE = 2.3
GRAPH = "https://graph.instagram.com/v23.0"
# Hashtagek: a fix mindig kimegy, a rotalobol naponta veletlenszeruen 3
HASHTAGS_FIXED = ["#abstractportrait", "#abstractface"]
HASHTAGS_ROTATING = ["#cubism", "#expressionism", "#cubistart", "#neoexpressionism"]
HASHTAGS_ROTATING_PICK = 3

# Idezet: a Claude generalja a quote_style.txt mintai alapjan
QUOTE_MODEL = "claude-sonnet-5-5"
# ---------------------------------

FAL_KEY = os.environ["FAL_KEY"]
IG_TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]
LORA_URL = os.environ["LORA_URL"]
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REPO = os.environ["GITHUB_REPOSITORY"]
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

QUEUE = pathlib.Path("queue")
RED_QUEUE = pathlib.Path("queue_red")
BONUS_QUEUE = pathlib.Path("queue_bonus")
POSTED = pathlib.Path("posted")
POSTS_BEFORE = 49  # ennyi poszt volt kint az automatizalas elott
NUMBERED = re.compile(r"^\d{4}\.jpg$")


def git(*args):
    subprocess.run(["git", *args], check=True)


def commit_push(message):
    git("add", "-A", str(QUEUE), str(RED_QUEUE), str(BONUS_QUEUE), str(POSTED))
    if RED_LEARNED.exists():
        git("add", str(RED_LEARNED))
    if LAST_POST.exists():
        git("add", str(LAST_POST))
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        git("commit", "-m", message)
        git("pull", "--rebase")
        git("push")


def numbered(folder):
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if NUMBERED.match(p.name))


def next_number():
    nums = [int(p.stem) for p in numbered(QUEUE) + numbered(RED_QUEUE) + numbered(BONUS_QUEUE) + numbered(POSTED)]
    return max(nums, default=0) + 1


def natural_key(p):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.stem)]


def normalize_queue(folder):
    """Feltoltott kepek: JPEG-re alakit, a sor vegere szamoz.
    Ha a kep mellett azonos nevu .txt is van (pl. 001.png + 001.txt), azt viszi magaval idezetnek."""
    folder.mkdir(exist_ok=True)
    new_files = sorted(
        (p for p in folder.iterdir()
         if p.is_file() and not NUMBERED.match(p.name) and not p.name.startswith(".")
         and p.suffix.lower() != ".txt"),
        key=natural_key,
    )
    n = next_number()
    for p in new_files:
        try:
            img = Image.open(p).convert("RGB")
        except Exception:
            print(f"Nem kep, kihagyom: {p.name}")
            continue
        img.save(folder / f"{n:04d}.jpg", "JPEG", quality=95)
        p.unlink()
        quote = p.with_suffix(".txt")
        if quote.exists():
            quote.rename(folder / f"{n:04d}.txt")
            print(f"Sorba allitva: {p.name} + idezet -> {n:04d}.jpg")
        else:
            print(f"Sorba allitva: {p.name} (idezet nelkul) -> {n:04d}.jpg")
        n += 1


def pick_prompt(post_date):
    """A prompts.json datumai a KIPOSZTOLAS napjat jelentik."""
    try:
        with open("prompts.json", encoding="utf-8") as f:
            special = json.load(f)
    except FileNotFoundError:
        special = {}
    return special.get(post_date.isoformat(), BASE_PROMPT)


def known_quotes():
    """Az eddigi idezetek, hogy ne ismetlodjenek."""
    out = []
    for folder in (QUEUE, RED_QUEUE, POSTED):
        if folder.exists():
            out += [p.read_text(encoding="utf-8").strip() for p in folder.glob("*.txt")]
    return [q for q in out if q]


def generate_quote(red=False):
    """Kek kepekhez egy idezet. Pirosakhoz 12 jeloltbol a piros mintakhoz leginkabb hasonlitot."""
    if not ANTHROPIC_KEY:
        return None

    def read(name):
        try:
            return pathlib.Path(name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    recent = "\n".join(known_quotes()[-60:])
    rules = (
        "Rules: English, max 20 words, no hashtags, no quotation marks around it, no emojis. "
        "No politics, religious commentary, violence, death of real people, or real names. "
        "Do not repeat or closely paraphrase any of these earlier captions:\n"
        f"{recent}\n\n"
    )
    if red:
        red_refs = read("quote_style_red.txt").strip() + "\n" + read("quote_style_red_learned.txt").strip()
        prompt = (
            "Write 12 new original one-line captions for an Instagram art account that posts "
            "abstract cubist portraits of suspicious, weary, bald men.\n"
            "Tone: surreal, absurd, quietly melancholic, dry humour, contemplative. "
            "Match the voice of these examples:\n\n"
            f"{read('quote_style.txt')}\n\n"
            + rules +
            "Write the 12 candidates, one per line. Then compare them with these reference captions "
            "used for special red posts:\n\n"
            f"{red_refs.strip()}\n\n"
            "Pick the ONE candidate that is most similar in spirit to the red references and write it "
            "on a final line starting with BEST: "
        )
    else:
        prompt = (
            "Write ONE new original one-line caption for an Instagram art account that posts "
            "abstract cubist portraits of suspicious, weary, bald men with a blue background.\n"
            "Tone: surreal, absurd, quietly melancholic, dry humour, contemplative. "
            "Match the voice of these examples exactly:\n\n"
            f"{read('quote_style.txt')}\n\n"
            + rules +
            "Reply with the caption only."
        )
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": QUOTE_MODEL,
                "max_tokens": 700 if red else 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        lines = [l.strip() for l in resp.json()["content"][0]["text"].splitlines() if l.strip()]
        if red:
            best = [l for l in lines if l.upper().startswith("BEST:")]
            text = best[-1][5:] if best else (lines[-1] if lines else "")
        else:
            text = lines[0] if lines else ""
        text = text.strip().strip('"').strip()
        return text or None
    except Exception as e:
        print(f"Figyelem: idezet generalas nem sikerult ({e})")
        return None


RED_LEARNED = pathlib.Path("quote_style_red_learned.txt")
RED_LEARNED_KEEP = 12  # a tanult piros idezetekbol ennyi marad meg (a legfrissebbek)


def learn_red_quote(img):
    """A kiposztolt piros idezet bekerul a tanult mintak koze, igy erosodik a piros sema."""
    txt = img.with_suffix(".txt")
    if not txt.exists():
        return
    quote = txt.read_text(encoding="utf-8").strip()
    base = pathlib.Path("quote_style_red.txt")
    anchors = base.read_text(encoding="utf-8").splitlines() if base.exists() else []
    learned = RED_LEARNED.read_text(encoding="utf-8").splitlines() if RED_LEARNED.exists() else []
    if not quote or quote in anchors or quote in learned:
        return
    learned = (learned + [quote])[-RED_LEARNED_KEEP:]
    RED_LEARNED.write_text("\n".join(learned) + "\n", encoding="utf-8")
    print(f"Piros mintaba tanulva: {quote}")


def build_caption(img):
    txt = img.with_suffix(".txt")
    quote = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
    tags = HASHTAGS_FIXED + random.sample(HASHTAGS_ROTATING, HASHTAGS_ROTATING_PICK)
    head = f"{quote}\n" if quote else ""
    return f"{head}.\n.\n.\n{' '.join(tags)}"


def is_bonus_day(day):
    return is_red_day(day - datetime.timedelta(days=1))


def generate_bonus():
    """Bonusz kep: az eredeti master szerkesztese a 'completely different face' prompttal."""
    ref = f"https://raw.githubusercontent.com/{REPO}/main/bonus_reference.png"
    resp = requests.post(
        f"https://fal.run/{BONUS_MODEL}",
        headers={"Authorization": f"Key {FAL_KEY}"},
        json={
            "prompt": BONUS_PROMPT,
            "image_urls": [ref],
            "image_size": {"width": 1024, "height": 1024},
            "num_images": 1,
            "output_format": "jpeg",
        },
        timeout=300,
    )
    if not resp.ok:
        print(f"Figyelem: bonusz generalas nem sikerult ({resp.status_code}): {resp.text[:300]}")
        return
    image = requests.get(resp.json()["images"][0]["url"], timeout=120)
    path = BONUS_QUEUE / f"{next_number():04d}.jpg"
    path.write_bytes(image.content)
    print(f"Uj bonusz kep: {path.name}")


def expected_post_date(today, ahead):
    """Melyik napon kerul ki a kep, ha 'ahead' normal kep all elotte a sorban.
    A piros es bonusz napokon a fo sorbol nem fogy, ezeket atugorja."""
    day = today
    while True:
        if not is_red_day(day) and not is_bonus_day(day):
            if ahead == 0:
                return day
            ahead -= 1
        day += datetime.timedelta(days=1)


def is_red_day(day):
    return day.month == day.day


def generate_into_queue(prompt, folder):
    resp = requests.post(
        "https://fal.run/fal-ai/flux-2/lora",
        headers={"Authorization": f"Key {FAL_KEY}"},
        json={
            "prompt": prompt,
            "loras": [{"path": LORA_URL, "scale": LORA_SCALE}],
            "image_size": {"width": 1024, "height": 1024},
            "num_images": 1,
            "output_format": "jpeg",
        },
        timeout=300,
    )
    if not resp.ok:
        # Nem allunk le: a pufferbol aznap is lesz poszt
        print(f"Figyelem: a generalas nem sikerult ({resp.status_code}): {resp.text[:300]}")
        return
    image = requests.get(resp.json()["images"][0]["url"], timeout=120)
    path = folder / f"{next_number():04d}.jpg"
    path.write_bytes(image.content)
    print(f"Uj kep a sor vegen: {path.name}")

    # Csak a generalt kepek kapnak automatikus idezetet
    for _ in range(3):
        quote = generate_quote(red=(folder == RED_QUEUE))
        if quote:
            path.with_suffix(".txt").write_text(quote + "\n", encoding="utf-8")
            print(f"Idezet {path.name}: {quote}")
            break


def fail(step, resp):
    print(f"HIBA ({step}): {resp.status_code} {resp.text[:500]}")
    sys.exit(1)


def publish(image_url, caption):
    resp = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": IG_TOKEN},
        timeout=60,
    )
    if not resp.ok:
        fail("kontener", resp)
    container_id = resp.json()["id"]

    for _ in range(24):
        status = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code", "access_token": IG_TOKEN},
            timeout=30,
        ).json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            print("HIBA: az Instagram nem tudta feldolgozni a kepet")
            sys.exit(1)
        time.sleep(5)

    resp = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_TOKEN},
        timeout=60,
    )
    if not resp.ok:
        fail("posztolas", resp)
    return resp.json()["id"]


def refresh_token():
    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": IG_TOKEN},
        timeout=30,
    )
    if not resp.ok:
        print(f"Figyelem: token frissites nem sikerult ({resp.status_code})")
        return
    new_token = resp.json().get("access_token")
    if not new_token:
        print("Figyelem: token frissites valasza ures")
        return
    print(f"::add-mask::{new_token}")
    pathlib.Path("new_token.txt").write_text(new_token)
    print(f"Token megujitva, meg {resp.json().get('expires_in', 0) // 86400} napig ervenyes")


LAST_POST = pathlib.Path("last_post_date.txt")
POST_TIME = (18, 40)  # ennel korabban (budapesti ido) az idozitett futas nem posztol


def budapest_now():
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("Europe/Budapest"))


def should_run():
    """Tobb idozites fut naponta (18:47, 19:47 ... budapesti ido korul).
    Az elso, amelyik 18:40 utan indul es ma meg nem volt poszt, posztol, a tobbi kilep.
    Igy egy kimaradt GitHub-futas sem okoz kiesest, es dupla poszt sem lehet."""
    now = budapest_now()
    if DRY_RUN:
        return True
    if LAST_POST.exists() and LAST_POST.read_text().strip() == now.date().isoformat():
        print("Ma mar kiment a poszt, kilepek.")
        return False
    if os.environ.get("SCHEDULE") and (now.hour, now.minute) < POST_TIME:
        print("Meg nincs 18:40 budapesti ido, kilepek.")
        return False
    return True


def main():
    if not should_run():
        return
    today = budapest_now().date()
    red_day = is_red_day(today)
    bonus_day = is_bonus_day(today)

    # 1. feltoltott kepek rendezese
    normalize_queue(QUEUE)
    normalize_queue(RED_QUEUE)
    normalize_queue(BONUS_QUEUE)

    # 2a. normal kep a sor vegere (piros napon nem, igy a puffer merete nem valtozik).
    #     Amennyi kep most all a sorban, annyi nap mulva kerul ki.
    if not red_day and not bonus_day:
        post_date = expected_post_date(today, len(numbered(QUEUE)))
        prompt = pick_prompt(post_date)
        print(f"Prompt ({post_date} napra): {prompt}")
        generate_into_queue(prompt, QUEUE)

    # 2b. piros keszlet feltoltese
    if len(numbered(RED_QUEUE)) < RED_RESERVE:
        print("Piros keszlet feltoltese")
        generate_into_queue(RED_PROMPT, RED_QUEUE)

    # 2c. bonusz keszlet feltoltese
    if len(numbered(BONUS_QUEUE)) < BONUS_RESERVE:
        print("Bonusz keszlet feltoltese")
        generate_bonus()

    commit_push(f"Sor frissitve {today}")

    if DRY_RUN:
        print(f"Proba futas, nem posztolok. Sorban: {len(numbered(QUEUE))} normal, "
              f"{len(numbered(RED_QUEUE))} piros, {len(numbered(BONUS_QUEUE))} bonusz")
        return

    # 3. piros napon a piros sorbol, egyebkent a normal sorbol posztol
    if red_day and numbered(RED_QUEUE):
        source = RED_QUEUE
    elif bonus_day and numbered(BONUS_QUEUE):
        source = BONUS_QUEUE
    else:
        source = QUEUE
    queue = numbered(source)
    if not queue:
        print("Ures a sor, ma nincs poszt.")
        return
    head = queue[0]
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    image_url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{source}/{head.name}"
    time.sleep(10)  # a GitHub CDN-nek ido kell, mire az uj fajl elerheto

    # Biztonsagi halo: ha egy sajat kephez kimaradt az idezet, most generalunk egyet
    if source == BONUS_QUEUE:
        head.with_suffix(".txt").unlink(missing_ok=True)  # bonusz poszt: szandekosan idezet nelkul
    elif not head.with_suffix(".txt").exists():
        for _ in range(3):
            quote = generate_quote(red=(source == RED_QUEUE))
            if quote:
                head.with_suffix(".txt").write_text(quote + "\n", encoding="utf-8")
                print(f"Hianyzo idezet potolva: {quote}")
                break

    if source == RED_QUEUE:
        learn_red_quote(head)

    caption = build_caption(head)
    post_id = publish(image_url, caption)
    LAST_POST.write_text(today.isoformat() + "\n")
    commit_push(f"Posztolas datuma: {today}")  # azonnal mentjuk, hogy egy tartalek futas se posztoljon ujra
    print(f"Kiposztolva: {source}/{head.name}, id: {post_id}\n{caption}")

    # Archivum: a kep a valodi Instagram poszt szamat kapja (0050.jpg, 0051.jpg ...)
    POSTED.mkdir(exist_ok=True)
    post_no = max([POSTS_BEFORE] + [int(p.stem) for p in numbered(POSTED)]) + 1
    target = POSTED / f"{post_no:04d}.jpg"
    git("mv", str(head), str(target))
    if head.with_suffix(".txt").exists():
        git("mv", str(head.with_suffix(".txt")), str(target.with_suffix(".txt")))
    print(f"Archivalva: {target} ({post_no}. poszt)")
    commit_push(f"Kiposztolva: {post_no}. poszt")
    print(f"Sorban maradt: {len(numbered(QUEUE))} normal, {len(numbered(RED_QUEUE))} piros")

    if today.weekday() == 0:  # hetfon
        refresh_token()


if __name__ == "__main__":
    main()
