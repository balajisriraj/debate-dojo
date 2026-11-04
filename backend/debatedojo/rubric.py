"""What the judge scores, per mode, and the shapes every agent returns.

The rubric is fixed per mode so scores are comparable across sessions: that is what makes the
progress view meaningful.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Criterion(BaseModel):
    id: str
    name: str
    looks_for: str


RUBRICS: dict[str, list[Criterion]] = {
    "debate": [
        Criterion(id="argument", name="Argument", looks_for="Clear claims, each backed by a reason and an impact."),
        Criterion(
            id="evidence",
            name="Evidence",
            looks_for="Specific, checkable support: examples, data with a source, mechanisms.",
        ),
        Criterion(
            id="rebuttal", name="Rebuttal", looks_for="Engages the opponent's actual points and explains why they fail."
        ),
        Criterion(
            id="structure",
            name="Structure",
            looks_for="Signposted, ordered, easy to follow; a clear line through each speech.",
        ),
        Criterion(
            id="delivery",
            name="Delivery",
            looks_for="Steady pace, few fillers, uses the time well without running over.",
        ),
    ],
    "meeting": [
        Criterion(id="clarity", name="Clarity", looks_for="Says what is proposed and why in plain, short sentences."),
        Criterion(
            id="data", name="Data", looks_for="Numbers, costs, timelines or results that make the case concrete."
        ),
        Criterion(
            id="pushback",
            name="Handling pushback",
            looks_for="Takes the stakeholder's concern seriously and answers it directly.",
        ),
        Criterion(
            id="common_ground",
            name="Common ground",
            looks_for="Connects the proposal to what the stakeholder already cares about.",
        ),
        Criterion(id="ask", name="Clear ask", looks_for="A specific decision requested, with who, what and by when."),
    ],
    "sales": [
        Criterion(
            id="acknowledge",
            name="Acknowledge",
            looks_for="Recognises the objection before answering it; the buyer feels heard.",
        ),
        Criterion(
            id="clarify", name="Clarify", looks_for="Asks a question to understand what is really behind the objection."
        ),
        Criterion(
            id="reframe",
            name="Reframe",
            looks_for="Shifts the frame: cost of doing nothing, value over price, risk of the status quo.",
        ),
        Criterion(
            id="evidence",
            name="Evidence",
            looks_for="Proof the buyer can check: results, a trial, a reference, specifics.",
        ),
        Criterion(id="next_step", name="Next step", looks_for="Proposes a concrete next step with a time on it."),
    ],
}


def rubric_text(mode: str) -> str:
    return "\n".join(f"- {c.id} ({c.name}): {c.looks_for}" for c in RUBRICS[mode])


# ── fact-checker ──


class Claim(BaseModel):
    claim: str = Field(description="The factual claim, quoted exactly as the user said it.")
    verdict: Literal["supported", "unsupported", "doubtful"] = Field(
        description="supported: well established; unsupported: a specific fact or figure with no source given; "
        "doubtful: likely wrong, overstated or an absolute that does not hold."
    )
    reason: str = Field(description="One line on why.")
    evidence_needed: str = Field(
        description="The kind of evidence that would back it, e.g. 'a national survey of teachers'."
    )
    source_urls: list[str] = Field(
        default_factory=list,
        description="URLs from the research notes that bear on this claim. Empty if there are none.",
    )


class FactCheck(BaseModel):
    claims: list[Claim] = Field(
        description="Factual claims in the turn. Opinions, values and predictions are not claims."
    )


# ── judge ──


class Score(BaseModel):
    criterion: str = Field(description="The criterion id from the rubric.")
    score: int = Field(ge=1, le=10)
    explanation: str = Field(description="Two or three sentences on why this score, specific to what the user did.")
    quote: str = Field(
        description="The user's own words, copied exactly from one of their turns, that best evidence the score."
    )
    turn: int = Field(description="The number of the user turn the quote comes from, counting from 1.")


class Scorecard(BaseModel):
    scores: list[Score]
    summary: str = Field(description="Two sentences on the session overall.")
    decision: str = Field(description="A short verdict line, e.g. 'Won on points' or 'Not yet convinced'.")


# ── coach ──


class Improvement(BaseModel):
    title: str = Field(description="A short imperative, e.g. 'Answer their best point first'.")
    why: str = Field(description="Why this is high leverage for this user, tied to what they did.")
    drill: str = Field(description="A concrete thing to practise next session.")


class Coaching(BaseModel):
    improvements: list[Improvement] = Field(description="Exactly three, highest leverage first.")
    weakest_turn: int = Field(description="The number of the user's weakest turn, counting from 1.")
    rewrite: str = Field(
        description="That turn rewritten as a model answer, in the user's voice, about the same length."
    )
    why_stronger: list[str] = Field(description="Two to four reasons the rewrite is stronger.")


ScoreLabel = Literal["weak", "developing", "solid", "strong"]


def label(score: float) -> ScoreLabel:
    if score < 4:
        return "weak"
    if score < 6:
        return "developing"
    if score < 8:
        return "solid"
    return "strong"
