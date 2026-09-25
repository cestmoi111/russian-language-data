# -*- coding: utf-8 -*-
"""
Builds data/aspect-db.json: the aspect of EVERY Russian verb plus every
imperfective/perfective pair we can attest.

    python scripts/build-aspect-db.py

Why this exists next to aspect-pairs-db.json: that older file is a flat list of
{impf, perf} pairs, which answers "what is the partner of X" but not "what
aspect is X" - and it silently loses the fact that one written verb can belong
to SEVERAL pairs with a DIFFERENT aspect in each. "считать" is imperfective in
считать/счесть ("consider") and perfective in считывать/считать ("read off");
its reflexive "считаться" is imperfective in считаться/счесться and perfective
in считываться/считаться. A consumer that keeps one pair per headword has to
pick one of those at random, and gets it wrong half the time.

Sources
  1. OpenCorpora, via the pymorphy3 dictionary - the aspect grammeme of every
     verb lemma (~31k, reflexives included). This is the authority for the
     label we print next to a word.
  2. OpenRussian (Badestrand/russian-dictionary) - the partner column, i.e.
     the pairs themselves, plus a short English gloss.
  3. Derivation - a pair of plain verbs (X / Y) yields the reflexive pair
     (Xся / Yся) when at least one of those reflexives is a known verb.
     OpenRussian's partner column covers reflexives thinly, and this is how
     считываться/считаться gets in at all.

Every pair is checked against OpenCorpora before it is kept: if OpenCorpora
says the member OpenRussian filed as imperfective is perfective-only (and vice
versa) the pair is flipped; if only one side contradicts, the pair is dropped.

Output (data/aspect-db.json)

    {
      "aspect": { "impf": [lemmas...], "perf": [lemmas...], "both": [lemmas...] },
      "pairs":  [ ["считывать", "считать", "read off", "or"], ... ]
    }

  aspect  - every verb lemma OpenCorpora knows, bucketed by ITS OWN verdict.
            "both" means the one lemma carries both grammemes: either a
            genuinely biaspectual verb (использовать) or two homographic verbs
            (считать). A pair may still attest an aspect this table does not
            list, so a consumer reads both keys: the bucket is the dictionary
            label, the pairs are what that verb pairs with in each reading.
  pairs   - [imperfective, perfective, gloss, source]; source is "or"
            (OpenRussian) or "refl" (derived reflexive). Sorted by the
            imperfective member. Arrays, not objects: 11k records, and the key
            names would be two thirds of the file.

Both source datasets are CC BY-SA 4.0 / CC BY-SA; see NOTICE.
"""

import collections
import csv
import io
import json
import os
import re
import unicodedata
import urllib.request

import pymorphy3

RAW = "https://raw.githubusercontent.com/Badestrand/russian-dictionary/master"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# ё and й both decompose under NFD (ё -> е + U+0308, й -> и + U+0306), so they
# are swapped out for private-use placeholders before the diacritic strip and
# swapped back after - same trick as scripts/build-language-db.mjs.
_YO = {"ё": "", "Ё": "", "й": "", "Й": ""}


def bare(s):
    """A lookup-ready headword: no stress marks, ё/й intact, lowercased."""
    s = "".join(_YO.get(c, c) for c in (s or ""))
    s = unicodedata.normalize("NFD", s)
    s = re.sub(r"[̀-ͯ'`]", "", s)
    s = s.replace("", "ё").replace("", "й")
    return s.lower().strip()


def is_word(s):
    """OpenRussian uses "-" / "_" as placeholder headwords; reject those."""
    return bool(re.fullmatch(r"[а-яё]{2,}(-[а-яё]+)*", s or ""))


def cell_forms(cell):
    """The partner column may list alternatives: "честь;счесть;посчитать"."""
    return [w for w in (bare(x) for x in re.split(r"[,;]", cell or "")) if is_word(w)]


def fetch_table(name):
    with urllib.request.urlopen(RAW + "/" + name + ".csv") as r:
        text = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def main():
    morph = pymorphy3.MorphAnalyzer()

    # ---- 1. OpenCorpora: lemma -> {"impf"} / {"perf"} / both ---------------
    oc = collections.defaultdict(set)
    for _word, tag, lemma, _para, _idx in morph.dictionary.iter_known_words():
        if tag.POS in ("INFN", "VERB") and tag.aspect:
            oc[lemma].add(str(tag.aspect))

    # ---- 2. OpenRussian: the pairs ----------------------------------------
    verbs = fetch_table("verbs")
    gloss_of = {}
    for r in verbs:
        b = cell_forms(r["bare"])
        if b:
            gloss_of.setdefault(b[0], (r.get("translations_en") or "").split(",")[0].strip())

    pairs = {}

    def add(impf, perf, gloss, src):
        if not (is_word(impf) and is_word(perf)) or impf == perf:
            return False
        key = (impf, perf)
        if key in pairs:
            if src == "or":  # OpenRussian outranks a derived duplicate
                pairs[key][3] = "or"
            return False
        pairs[key] = [impf, perf, gloss or gloss_of.get(impf, "") or "", src]
        return True

    flipped = dropped = 0
    for r in verbs:
        selves = cell_forms(r["bare"])
        if not selves:
            continue
        self = selves[0]
        gloss = (r.get("translations_en") or "").split(",")[0].strip()
        for partner in cell_forms(r["partner"]):
            aspect = r.get("aspect")
            if aspect == "imperfective":
                impf, perf = self, partner
            elif aspect == "perfective":
                impf, perf = partner, self
            else:
                # Biaspectual row: let the partner's own aspect place the pair.
                pa = oc.get(partner, set())
                if pa == {"perf"}:
                    impf, perf = self, partner
                elif pa == {"impf"}:
                    impf, perf = partner, self
                else:
                    continue

            ai, ap = oc.get(impf, set()), oc.get(perf, set())
            if ai == {"perf"} and ap == {"impf"}:
                impf, perf = perf, impf  # OpenRussian had the row backwards
                flipped += 1
            elif (ai and "impf" not in ai) or (ap and "perf" not in ap):
                dropped += 1
                continue
            add(impf, perf, gloss, "or")

    from_source = len(pairs)

    # ---- 3. Derived reflexive pairs ---------------------------------------
    # одевать/одеть -> одеваться/одеться, считывать/считать -> считываться/
    # считаться. Aspect is carried by the stem, so the -ся form of an
    # imperfective is imperfective; we only add the pair when OpenCorpora
    # actually knows one of the two reflexives, so nothing is invented.
    derived = 0
    for impf, perf, gloss, _src in list(pairs.values()):
        if impf.endswith(("ся", "сь")) or perf.endswith(("ся", "сь")):
            continue
        r_impf, r_perf = impf + "ся", perf + "ся"
        if r_impf in oc or r_perf in oc:
            if add(r_impf, r_perf, gloss, "refl"):
                derived += 1

    # The aspect buckets stay OpenCorpora's own verdict, NOT the union with the
    # pairs. A derived pair can attest an aspect OpenCorpora does not list -
    # "считаться" is imperfective there and perfective only as the partner of
    # считываться - and a consumer needs to tell the dictionary reading (the
    # label to print) from the one the pairs imply (a second line, if it shows
    # one at all). Union the two and that distinction is gone.
    buckets = {"impf": [], "perf": [], "both": []}
    for lemma in sorted(oc):
        a = oc[lemma]
        buckets["both" if len(a) > 1 else next(iter(a))].append(lemma)

    pairs_arr = sorted(pairs.values(), key=lambda p: (p[0], p[1]))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "aspect-db.json")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(
            {"aspect": buckets, "pairs": pairs_arr},
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        f.write("\n")

    print(
        "aspect-db.json: %d verbs (impf %d, perf %d, both %d), %d pairs "
        "(%d OpenRussian, %d derived reflexive; %d flipped, %d dropped as contradictory)"
        % (
            len(oc),
            len(buckets["impf"]),
            len(buckets["perf"]),
            len(buckets["both"]),
            len(pairs_arr),
            from_source,
            derived,
            flipped,
            dropped,
        )
    )


if __name__ == "__main__":
    main()
