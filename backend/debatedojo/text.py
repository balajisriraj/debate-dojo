"""Small text utilities shared by the agents and the scripted model."""

from __future__ import annotations

import re
from typing import Any

DASHES = re.compile("\\s*[\\u2013\\u2014]\\s*")  # en and em dash; the house style uses plain hyphens

_STOPWORDS = """
a an the and or but if so of to in on at by for with from as is are was were be been being it its
it's this that these those there their they them we our us you your i me my he she his her him not
no do does did doing have has had having will would should could can may might must just very
really also too than then which who what when where why how all any some more most such only own
same into over under about again further once here out up down off both each few other nor yes i'm
you're we're they're that's what's don't isn't aren't won't can't let let's get got make made going
go say said think know want need like one two well because
"""
STOPWORDS = frozenset(_STOPWORDS.split())

_SENTENCE = re.compile(r"[^.!?]+[.!?]*")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def clean(value: Any) -> Any:
    """Replace em and en dashes with a plain hyphen, recursively through dicts and lists."""
    if isinstance(value, str):
        return DASHES.sub(" - ", value)
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    return value


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text.replace("\n", " ")) if len(s.strip().split()) >= 2]


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("’", "'"))


def content_words(text: str) -> set[str]:
    return {w for w in words(text) if w not in STOPWORDS and len(w) > 2}


def _stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def stems(text: str) -> set[str]:
    return {_stem(w) for w in content_words(text)}


def overlap(a: str, b: str) -> float:
    """Share of ``b``'s content stems that ``a`` picks up, from 0 to 1."""
    sb = stems(b)
    if not sb:
        return 0.0
    return len(stems(a) & sb) / min(len(sb), 12)


def find_quote(quote: str, texts: list[str]) -> tuple[int, str] | None:
    """Locate ``quote`` in one of ``texts`` ignoring case, spacing and punctuation.

    Returns the index of the text and the exact original wording, so a quote shown to the user
    is always their own words.
    """
    tokens = words(quote)
    if not tokens:
        return None
    pattern = re.compile(r"\W+".join(re.escape(t) for t in tokens), re.I)
    for i, text in enumerate(texts):
        m = pattern.search(text.replace("’", "'"))
        if m:
            return i, text[m.start() : m.end()]
    return None


def closest_sentence(quote: str, texts: list[str]) -> tuple[int, str] | None:
    """The sentence across ``texts`` that shares the most words with ``quote``."""
    best: tuple[float, int, str] | None = None
    target = set(words(quote))
    for i, text in enumerate(texts):
        for s in sentences(text) or ([text.strip()] if text.strip() else []):
            score = len(target & set(words(s))) / (len(target) or 1)
            if best is None or score > best[0]:
                best = (score, i, s)
    return (best[1], best[2]) if best else None


def shorten(text: str, max_words: int = 18) -> str:
    """Trim to a clause of at most ``max_words`` words, cutting at a comma where one is close."""
    ws = text.strip().rstrip(".!?").split()
    if len(ws) <= max_words:
        return " ".join(ws)
    head = " ".join(ws[:max_words])
    comma = max(head.rfind(","), head.rfind(";"))
    if comma > len(head) * 0.45:
        return head[:comma]
    return head.rstrip(",;:") + "..."
