# russian-language-data

Open datasets for Russian language learning tools: **word stress**, **verb
aspectual pairs** and **bilingual dictionary entries**, generated from
[OpenRussian](https://github.com/Badestrand/russian-dictionary) and
[WikDict](https://www.wikdict.com/).

| File | Contents | Entries |
|------|----------|--------:|
| `data/stress-db.json` | bare lowercase form → stress-marked form(s) | ~53k |
| `data/aspect-pairs-db.json` | `[{ impf, perf, gloss }]` imperfective/perfective pairs | ~7.7k |
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

**`aspect-pairs-db.json`** — a JSON array of pairs, sorted by the imperfective
member. `gloss` is a short English gloss (may be empty):

```json
[
  { "impf": "покупать", "perf": "купить", "gloss": "buy" },
  { "impf": "решать", "perf": "решить", "gloss": "decide" }
]
```

## Regenerating

```bash
node scripts/build-language-db.mjs
```

The script fetches the OpenRussian CSV tables from GitHub raw and writes both
JSON files into `data/`. No source data is vendored in this repository.

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
