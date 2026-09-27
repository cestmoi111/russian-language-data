"""How much of real usage the dictionaries answer.

    python scripts/dict/coverage.py en fr [--top 10000]

Takes the most frequent word forms of subtitles (.cache/freq, OpenSubtitles
2018 via hermitdave/FrequencyWords), brings each to its dictionary form and
counts how many get an article with at least one translation. Russian forms
are lemmatised with pymorphy3; for the other language the dictionary's own
form table is used, so that part of the test also checks the forms.
"""

import json
import os
import sys

import pymorphy3

from build import FREQ, FREQ_FILE, OUT, bare_ru, fnv1a, key_x
from langs import CYRILLIC

morph = pymorphy3.MorphAnalyzer()
ELISION = {"c": "ce", "l": "le", "j": "je", "d": "de", "qu": "que", "n": "ne", "t": "te",
           "m": "me", "s": "se", "quelqu": "quelque", "jusqu": "jusque", "lorsqu": "lorsque",
           "puisqu": "puisque", "dell": "dello", "all": "allo", "un": "uno", "po": "poco"}


class Pair:
    def __init__(self, pair):
        self.base = os.path.join(OUT, pair)
        self.m = json.load(open(os.path.join(self.base, "manifest.json"), encoding="utf8"))
        self.cache = {}

    def shard(self, key):
        i = fnv1a(key) % self.m["buckets"]
        if i not in self.cache:
            self.cache[i] = json.load(open(os.path.join(self.base, f"{i}.json"), encoding="utf8"))
        return self.cache[i]

    def lookup(self, key):
        """The article(s) for a key: its own, then those of its lemmas."""
        out = [a for a in self.shard(key)["e"].get(key, []) if a.get("t")]
        for lemma in self.shard(key)["f"].get(key, []):
            out += self.shard(lemma)["e"].get(lemma, [])
        if not out and "-" in key:  # clitics: avez-vous, dis-moi, allons-y
            return self.lookup(key.split("-")[0])
        return out or None


def words(lang, top):
    path = os.path.join(FREQ, f"{FREQ_FILE.get(lang, lang)}_50k.txt")
    out = []
    with open(path, encoding="utf8") as f:
        for line in f:
            w = line.split(" ")[0].strip()
            if w and any(c.isalpha() for c in w):
                out.append(w)
            if len(out) >= top:
                break
    return out


def ru_side(x, top):
    d = Pair(f"ru-{x}")
    old_path = os.path.join(OUT, "..", "translations", f"{x}.json")
    old = json.load(open(old_path, encoding="utf8")) if os.path.exists(old_path) else None
    hit = old_hit = 0
    miss = []
    ws = words("ru", top)
    for w in ws:
        lemmas = [bare_ru(p.normal_form) for p in morph.parse(w)[:3]] + [bare_ru(w)]
        if any(any(a.get("t") for a in (d.lookup(l) or [])) for l in lemmas):
            hit += 1
        else:
            miss.append(w)
        if old is not None and any(l in old for l in lemmas):
            old_hit += 1
    return len(ws), hit, old_hit if old is not None else None, miss


def x_side(x, top):
    d = Pair(f"{x}-ru")
    alt = Pair("hr-ru") if x == "sr" else None  # the same fallback as lookup.mjs
    hit = 0
    miss = []
    ws = words(x, top)
    for w in ws:
        k = key_x(w)
        # Subtitle tokenisers cut elisions off: c' l' qu' are ce le que.
        if k.endswith(("'", "’")):
            k = ELISION.get(k[:-1], k[:-1])
        e = d.lookup(k) or (alt.lookup(k) if alt and not CYRILLIC.search(k) else None)
        if e and any(a.get("t") for a in e):
            hit += 1
        else:
            miss.append(w)
    return len(ws), hit, miss


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    top = 10000
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1])
        del args[i:i + 2]
    for x in args:
        n, hit, old, miss_ru = ru_side(x, top)
        line = f"ru-{x}: {hit / n:6.1%} of top {n} Russian forms"
        if old is not None:
            line += f"   (old translations/{x}.json: {old / n:.1%})"
        print(line)
        n, hit, miss_x = x_side(x, top)
        print(f"{x}-ru: {hit / n:6.1%} of top {n} {x} forms")
        print("   missing ru:", " ".join(miss_ru[:40]))
        print(f"   missing {x}:", " ".join(miss_x[:40]))


if __name__ == "__main__":
    main()
