# gsaps4v napi poszt

Minden nap 18:47 körül (budapesti idő) kimegy egy poszt az Instagramra. A képek egy sorban várakoznak, így mindig hetekre előre látod, mi következik.

## Hogyan működik

Három sor van, mindegyik egy mappa:

| Mappa | Mikor posztol belőle | Idézet |
|---|---|---|
| `queue` | minden normál napon | van |
| `queue_red` | piros napon (01.01, 02.02 … 12.12) | van, külön piros hangon |
| `queue_bonus` | bónusz napon, a piros nap utáni napon (01.02, 02.03 … 12.13) | szándékosan nincs |

Minden este a rendszer:
1. Normál napon legenerál egy új képet a LoRA-val, idézettel együtt, és **a `queue` végére** teszi. Piros és bónusz napon ezt kihagyja, így a fő sor hossza mindig ugyanannyi marad.
2. Ha a piros vagy a bónusz tartalék 2 alá csökken, generál oda is egyet.
3. Kiposztolja az aznapi sor **elején** álló képet, és átteszi a `posted` archívumba.

## Kezdő állapot

A sor már fel van töltve, és minden képnek megvan az idézete:
- `queue`: `000.png` a piros nyitókép (50. poszt), utána `001`-`047` véletlen sorrendben. Minden kép mellett azonos nevű txt az idézettel.
- `queue_red`: 3 piros kép, saját idézettel.
- `queue_bonus`: 5 bónusz kép, idézet nélkül.

Az első futáskor a rendszer a képeket a saját belső számozására nevezi át (`0001.jpg` …). A sorrend és az idézetpárok ettől nem változnak.

## Idézetek

- **Generált képek:** a Claude ír idézetet a `quote_style.txt` mintái alapján, ismétlés nélkül, még a generáláskor. Így a 7 hetes várakozás alatt látod és átírhatod.
- **Piros képek:** 12 jelöltből azt választja, amelyik a legjobban hasonlít a piros mintákra (`quote_style_red.txt`). Minden kiposztolt piros idézet bekerül a `quote_style_red_learned.txt`-be, így a piros minta idővel erősödik (a legfrissebb 12 marad meg, a te alapidézeteid mindig megmaradnak).
- **Meglévő idézetet a rendszer soha nem ír felül.** Csak akkor generál, ha egy képnek egyáltalán nincs txt-je, legkésőbb a kimenetel napján.
- **Átírás:** a GitHubon kattints a txt fájlra, ceruza ikon, írd át, Commit.

## Poszt szövege

Idézet, három pont külön sorban, aztán 5 hashtag: kettő fix (`#abstractportrait #abstractface`), három naponta véletlenszerűen a rotáló listából. Mindkét lista a `post.py` tetején állítható. Az Instagram 5 hashtagnél többet nem enged. A bónusz posztoknál csak a pontok és a hashtagek mennek ki.

## Új képek hozzáadása kézzel

`queue` mappa → Add file → Upload files. A fájlnév mindegy, a rendszer a következő futáskor JPEG-re alakítja, beszámozza, és **a sor végére** teszi. Ha idézetet is szeretnél hozzá, tölts fel mellé egy azonos nevű txt-t (pl. `uj.png` + `uj.txt`). Txt nélkül a rendszer ír neki egyet. Ugyanez működik a `queue_red` és a `queue_bonus` mappában is.

## Sor kezelése

- **Átnézés:** az előnézeti oldalon, vagy a GitHubon a mappákban.
- **Törlés:** kép megnyitása → jobb felül `...` → Delete file → Commit. Ha a képnek van txt-je, azt is töröld.
- **Sorrend:** a fájlnév száma szerint megy, átnevezéssel előrébb vagy hátrébb teheted.

## Bónusz képek

Az eredeti masterből (`bonus_reference.png`) készülnek a FLUX.2 [max] szerkesztővel, ezzel a prompttal: *„Create a new variation of this painting. Keep the exact same style, colors, brushwork and composition, but paint a completely different man's face with a new expression.”*

## Különleges napok

A `prompts.json`-ba dátum szerint írhatsz saját promptot, ez a **kiposztolás** napja. A rendszer generáláskor kiszámolja, melyik napon kerül ki a kép (a piros és bónusz napokat átugorva), és ha arra a napra van saját prompt, azt használja. Most: december 24-re mikulássapkás, piros hátteres kép. Ha közben törölsz a sorból, a képek előrébb csúsznak, ezért ünnepek előtt érdemes az előnézeten ránézni.

## Előnézeti oldal

Az `index.html` élőben mutatja a következő posztokat: kép, idézet, kimenetel dátuma, poszt száma, piros és bónusz napok jelölve, és szól, ha fogy a sor.

Bekapcsolás egyszer: Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch: **main**, mappa: **/ (root)** → Save. Pár perc múlva elérhető: `https://balazsnogradii-cell.github.io/gsaps4v-bot/`

## Archívum

A kiposztolt képek a `posted` mappába kerülnek a valódi Instagram poszt számukkal (`0050.jpg`, `0051.jpg`…), az idézetükkel együtt.

## Időzítés

A GitHub naponta négyszer indítja a scriptet, kerek órákon kívül (16:47, 17:47, 18:47, 19:47 UTC), mert egész órakor a GitHub néha eldobja az időzített futásokat. A script csak akkor posztol, ha már elmúlt 18:40 budapesti idő, és ma még nem ment ki poszt (`last_post_date.txt`). Így:
- nyáron a 18:47-es, télen a 18:47-es (UTC-ben egy órával később induló) futás posztol, az időszámítás-váltás magától rendeződik,
- ha a GitHub egy futást kihagy, a következő pótolja,
- dupla poszt nem lehet, kézi indításnál sem.

## Beállítás (egyszer)

1. Fájlok feltöltése a **publikus** `gsaps4v-bot` repóba (a rejtett `.github` mappával és a `.gitignore`-ral együtt). Publikusnak kell lennie, mert az Instagram innen tölti le a képeket. A kulcsok ettől titkosak maradnak.
2. Repo → Settings → Secrets and variables → Actions → **New repository secret**:
   - `FAL_KEY`: fal.ai API kulcs
   - `IG_ACCESS_TOKEN`: az Instagram token
   - `IG_USER_ID`: az Instagram user ID
   - `LORA_URL`: a LoRA fájl linkje (.safetensors)
   - `ANTHROPIC_API_KEY`: Anthropic API kulcs (console.anthropic.com → API Keys)
   - `GH_PAT`: GitHub token a tokenfrissítéshez (lásd lent)
3. Előnézeti oldal bekapcsolása (lásd fent).
4. Actions fül → **Daily post** → **Run workflow**. Pipával próbafutás: rendezi a sort és generál, de nem posztol. Pipa nélkül élesben fut.

## GH_PAT (egyszeri, kézi)

Az Instagram token 60 nap után lejár. A rendszer minden hétfőn megújítja, és az új tokent visszaírja a Secretsbe, ehhez kell ez a kulcs. Egyszer kell létrehozni, utána minden automatikus:

GitHub → jobb felül profilkép → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Repository access: **Only select repositories** → `gsaps4v-bot`
- Permissions → Repository permissions → **Secrets: Read and write**
- Expiration: a leghosszabb választható. Lejárat előtt a GitHub emailben szól, akkor kell egy újat csinálni és a `GH_PAT` secretet frissíteni.
