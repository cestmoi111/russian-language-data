"""The 24 languages paired with Russian, and how Wiktionary spells them."""

import re

# THE LEV extension's languages (langs.js) minus sl, lt, bg, whose Wiktionary
# coverage was too thin; zh-CN and zh-TW share one dictionary.
TARGETS = [
    "en", "es", "fr", "de", "it", "pt", "nl", "pl", "cs", "sk", "sr",
    "hr", "ro", "el", "hu", "fi", "sv", "no", "da", "lv", "et", "tr", "zh", "ja",
]
_T = set(TARGETS)

# Wiktionary codes that fold into one of ours.
ALIASES = {"nb": "no", "nn": "no", "cmn": "zh"}
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def wikt_to_target(code, word=""):
    """Map a Wiktionary language code to one of TARGETS (or "ru"), else None.

    Serbo-Croatian ("sh") is one language on en.wiktionary: Cyrillic spellings
    go to Serbian, Latin ones to Croatian.
    """
    if not code:
        return None
    code = ALIASES.get(code, code)
    if code == "ru" or code in _T:
        return code
    if code == "sh":
        return "sr" if CYRILLIC.search(word or "") else "hr"
    return None
