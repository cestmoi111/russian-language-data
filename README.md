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
