# russian-language-data

Open datasets for Russian language learning tools: **word stress**, **verb
aspectual pairs** and **bilingual dictionary entries**, generated from
[OpenRussian](https://github.com/Badestrand/russian-dictionary) and
[WikDict](https://www.wikdict.com/).

| File | Contents | Entries |
|------|----------|--------:|
| `data/stress-db.json` | bare lowercase form → stress-marked form(s) | ~53k |
| `data/aspect-db.json` | verb → aspect, and every attested impf/perf pair | 33k verbs / 11k pairs |
| `data/aspect-pairs-db.json` | `[{ impf, perf, gloss }]` imperfective/perfective pairs (superseded by `aspect-db.json`) | ~7.7k |
| `data/translations/en.json` | headword → dictionary entry, English | ~46k |
| `data/translations/de.json` | headword → dictionary entry, German | ~53k |
| `data/translations/fr.json` | headword → dictionary entry, French | ~25k |
| `data/translations/es.json` | headword → dictionary entry, Spanish | ~19k |
| `data/translations/it.json` | headword → dictionary entry, Italian | ~17k |
| `data/translations/nl.json` | headword → dictionary entry, Dutch | ~9k |
| `data/translations/zh.json` | headword → dictionary entry, Chinese | ~3k |
| `data/dict/<pair>/` | bilingual dictionaries, Russian ↔ 27 languages, sharded (see below) | ~1.5M articles |

One file per language, so a consumer downloads only the language it needs.

**`translations/<lang>.json`** — hand-written glosses, not machine output:
English and German come from OpenRussian's own translation columns, the rest
from WikDict, which distils Wiktionary's translation tables. Keys follow the
same bare-headword convention as `stress-db.json`.

```json
{
  "девушка": { "t": ["girl", "lass", "miss"], "pos": "noun", "g": "f" },
  "читать":  { "t": ["read"], "pos": "verb", "a": "imperfective" }
}
```

`t` is the gloss list, most common first (at most 6). `pos`, `g` (gender) and
`a` (aspect) are present only where the source provides them, so entries built
from WikDict carry `t` alone.

## Formats

**`stress-db.json`** — a JSON object mapping a bare, lowercased headword to its
stress-marked form. Stress is a combining acute accent (U+0301) sitting right
after the stressed vowel. A word with more than one attested stress
(heterograph) maps to an **array**:

```json
{
  "человек": "челове́к",
  "замок": ["за́мок", "замо́к"]
}
```

`ё` is always stressed and carries no extra mark.

**`aspect-db.json`** — the aspect of every verb, and every pair:

```json
{
  "aspect": { "impf": ["читать", …], "perf": ["прочитать", …], "both": ["считать", …] },
  "pairs":  [ ["считывать", "считать", "read off", "or"], … ]
}
```

`aspect` buckets all ~33k verb lemmas OpenCorpora knows, reflexives included.
`both` means the one spelling carries both grammemes — a biaspectual verb
(*использовать*) or two homographs (*считать*: imperfective "consider",
perfective "read off").

`pairs` are `[imperfective, perfective, gloss, source]`, sorted by the
imperfective member; `source` is `"or"` (OpenRussian's partner column) or
`"refl"` (the reflexive of a pair of plain verbs, added when OpenCorpora knows
the reflexive — this is how *считываться/считаться* gets in).

**A verb can appear in several pairs with a different aspect in each**, and a
lookup must keep them all: *считаться* is imperfective in *считаться/счесться*
and perfective in *считываться/считаться*. Picking one pair per headword is
what the older `aspect-pairs-db.json` did, and it labels half of these wrong.

**`aspect-pairs-db.json`** — the older flat list, kept for existing consumers.
A JSON array of pairs, sorted by the imperfective member:

```json
[
  { "impf": "покупать", "perf": "купить", "gloss": "buy" },
  { "impf": "решать", "perf": "решить", "gloss": "decide" }
]
```

## Bilingual dictionaries: `data/dict/`

Two dictionaries for each of 27 languages, Russian to the language and back
(`ru-fr`, `fr-ru`, …): en es fr de it pt nl pl cs sk sl bg sr hr ro el hu fi
sv no da lt lv et tr zh ja. Built from Wiktionary, read through the
[wiktextract](https://github.com/tatuylonen/wiktextract) extractions published
on [kaikki.org](https://kaikki.org/): the English and Russian editions, plus
the edition written in the language itself where kaikki publishes one (fr de
es it pt nl pl cs el tr ja zh).

An article is modelled on a printed bilingual dictionary: numbered senses with
their translations, usage labels and short examples with a translation, and a
ranked list of the best equivalents first.

```json
"девушка": [{
  "w": "девушка", "h": "де́вушка", "p": "noun", "gd": "f",
  "t": ["mademoiselle", "demoiselle", "jeune fille", "fille", "petite amie"],
  "s": [
    { "g": "Jeune fille, demoiselle …", "t": ["jeune fille", "demoiselle"], "x": [["…", "…"]] },
    { "d": "форма обращения к девушке", "t": ["mademoiselle"] }
  ],
  "src": ["frwikt", "inv", "ruwikt"]
}]
```

| Field | Meaning |
|---|---|
| `w` | headword; `h` the same with stress marks, where known |
| `p` | part of speech (wiktextract names: noun, verb, adj, adv, …) |
| `gd`, `a` | gender (m/f/n), aspect (impf/perf) |
| `t` | best equivalents, strongest first (at most 8) |
| `s` | senses: `g` a gloss in the other language, or `d` a sense label from a translation table; `t` its equivalents, `l` usage labels, `x` examples `[text, translation]` |
| `src` | where the article comes from: `<lang>wikt` a Wiktionary edition, `inv` translations read backwards from other articles, `pivot` equivalents listed under the same English sense (used only where nothing direct exists) |

A key may hold several articles (one per part of speech). Keys are lowercase;
Russian keys have no stress marks and keep ё and й.

**Layout.** Each pair is a directory with `manifest.json` and shards
`0.json … N-1.json`. A shard is `{ "e": { key: [article, …] }, "f": { form: [key, …] } }`:
`e` holds the articles, `f` maps inflected forms of the non-Russian language
to the keys of their articles (*went* → *go*). The shard of a key is
`fnv1a32(key) % buckets`, FNV-1a over UTF-16 code units, so a lookup downloads
one file of about 250 KB. Russian inflection is not in the data: pass the
lemmas from your morphology (pymorphy3, Az.js). `scripts/dict/lookup.mjs` is a
reference client.

**Coverage**: share of the 10 000 most frequent subtitle word forms
(OpenSubtitles, via FrequencyWords) that get at least one translation. Most of
the rest are names and English words.

| Language | ru→x articles | x→ru articles | ru→x coverage | x→ru coverage | Size |
|---|--:|--:|--:|--:|--:|
| English (`en`) | 79,360 | 79,313 | 94.2% | 95.5% | 50 MB |
| Spanish (`es`) | 28,276 | 24,884 | 88.0% | 87.5% | 18 MB |
| French (`fr`) | 48,079 | 38,217 | 90.5% | 88.9% | 24 MB |
| German (`de`) | 35,093 | 93,315 | 89.4% | 88.0% | 48 MB |
| Italian (`it`) | 27,241 | 23,783 | 87.0% | 80.5% | 21 MB |
| Portuguese (`pt`) | 22,010 | 23,387 | 87.4% | 87.6% | 11 MB |
| Dutch (`nl`) | 19,911 | 23,174 | 85.7% | 81.2% | 10 MB |
| Polish (`pl`) | 36,834 | 36,679 | 89.7% | 89.9% | 28 MB |
| Czech (`cs`) | 23,109 | 25,715 | 86.7% | 82.4% | 14 MB |
| Slovak (`sk`) | 15,419 | 11,983 | 77.8% | 58.4% | 5 MB |
| Slovenian (`sl`) | 12,293 | 9,261 | 76.2% | 37.2% | 4 MB |
| Bulgarian (`bg`) | 18,183 | 15,297 | 85.0% | 44.4% | 11 MB |
| Serbian (`sr`) | 13,982 | 16,045 | 76.3% | 61.7% | 9 MB |
| Croatian (`hr`) | 14,319 | 10,523 | 79.0% | 53.0% | 6 MB |
| Romanian (`ro`) | 15,533 | 13,439 | 82.1% | 67.7% | 7 MB |
| Greek (`el`) | 17,302 | 16,031 | 84.0% | 78.6% | 12 MB |
| Hungarian (`hu`) | 17,129 | 17,545 | 84.7% | 74.5% | 23 MB |
| Finnish (`fi`) | 19,775 | 24,970 | 87.2% | 86.4% | 93 MB |
| Swedish (`sv`) | 22,700 | 20,637 | 85.9% | 83.5% | 10 MB |
| Norwegian (`no`) | 15,596 | 15,532 | 81.6% | 76.2% | 6 MB |
| Danish (`da`) | 15,631 | 15,400 | 81.8% | 76.3% | 6 MB |
| Lithuanian (`lt`) | 13,959 | 13,350 | 76.3% | 35.8% | 7 MB |
| Latvian (`lv`) | 13,304 | 11,214 | 74.8% | 59.1% | 5 MB |
| Estonian (`et`) | 13,796 | 11,188 | 73.6% | 70.0% | 7 MB |
| Turkish (`tr`) | 18,281 | 26,356 | 84.1% | 69.7% | 51 MB |
| Chinese (`zh`) | 113,842 | 177,033 | 92.0% | 66.2% | 69 MB |
| Japanese (`ja`) | 22,802 | 16,905 | 85.6% | 48.4% | 12 MB |

Japanese and Chinese x→ru figures understate: the frequency lists split words differently (分か for 分かる). Serbian in Latin script falls back to the Croatian dictionary.

**Rebuilding** (Python 3.11+, `pip install orjson pymorphy3`; about 5 GB of
downloads, kept in the git-ignored `.cache/`):

```bash
sh scripts/dict/fetch.sh en ru fr de es it pt nl pl cs el tr ja zh
python scripts/dict/extract.py en .cache/en-raw.jsonl.gz     # and each <lang>-extract
python scripts/dict/build.py                                 # all pairs, or: build.py en fr
python scripts/dict/coverage.py en fr
```

## Regenerating

```bash
node scripts/build-language-db.mjs    # stress, aspect pairs, translations
python scripts/build-aspect-db.py     # aspect-db.json (needs pymorphy3)
```

The scripts fetch the OpenRussian CSV tables from GitHub raw and write the JSON
files into `data/`. No source data is vendored in this repository. The aspect
builder additionally reads the OpenCorpora dictionary shipped with
[pymorphy3](https://github.com/no-plagiarism/pymorphy3) (`pip install pymorphy3`)
for the per-verb aspect grammeme.

## Consuming from another project

Pin to a tag or commit and download at build time, e.g.:

```
https://raw.githubusercontent.com/cestmoi111/russian-language-data/<tag>/data/stress-db.json
https://raw.githubusercontent.com/cestmoi111/russian-language-data/<tag>/data/aspect-pairs-db.json
```

## License

The datasets under `data/` are licensed under **CC BY-SA 4.0** (see `LICENSE`),
inherited from OpenRussian's ShareAlike terms. You must keep attribution,
indicate changes, and license any redistribution under CC BY-SA 4.0. See
`NOTICE` for full source attribution.
