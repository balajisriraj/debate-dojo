"""Delivery metrics for a turn: pace, filler words, pauses and talk time against the limit.

The same rules run in the browser (``frontend/src/delivery.ts``) for the live meter, and both
implementations are tested against one fixture (``fixtures/delivery-cases.json``). Speech
recognition output usually has no punctuation, so the rules lean on neighbouring words rather
than commas, and they are deliberately conservative: "I like this" and "do you know" are not
fillers.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

FILLERS = ("um", "uh", "like", "you know", "basically", "sort of")

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[,]|[.!?;:]")
_UM = {"um", "umm", "ummm", "erm", "hmm"}
_UH = {"uh", "uhh", "uhm", "er"}

# "like" is a filler after these words ("it was like really"), unless what follows makes it a comparison.
_LIKE_AFTER = {
    "um",
    "uh",
    "and",
    "so",
    "was",
    "is",
    "it's",
    "were",
    "i'm",
    "they're",
    "we're",
    "you're",
    "be",
    "been",
    "just",
    "but",
}
_LIKE_NOT_BEFORE = {
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "it",
    "me",
    "you",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "our",
    "their",
    "his",
    "its",
    "to",
    "what",
    "how",
    "when",
}
# "you know" is part of a real question or clause after these words, or before these.
_YK_NOT_AFTER = {
    "do",
    "did",
    "don't",
    "didn't",
    "if",
    "as",
    "would",
    "could",
    "should",
    "will",
    "might",
    "may",
    "let",
    "what",
    "how",
    "you",
    "now",
    "then",
}
_YK_NOT_BEFORE = {
    "what",
    "how",
    "why",
    "when",
    "where",
    "who",
    "which",
    "that",
    "if",
    "whether",
    "the",
    "a",
    "an",
    "about",
    "him",
    "her",
    "them",
    "it",
    "this",
    "me",
    "us",
    "more",
    "better",
}
_SORT_NOT_AFTER = {
    "a",
    "the",
    "what",
    "that",
    "this",
    "some",
    "any",
    "which",
    "every",
    "one",
    "no",
    "each",
    "same",
    "right",
    "wrong",
}


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    return [("." if t in ".!?;:" else t) for t in _TOKEN.findall(text)]


def count_fillers(text: str) -> dict[str, int]:
    tokens = tokenize(text)
    counts = dict.fromkeys(FILLERS, 0)
    n = len(tokens)
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else "."
        nxt = tokens[i + 1] if i + 1 < n else "."
        if tok in _UM:
            counts["um"] += 1
        elif tok in _UH:
            counts["uh"] += 1
        elif tok == "basically":
            counts["basically"] += 1
        elif tok == "like":
            if (
                prev == ","
                or nxt == ","
                or nxt in _UM
                or nxt in _UH
                or (prev in _LIKE_AFTER and nxt not in _LIKE_NOT_BEFORE)
            ):
                counts["like"] += 1
        elif tok == "you" and nxt == "know":
            after = tokens[i + 2] if i + 2 < n else "."
            if after in {",", "."} or (prev not in _YK_NOT_AFTER and after not in _YK_NOT_BEFORE):
                counts["you know"] += 1
        elif tok == "sort" and nxt == "of" and prev not in _SORT_NOT_AFTER:
            counts["sort of"] += 1
    return counts


def word_count(text: str) -> int:
    return sum(1 for t in tokenize(text) if t not in {",", "."})


def words_per_minute(words: int, seconds: float | None) -> float | None:
    """Pace over the time actually spent speaking. Too short a sample says nothing, so it is None."""
    if not seconds or seconds < 3 or words == 0:
        return None
    return round(words / (seconds / 60), 1)


class Delivery(BaseModel):
    source: str  # "voice" or "typed"
    words: int
    wpm: float | None
    fillers: dict[str, int]
    filler_total: int
    fillers_per_100: float
    longest_pause_s: float | None
    talk_seconds: float
    limit_seconds: int
    talk_ratio: float
    over_time: bool


def measure(
    text: str,
    *,
    source: str,
    talk_seconds: float,
    limit_seconds: int,
    longest_pause_s: float | None = None,
    over_time: bool = False,
) -> Delivery:
    words = word_count(text)
    fillers = count_fillers(text)
    total = sum(fillers.values())
    spoken = source == "voice"
    return Delivery(
        source=source,
        words=words,
        # Pace only means something for speech; a typed turn's duration is thinking time.
        wpm=words_per_minute(words, talk_seconds) if spoken else None,
        fillers=fillers,
        filler_total=total,
        fillers_per_100=round(100 * total / words, 1) if words else 0.0,
        longest_pause_s=round(longest_pause_s, 1) if spoken and longest_pause_s is not None else None,
        talk_seconds=round(talk_seconds, 1),
        limit_seconds=limit_seconds,
        talk_ratio=round(talk_seconds / limit_seconds, 2) if limit_seconds else 0.0,
        over_time=over_time,
    )


def summarise(deliveries: list[Delivery]) -> dict:
    """Session-level delivery, for the judge: averages over spoken turns where they exist."""
    if not deliveries:
        return {"turns": 0, "spoken_turns": 0}
    spoken = [d for d in deliveries if d.source == "voice"]
    paces = [d.wpm for d in spoken if d.wpm is not None]
    pauses = [d.longest_pause_s for d in spoken if d.longest_pause_s is not None]
    words = sum(d.words for d in deliveries)
    fillers = sum(d.filler_total for d in deliveries)
    return {
        "turns": len(deliveries),
        "spoken_turns": len(spoken),
        "avg_wpm": round(sum(paces) / len(paces), 1) if paces else None,
        "fillers_per_100": round(100 * fillers / words, 1) if words else 0.0,
        "filler_total": fillers,
        "longest_pause_s": max(pauses) if pauses else None,
        "over_time_turns": sum(d.over_time for d in deliveries),
        "avg_talk_ratio": round(sum(d.talk_ratio for d in deliveries) / len(deliveries), 2),
    }
