"""Stage 1: stream one Wiktionary dump (kaikki.org / wiktextract JSONL.gz) and
keep only what the bilingual dictionaries need, per target language.

    python scripts/dict/extract.py en .cache/en-raw.jsonl.gz
    python scripts/dict/extract.py ru .cache/ru-extract.jsonl.gz
    python scripts/dict/extract.py fr .cache/fr-extract.jsonl.gz

`edition` is the language the dump is WRITTEN in (its glosses). Output goes to
.cache/stage/<edition>/, one JSONL per record kind and language:

  ruent.jsonl          Russian headwords defined in the edition's language
  xent.<x>.jsonl       (ru edition only) headwords of language x, glosses in Russian
  tr.<x>.jsonl         translation tables linking Russian and x
  pivot.jsonl          (en edition only) English senses listing both ru and x
  forms.<x>.jsonl      inflected form -> lemma for language x

Everything is kept raw enough that the merge step (build.py) can change its
mind without re-reading the multi-gigabyte dumps.
"""

import gzip
import os
import sys

import orjson

from langs import TARGETS, wikt_to_target

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MAX_EX = 3
MAX_EX_LEN = 220

# Senses that only point to another headword carry no meaning of their own.
FORM_TAGS = {"form-of", "alt-of", "abbreviation", "misspelling", "alternative"}
SKIP_POS = {"name", "character", "symbol", "punct", "romanization", "suffix",
            "prefix", "infix", "interfix", "affix", "circumfix", "phrase-suffix"}


class Sink:
    def __init__(self, base):
        self.base = base
        self.files = {}
        os.makedirs(base, exist_ok=True)

    def write(self, name, obj):
        f = self.files.get(name)
        if f is None:
            f = self.files[name] = open(os.path.join(self.base, name + ".jsonl"), "wb")
        f.write(orjson.dumps(obj))
        f.write(b"\n")

    def close(self):
        for f in self.files.values():
            f.close()


def examples(sense, want_translation):
    out = []
    for ex in sense.get("examples") or []:
        text = (ex.get("text") or "").strip()
        tr = (ex.get("translation") or ex.get("english") or "").strip()
        if not text or len(text) > MAX_EX_LEN:
            continue
        if want_translation and not tr:
            continue
        if ex.get("type") == "quotation" and len(text) > 120:
            continue
        out.append([text, tr] if tr else [text])
        if len(out) >= MAX_EX:
            break
    return out


def labels(sense, edition):
    # Normalised wiktextract tags are English words ("colloquial", "figuratively");
    # the ru edition's own marks (разг., перен.) come as raw tags and are kept too.
    tags = [t for t in (sense.get("tags") or []) if t not in ("form-of",)]
    raw = sense.get("raw_tags") or [] if edition == "ru" else []
    return (tags + raw)[:4]


def senses_of(o, want_translation, edition):
    out = []
    for s in o.get("senses") or []:
        tags = set(s.get("tags") or [])
        if tags & FORM_TAGS or s.get("form_of") or s.get("alt_of"):
            continue
        gl = [g.strip().lstrip("#*: ").strip() for g in (s.get("glosses") or []) if g and g.strip()]
        gl = [g for g in gl if g]
        if not gl:
            continue
        rec = {"g": gl[-1]}
        lb = labels(s, edition)
        if lb:
            rec["l"] = lb
        ex = examples(s, want_translation)
        if ex:
            rec["x"] = ex
        out.append(rec)
    return out


def head(o):
    for f in o.get("forms") or []:
        if "canonical" in (f.get("tags") or []):
            return f.get("form")
    return None


def gram(o):
    tags = set(o.get("tags") or [])
    for ht in o.get("head_templates") or []:
        tags.update((ht.get("expansion") or "").replace(",", " ").split())
    rec = {}
    for t, (k, v) in {
        "masculine": ("gd", "m"), "feminine": ("gd", "f"), "neuter": ("gd", "n"),
        "imperfective": ("a", "impf"), "perfective": ("a", "perf"),
        "impf": ("a", "impf"), "pf": ("a", "perf"),
    }.items():
        if t in tags and k not in rec:
            rec[k] = v
    return rec


def forms_of(o):
    """Inflected forms of a lemma, and lemmas this entry is a form of."""
    lemma = o.get("word")
    for f in o.get("forms") or []:
        form = f.get("form")
        tags = set(f.get("tags") or [])
        if not form or form == lemma or tags & {"canonical", "romanization", "table-tags",
                                                   "inflection-template", "class"}:
            continue
        if " " in form and " " not in lemma:
            continue  # analytic forms (will go, a été) are not lookup keys
        yield form, lemma
    for s in o.get("senses") or []:
        for fo in (s.get("form_of") or []) + (s.get("alt_of") or []):
            w = fo.get("word")
            if w and w != lemma:
                yield lemma, w


def main():
    edition, path = sys.argv[1], sys.argv[2]
    sink = Sink(os.path.join(ROOT, ".cache", "stage", edition))
    ed_target = wikt_to_target(edition)  # the edition's own language as a target, if any
    n = kept = 0
    try:
        f = gzip.open(path, "rb")
        lines = iter(f)
    except OSError:
        raise
    while True:
        try:
            line = next(lines)
        except StopIteration:
            break
        except EOFError:  # a dump still downloading: use what is there
            print("  (truncated input)")
            break
        if True:
            n += 1
            if n % 500000 == 0:
                print(f"  {edition}: {n:,} lines, {kept:,} records", flush=True)
            try:
                o = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            lc = o.get("lang_code")
            word = o.get("word")
            pos = o.get("pos")
            if not lc or not word or pos in SKIP_POS:
                continue
            tgt = "ru" if lc == "ru" else wikt_to_target(lc, word)

            # Inflected forms, for looking up "went" or "читала".
            if tgt and tgt != "ru":
                for form, lemma in forms_of(o):
                    sink.write(f"forms.{tgt}", [form, lemma])
                    kept += 1

            # Russian headwords defined in this edition's language.
            if lc == "ru" and ed_target and ed_target != "ru":
                ss = senses_of(o, (edition != "ru"), edition)
                if ss:
                    rec = {"w": word, "p": pos, "s": ss}
                    h = head(o)
                    if h and h != word:
                        rec["h"] = h
                    rec.update(gram(o))
                    sink.write("ruent", rec)
                    kept += 1

            # Foreign headwords defined in Russian (ru edition only).
            if edition == "ru" and tgt and tgt != "ru":
                ss = senses_of(o, False, edition)
                if ss:
                    rec = {"w": word, "p": pos, "s": ss}
                    rec.update(gram(o))
                    sink.write(f"xent.{tgt}", rec)
                    kept += 1

            trs = o.get("translations") or []
            if not trs:
                continue
            # Translation tables between Russian and a target language.
            if tgt:
                by_sense = {}
                for t in trs:
                    tw = (t.get("word") or "").strip()
                    tt = wikt_to_target(t.get("lang_code") or t.get("code") or "", tw)
                    if not tw or not tt:
                        continue
                    if tgt == "ru" and tt != "ru":
                        sink.write(f"tr.{tt}", {"d": "ru", "w": word, "p": pos,
                                                  "sn": t.get("sense") or "", "t": tw})
                        kept += 1
                    elif tgt != "ru" and tt == "ru":
                        sink.write(f"tr.{tgt}", {"d": tgt, "w": word, "p": pos,
                                                   "sn": t.get("sense") or "", "t": tw})
                        kept += 1
                    if edition == "en" and lc == "en":
                        by_sense.setdefault(t.get("sense") or "", {}).setdefault(tt, []).append(tw)
                # English senses that list both Russian and other languages: a
                # sense-aligned pivot, used only where direct data is missing.
                for sn, langs in by_sense.items():
                    if "ru" in langs and len(langs) > 1:
                        sink.write("pivot", {"w": word, "p": pos, "sn": sn, "t": langs})
                        kept += 1
    sink.close()
    print(f"{edition}: {n:,} lines, {kept:,} records -> .cache/stage/{edition}/")


if __name__ == "__main__":
    main()
