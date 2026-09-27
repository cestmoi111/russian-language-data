"""Stage 2: merge the staged Wiktionary records into two dictionaries per
language, ru-<x> and <x>-ru, sharded for on-demand loading.

    python scripts/dict/build.py en fr        # these languages
    python scripts/dict/build.py              # every language in langs.TARGETS

Reads .cache/stage/<edition>/ (written by extract.py) and .cache/freq/, writes
data/dict/<pair>/manifest.json and data/dict/<pair>/<bucket>.json.

How an article is put together (the Lingvo idea: a numbered list of senses,
each with its translations, labels and short examples):

  senses   from the one source that DEFINES the headword in the other
           language: for ru-x the x edition of Wiktionary describing the
           Russian word; for x-ru the Russian edition describing the x word.
           Where that source is silent, the senses come from a translation
           table instead (sense label + the words listed under it).
  t        the short answer shown first: every translation any source gives,
           scored by how many sources agree and by word frequency.
"""

import os
import re
import sys
import unicodedata
from collections import defaultdict

import orjson

from langs import TARGETS

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
STAGE = os.path.join(ROOT, ".cache", "stage")
FREQ = os.path.join(ROOT, ".cache", "freq")
OUT = os.path.join(ROOT, "data", "dict")

MAX_SENSES = 12
MAX_EX = 2
MAX_EX_LEN = 160
MAX_FORMS = 80
MAX_T = 8
SHARD_BYTES = 256 * 1024

# Source weights for the short answer.
W_DEF = 4.0      # gloss of a sense in a defining entry
W_TABLE = 3.0    # translation table of the headword itself
W_INV_TABLE = 2.0  # translation table of the other word, read backwards
W_INV_DEF = 1.5  # the other word's definition mentions this headword
W_PIVOT = 0.5    # both listed under the same English sense

FREQ_FILE = {"zh": "zh_cn"}


# ---------------------------------------------------------------- normalising

def bare_ru(s):
    """Key for a Russian headword: no stress marks, ё and й kept, lowercase."""
    s = (s or "").replace("ё", "\0yo").replace("Ё", "\0YO").replace("й", "\0j").replace("Й", "\0J")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("\0yo", "ё").replace("\0YO", "Ё").replace("\0j", "й").replace("\0J", "Й")
    return unicodedata.normalize("NFC", s).lower().strip()


def key_x(s):
    return unicodedata.normalize("NFC", (s or "").strip()).lower()


def key_of(lang, s):
    return bare_ru(s) if lang == "ru" else key_x(s)


PAREN = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
LEAD = re.compile(r"^(to|a|an|the|le|la|les|l'|l’|un|une|des|du|se|s')\s+", re.I)


# Leading usage marks in Russian glosses: "разг. уличная девка", "перен., книжн. ..."
ABBR = re.compile(r"^(?:[а-яё]{2,8}\.\s*,?\s*)+")
# Words a real equivalent never ends with, and phrases that are only commentary.
TAIL = {"et", "and", "ou", "or", "и", "или", "de", "of", "à", "to", "the", "le", "la"}
META = {"par extension", "by extension", "figuratively", "figurément", "etc", "и т. д",
        "и т. п", "в частности", "не переводится", "especially", "en particulier", "notamment"}


def terms(gloss, lang):
    """Short translation equivalents inside a gloss: "girl, young woman (colloquial)"
    -> ["girl", "young woman"]. Long descriptive glosses yield nothing."""
    g = PAREN.sub("", gloss or "")
    out = []
    for part in re.split(r"[;,]|\bor\b|\bou\b", g):
        p = " ".join(part.split()).strip(".:!()[] ").strip()
        if lang == "ru":
            p = ABBR.sub("", p).strip()
        if not p or len(p) > 40 or len(p.split()) > 4 or "~" in p:
            continue
        if p.lower() in META or p.split()[-1].lower() in TAIL:
            continue
        if lang == "en" and p.lower().startswith("to "):
            p = p[3:]  # "to call" is shown as "call", as in a printed dictionary
        # fr/es/it editions write glosses in sentence case; English and German
        # capitals are meaningful (Christmas, Buch).
        if lang not in ("en", "de") and p[:1].isupper() and not p[1:2].isupper():
            p = p[0].lower() + p[1:]
        if p not in out:
            out.append(p)
    return out


SR_LAT = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџш",
                  ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m",
                   "n", "nj", "o", "p", "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š"]))


def sr_latin(s):
    return "".join(SR_LAT.get(c, c) for c in s)


def plain(t):
    """Comparison form of a translation: lowercase, stress marks dropped. NFC
    first, so only marks with no precomposed letter (Cyrillic stress) remain."""
    t = unicodedata.normalize("NFC", t).lower()
    return t.replace("́", "").replace("̀", "").strip()


def match_key(term, lang):
    """How a gloss term is matched against headwords: drop "to", articles."""
    return key_of(lang, LEAD.sub("", term.strip()))


# ---------------------------------------------------------------- reading

def read(path):
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        for line in f:
            yield orjson.loads(line)


def stage(edition, name):
    """Staged records; a translation written as variants ("詞典 /词典",
    traditional and simplified) becomes one record per variant."""
    for r in read(os.path.join(STAGE, edition, name + ".jsonl")):
        t = r.get("t")
        if isinstance(t, str) and "/" in t:
            for part in t.split("/"):
                if part.strip():
                    yield {**r, "t": part.strip()}
        elif isinstance(t, dict):
            r["t"] = {k: [p.strip() for w in v for p in w.split("/") if p.strip()] for k, v in t.items()}
            yield r
        else:
            yield r


def freq_rank(lang):
    path = os.path.join(FREQ, f"{FREQ_FILE.get(lang, lang)}_50k.txt")
    rank = {}
    if os.path.exists(path):
        with open(path, encoding="utf8") as f:
            for i, line in enumerate(f):
                w = line.split(" ")[0].strip()
                if w:
                    rank.setdefault(key_of(lang, w), i)
    return rank


# ---------------------------------------------------------------- articles

class Article:
    __slots__ = ("w", "p", "h", "gd", "a", "senses", "cand", "inv", "src")

    def __init__(self, w, p):
        self.w, self.p = w, p
        self.h = self.gd = self.a = None
        self.senses = None      # from the defining source
        self.cand = {}          # translation -> score, from the headword's own data
        self.inv = {}           # translation -> score, read backwards from other articles
        self.src = set()

    def add(self, t, weight, src):
        t = t.strip()
        if not t or len(t) > 60:
            return
        self.cand[t] = self.cand.get(t, 0) + weight
        self.src.add(src)

    def add_inv(self, t, weight):
        t = t.strip()
        if t and len(t) <= 60:
            self.inv[t] = self.inv.get(t, 0) + weight


class Dict:
    """All articles of one direction, keyed by (headword key, part of speech)."""

    def __init__(self, src_lang):
        self.lang = src_lang
        self.arts = {}
        self.by_key = defaultdict(list)

    def get(self, w, p, create=True):
        k = (key_of(self.lang, w), p or "")
        a = self.arts.get(k)
        if a is None and create:
            a = self.arts[k] = Article(w, p)
            self.by_key[k[0]].append(k)
        return a

    def any(self, w):
        """Article for a headword when the part of speech is unknown."""
        ks = self.by_key.get(key_of(self.lang, w))
        return self.arts[ks[0]] if ks else None


def add_definitions(d, records, tgt_lang, src_name):
    """Records whose senses define the headword in the target language."""
    for r in records:
        a = d.get(r["w"], r.get("p"))
        if a.senses is None:
            a.senses = []
        for s in r["s"]:
            if len(a.senses) >= MAX_SENSES:
                break
            if not PAREN.sub("", s["g"]).strip(" .;,"):
                continue  # "(мужское имя)": a comment, not a meaning
            sense = {"g": s["g"]}
            ts = terms(s["g"], tgt_lang)
            if ts:
                sense["t"] = ts
            if s.get("l"):
                sense["l"] = s["l"]
            ex = [e for e in s.get("x") or [] if len(e[0]) <= MAX_EX_LEN]
            if ex:
                sense["x"] = ex[:MAX_EX]
            a.senses.append(sense)
            a.src.add(src_name)
            for i, t in enumerate(ts):
                a.add(t, W_DEF / (1 + 0.15 * len(a.senses)) / (1 + 0.3 * i), src_name)
        for k in ("h", "gd", "a"):
            if r.get(k) and not getattr(a, k):
                setattr(a, k, r[k])


def add_table(d, rows, src_name):
    """Translation-table rows of the headword itself, grouped by sense label."""
    tables = defaultdict(lambda: defaultdict(list))
    for r in rows:
        tables[(r["w"], r.get("p"))][r.get("sn") or ""].append(r["t"])
    for (w, p), by_sense in tables.items():
        a = d.get(w, p)
        for n, (sn, ts) in enumerate(by_sense.items()):
            for i, t in enumerate(ts):
                a.add(t, W_TABLE / (1 + 0.2 * n) / (1 + 0.2 * i), src_name)
        if a.senses is None:
            a.senses = [dict({"d": sn} if sn else {}, t=list(dict.fromkeys(ts))[:MAX_T])
                        for sn, ts in list(by_sense.items())[:MAX_SENSES]]


def add_inverse(d, pairs, weight, src_name, rank):
    """(headword, translation, pos) pairs read backwards. Only for headwords
    that exist in d already would be too strict (it is how most x-ru articles
    appear), so articles are created, but only for words the frequency list
    knows or that another source also mentions."""
    for w, t, p in pairs:
        k = key_of(d.lang, w)
        a = d.any(w)
        if a is None:
            if k not in rank:
                continue
            a = d.get(w, p)
        a.add_inv(t, weight)


# ---------------------------------------------------------------- output

def fnv1a(s):
    h = 0x811C9DC5
    # UTF-16 code units, the same as String.charCodeAt in JS.
    data = s.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def finish(a, other_rank):
    """Turn an Article into the published JSON shape, or None if empty."""
    if not a.cand and not a.senses and not a.inv:
        return None
    # Frequent words first among equally attested ones.
    def score(item):
        t, s = item
        r = other_rank.get(match_key(t, "x"), 60000)
        return -(s + 1.0 / (1 + r / 2000))
    # One spelling per word: "собака" and "соба́ка" add up, and the stressed
    # spelling is the one shown.
    merged, shown = {}, {}

    def fold(items):
        acc = {}
        for t, s in items:
            k = plain(t)
            acc[k] = acc.get(k, 0) + s
            if k not in shown or ("́" in t and "́" not in shown[k]):
                shown[k] = t
        return acc

    merged = fold(a.cand.items())
    inv = fold(a.inv.items())
    # Words read backwards from other articles ("le" is mentioned in thousands
    # of glosses) only confirm what the headword's own data says, unless the
    # headword has nothing else or several sources agree on them.
    if merged:
        for k, sc in inv.items():
            if k in merged:
                merged[k] += sc
            elif sc >= 2 * W_INV_TABLE:
                merged[k] = sc * 0.5
    else:
        merged = inv
    if inv:
        a.src.add("inv")
    top = [shown[k] for k, _ in sorted(merged.items(), key=score)][:MAX_T]
    rec = {"w": a.w}
    if a.h:
        rec["h"] = a.h
    if a.p:
        rec["p"] = a.p
    if a.gd:
        rec["gd"] = a.gd
    if a.a:
        rec["a"] = a.a
    if top:
        rec["t"] = top
    if a.senses:
        rec["s"] = a.senses[:MAX_SENSES]
    rec["src"] = sorted(a.src)
    return rec


def write_pair(pair, d, forms, other_rank):
    entries = defaultdict(list)
    for (k, _p), a in d.arts.items():
        rec = finish(a, other_rank)
        if rec:
            entries[k].append(rec)
    # A form only matters if it leads to an article. It is kept even when the
    # form is a headword itself ("ran" the name, "saw" the tool): a lookup shows
    # both. Values are article keys.
    # Finnish or Hungarian tables run to hundreds of forms per word (possessive
    # suffixes and the like); the first ones listed are the common ones.
    # A pair attested by several editions (went -> go) comes before a stray
    # one; "go" is not a form of "go on".
    fmap = defaultdict(list)
    per_lemma = defaultdict(int)
    counts = defaultdict(int)
    for form, lemma in forms:
        fk, lk = key_of(d.lang, form), key_of(d.lang, lemma)
        if fk != lk and lk in entries and not (" " in lk and " " not in fk):
            counts[(fk, lk)] += 1
    for (fk, lk), _n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if len(fmap[fk]) >= 3:
            continue
        if per_lemma[lk] >= MAX_FORMS:
            continue
        per_lemma[lk] += 1
        fmap[fk].append(lk)
    if d.lang == "ru":  # ёлка is also typed елка
        for k in list(entries):
            if "ё" in k:
                e = k.replace("ё", "е")
                if e not in entries and k not in fmap[e]:
                    fmap[e].append(k)
    if d.lang == "sr":  # Serbian is written in both scripts; the data is Cyrillic
        for k in list(entries):
            lat = sr_latin(k)
            if lat != k and k not in fmap[lat]:
                fmap[lat].append(k)
        for k, v in list(fmap.items()):
            lat = sr_latin(k)
            if lat != k:
                fmap[lat].extend(x for x in v if x not in fmap[lat])

    total = sum(len(orjson.dumps(v)) for v in entries.values()) + sum(len(orjson.dumps(v)) for v in fmap.values())
    n = 1
    while total / n > SHARD_BYTES:
        n *= 2
    shards = [{"e": {}, "f": {}} for _ in range(n)]
    for k, v in entries.items():
        shards[fnv1a(k) % n]["e"][k] = v
    for k, v in fmap.items():
        shards[fnv1a(k) % n]["f"][k] = v

    base = os.path.join(OUT, pair)
    os.makedirs(base, exist_ok=True)
    for old in os.listdir(base):
        os.remove(os.path.join(base, old))
    size = 0
    for i, sh in enumerate(shards):
        data = orjson.dumps(sh)
        size += len(data)
        with open(os.path.join(base, f"{i}.json"), "wb") as f:
            f.write(data)
    manifest = {
        "pair": pair, "buckets": n, "hash": "fnv1a32-utf16",
        "entries": len(entries), "forms": len(fmap), "bytes": size,
    }
    with open(os.path.join(base, "manifest.json"), "wb") as f:
        f.write(orjson.dumps(manifest, option=orjson.OPT_INDENT_2))
    return manifest, entries, fmap


def build(x):
    rank_ru, rank_x = freq_rank("ru"), freq_rank(x)
    has_x_edition = os.path.isdir(os.path.join(STAGE, x))

    # ------------------------------------------------ ru -> x
    ru = Dict("ru")
    if has_x_edition:
        add_definitions(ru, stage(x, "ruent"), x, f"{x}wikt")
    add_table(ru, (r for r in stage("ru", f"tr.{x}") if r["d"] == "ru"), "ruwikt")
    inv = []
    for ed in {"ru", x, "en"}:
        for r in stage(ed, f"tr.{x}"):
            if r["d"] == x:
                inv.append((r["t"], r["w"], None))
    add_inverse(ru, inv, W_INV_TABLE, "inv", rank_ru)
    inv = []
    for r in stage("ru", f"xent.{x}"):
        for s in r["s"]:
            for t in terms(s["g"], "ru"):
                inv.append((LEAD.sub("", t), r["w"], None))
    add_inverse(ru, inv, W_INV_DEF, "inv", rank_ru)

    # ------------------------------------------------ x -> ru
    xr = Dict(x)
    add_definitions(xr, stage("ru", f"xent.{x}"), "ru", "ruwikt")
    for ed in {x, "en"} if x == "en" else {x}:
        add_table(xr, (r for r in stage(ed, f"tr.{x}") if r["d"] == x), f"{ed}wikt")
    inv = [(r["t"], r["w"], None) for r in stage("ru", f"tr.{x}") if r["d"] == "ru"]
    add_inverse(xr, inv, W_INV_TABLE, "inv", rank_x)
    if has_x_edition:
        inv = []
        for r in stage(x, "ruent"):
            for s in r["s"][:6]:
                for t in terms(s["g"], x):
                    inv.append((LEAD.sub("", t), r["w"], None))
        add_inverse(xr, inv, W_INV_DEF, "inv", rank_x)

    # ------------------------------------------------ pivot through English senses
    if x != "en":
        for r in stage("en", "pivot"):
            rus, xs = r["t"].get("ru"), r["t"].get(x)
            if not rus or not xs:
                continue
            # Only where direct sources say little, and only for real words:
            # an article is created only for words the frequency list knows.
            for rw in rus[:3]:
                a = ru.any(rw)
                if a is None and bare_ru(rw) in rank_ru:
                    a = ru.get(rw, r.get("p"))
                if a is not None and len(a.cand) < 3:
                    for t in xs[:3]:
                        a.add(t, W_PIVOT, "pivot")
            for xw in xs[:3]:
                a = xr.any(xw)
                if a is None and key_x(xw) in rank_x:
                    a = xr.get(xw, r.get("p"))
                if a is not None and len(a.cand) < 3:
                    for t in rus[:3]:
                        a.add(t, W_PIVOT, "pivot")

    forms_x = []
    for ed in os.listdir(STAGE):
        forms_x.extend(tuple(p) for p in read(os.path.join(STAGE, ed, f"forms.{x}.jsonl")))

    m1 = write_pair(f"ru-{x}", ru, [], rank_x)
    m2 = write_pair(f"{x}-ru", xr, forms_x, rank_ru)
    return m1, m2


def main():
    langs = sys.argv[1:] or TARGETS
    for x in langs:
        (m1, _, _), (m2, _, _) = build(x)
        for m in (m1, m2):
            print(f"{m['pair']:7} {m['entries']:>8,} entries {m['forms']:>8,} forms "
                  f"{m['bytes'] / 1e6:7.1f} MB in {m['buckets']} shards", flush=True)


if __name__ == "__main__":
    main()
