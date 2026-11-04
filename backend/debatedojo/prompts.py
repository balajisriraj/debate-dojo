"""Prompts for the four agents.

Context goes in simple XML-style tags. Claude reads them as structure; the scripted model parses
the same tags, so tests exercise the real prompt assembly.
"""

from __future__ import annotations

import json
import re
from html import escape

from .formats import Persona
from .rubric import rubric_text

STYLE = (
    "Write in British English. Never use em dashes or en dashes; use a plain hyphen or a new sentence. "
    "No markdown, lists or headings."
)

MODE_BRIEF = {
    "debate": "This is formal debate practice. You argue the other side of the motion from the user, as a strong, fair opponent.",
    "meeting": "This is meeting practice. The user is pitching a proposal and you are a sceptical stakeholder in the room.",
    "sales": "This is sales practice. The user is selling and you are the buyer. You raise realistic objections.",
}

ROLE = {
    "opening": "Give the opposing opening speech. Answer how they framed the motion, then set out two or three arguments of your own.",
    "constructive": "Give your constructive case. Name a competing value and criterion, contrast them with theirs, and build your case on them.",
    "rebuttal": "Rebut. Take their strongest points in turn and show why each fails, then defend your own case against what they said.",
    "closing": "Close. No new arguments. Weigh the clashes that mattered and say why your side won them.",
    "answer": "They are cross-examining you. Answer their question directly and briefly, concede only what you must, then ask one pointed question back.",
    "rapid": "Rapid fire. Two or three sentences: hit back at their point, then make one of your own.",
    "probe": "React to the pitch in character: credit one thing specifically, then raise your first concern.",
    "pushback": "Say whether their answer settles your last concern and why, then push on the next concern.",
    "object": "Respond to what they just said as the buyer. If they handled your last objection well, give a little ground. Then raise the next objection.",
    "decide": "They are closing. Respond as a real person would: agree to a next step if they have earned it, or name exactly what is still missing.",
}

OBJECTIONS = {
    "price": "price: it costs more than budgeted, or cheaper options exist",
    "timing": "timing: now is not a good time, there is too much on",
    "incumbent": "incumbent: we already use something for this and switching is a project",
    "authority": "authority: you cannot commit without checking with your boss",
}

WORDS_PER_SECOND = 0.8


def reply_words(seconds: int) -> int:
    """How long the opponent's reply should be, scaled to the user's turn length."""
    return max(40, min(170, round(seconds * WORDS_PER_SECOND)))


def opponent_side(side: str | None) -> str | None:
    if side is None:
        return None
    return "opposition" if side == "proposition" else "proposition"


def _persona_tag(persona: Persona) -> str:
    return f'<persona name="{escape(persona.name)}" role="{escape(persona.role)}">{escape(persona.style)}</persona>'


def opponent_system(session: dict, persona: Persona, slot: dict, opponent_turns: int) -> str:
    mode = session["mode"]
    lines = [
        f"You are {persona.name}, the opponent in DebateDojo, a practice arena. {MODE_BRIEF[mode]}",
        f"<mode>{mode}</mode>",
        _persona_tag(persona),
        f"<topic>{escape(session['topic'])}</topic>",
    ]
    if session.get("side"):
        lines.append(f"<user_side>{session['side']}</user_side>")
        lines.append(f"<your_side>{opponent_side(session['side'])}</your_side>")
    if session.get("context"):
        lines.append(f"<context>{escape(session['context'])}</context>")
    lines.append(
        f'<phase id="{slot["phase_id"]}" name="{escape(slot["phase_name"])}" role="{slot["opponent_role"]}" '
        f'exchange="{slot["exchange"]}" of="{slot["exchanges"]}" />'
    )
    if mode == "meeting" and persona.concerns:
        lines.append(f"<concern_now>{persona.concerns[opponent_turns % len(persona.concerns)]}</concern_now>")
    if mode == "sales" and persona.objections and slot["opponent_role"] == "object":
        if opponent_turns < len(persona.objections):
            objection = OBJECTIONS[persona.objections[opponent_turns]]
        else:
            objection = "none left: you have raised them all, so ask what the next step would look like"
        lines.append(f"<objection_now>{objection}</objection_now>")
    lines += [
        "",
        "How to reply:",
        "- Engage with the user's latest turn first. Name their strongest point in a few of their own words and answer it. "
        "Never ignore what they said to deliver a prepared speech.",
        f"- {ROLE[slot['opponent_role']]}",
        f"- About {reply_words(slot['seconds'])} words. It is read aloud, so write it as speech.",
        "- Do not invent statistics or sources. If a number helps, frame it as a hypothetical.",
        "- Stay in character for the whole session.",
        f"- {STYLE}",
    ]
    return "\n".join(lines)


def opponent_messages(turns: list[dict]) -> list[dict]:
    """The session so far as alternating messages: the user's turns, then the opponent's."""
    messages = []
    for t in turns:
        role = "user" if t["speaker"] == "user" else "assistant"
        text = t["text"].strip() or "(The user ran out of time without saying anything.)"
        if role == "user" and t.get("timed_out"):
            text += "\n(Time ran out on this turn.)"
        messages.append({"role": role, "content": text})
    return messages


FACT_CHECK_SYSTEM = """You fact-check one turn from a practice {mode} on: {topic}.
List the factual claims in the turn. Opinions, values, proposals and predictions are not claims.
For each claim give a verdict:
- supported: well established or common knowledge
- unsupported: a specific figure, study or fact given with no source
- doubtful: likely wrong, overstated, or an absolute that does not hold
Give a one-line reason and the kind of evidence that would back it. Quote each claim exactly as written.
{method}
Never invent or name sources you have not seen. {style}"""

KNOWLEDGE_ONLY = "You have no web access. Judge on what you know, and say so in the reason when you are unsure."
WITH_RESEARCH = (
    "Research notes from a web search are included. Rely on them where they apply; otherwise judge on what you know."
)


def fact_check_system(session: dict, research: bool) -> str:
    return FACT_CHECK_SYSTEM.format(
        mode=session["mode"],
        topic=session["topic"],
        method=WITH_RESEARCH if research else KNOWLEDGE_ONLY,
        style=STYLE,
    )


def fact_check_message(text: str, notes: str = "") -> list[dict]:
    body = f"<turn>{escape(text)}</turn>"
    if notes:
        body += f"\n<research>{escape(notes)}</research>"
    return [{"role": "user", "content": body}]


RESEARCH_SYSTEM = (
    "Search the web to check the factual claims in this turn from a practice debate. For each claim, note in one "
    "or two sentences what reliable sources say. Keep it brief. Do not judge opinions."
)


def transcript_block(turns: list[dict]) -> str:
    lines = []
    n = 0
    for t in turns:
        text = escape(t["text"].strip() or "(no response, time ran out)")
        if t["speaker"] == "user":
            n += 1
            attrs = f'n="{n}" speaker="you" phase="{escape(t["phase_name"])}" input="{t["input"]}"'
            if t.get("timed_out"):
                attrs += ' timed_out="true"'
            lines.append(f"<turn {attrs}>{text}</turn>")
        else:
            lines.append(f'<turn speaker="opponent" phase="{escape(t["phase_name"])}">{text}</turn>')
    return "<transcript>\n" + "\n".join(lines) + "\n</transcript>"


def flags_block(turns: list[dict]) -> str:
    flags, n = [], 0
    for t in turns:
        if t["speaker"] != "user":
            continue
        n += 1
        flags += [{"turn": n, "claim": f["claim"], "verdict": f["verdict"], "reason": f["reason"]} for f in t["flags"]]
    return f"<flags>{json.dumps(flags)}</flags>"


JUDGE_SYSTEM = """You are the judge for a practice {mode} in DebateDojo. Score only the user ("you"), never the opponent.
Topic: {topic}
Rubric, each scored 1 to 10:
{rubric}

For every criterion, in this order, give a score, an explanation of two or three sentences that is specific to
what the user actually did, and a quote: the user's own words copied exactly from one of their turns that best
evidences the score. Give the number of the turn it comes from. A low score's quote shows the weakness.
Use the delivery metrics for delivery-related judgements. Typed turns have no pace or pause data; judge their
concision and filler words instead. Fact-check flags count against evidence.
Be a fair, demanding judge: 5 is competent, 8 is strong, 10 is rare. {style}"""


def judge_system(session: dict) -> str:
    return JUDGE_SYSTEM.format(
        mode=session["mode"], topic=session["topic"], rubric=rubric_text(session["mode"]), style=STYLE
    )


def judge_message(session: dict, persona: Persona, turns: list[dict], delivery: dict) -> list[dict]:
    body = "\n".join(
        [
            f"<mode>{session['mode']}</mode>",
            f"<topic>{escape(session['topic'])}</topic>",
            _persona_tag(persona),
            *([f"<user_side>{session['side']}</user_side>"] if session.get("side") else []),
            *([f"<context>{escape(session['context'])}</context>"] if session.get("context") else []),
            transcript_block(turns),
            f"<delivery>{json.dumps(delivery)}</delivery>",
            flags_block(turns),
        ]
    )
    return [{"role": "user", "content": body}]


COACH_SYSTEM = """You are the coach in DebateDojo, after a practice {mode}. You have the transcript and the judge's scorecard.
Give exactly three improvements, the highest leverage first: each a short imperative title, why it matters for
this user (tied to what they did) and a drill for next session.
Then pick the user's weakest turn and rewrite it as a model answer: in their voice, about the same length, keeping
their ideas but fixing what the scorecard found. Do not invent statistics; if a number is needed, use a placeholder
the user would fill in, like [your figure]. Explain in two to four short points why the rewrite is stronger. {style}"""


def coach_system(session: dict) -> str:
    return COACH_SYSTEM.format(mode=session["mode"], style=STYLE)


def coach_message(session: dict, persona: Persona, turns: list[dict], scorecard: dict) -> list[dict]:
    card = {"scores": [{k: s[k] for k in ("criterion", "score", "explanation", "turn")} for s in scorecard["scores"]]}
    body = "\n".join(
        [
            f"<mode>{session['mode']}</mode>",
            f"<topic>{escape(session['topic'])}</topic>",
            _persona_tag(persona),
            *([f"<context>{escape(session['context'])}</context>"] if session.get("context") else []),
            transcript_block(turns),
            f"<scorecard>{json.dumps(card)}</scorecard>",
        ]
    )
    return [{"role": "user", "content": body}]


# ── parsing, shared with the scripted model ──

_TAG = re.compile(r"<(\w+)>(.*?)</\1>", re.S)


def tags(text: str) -> dict[str, str]:
    from html import unescape

    return {k: unescape(v) for k, v in _TAG.findall(text)}


def parse_transcript(text: str) -> list[dict]:
    from html import unescape

    out = []
    for attrs, body in re.findall(r"<turn ([^>]*)>(.*?)</turn>", text, re.S):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        out.append(
            {
                "speaker": "user" if a.get("speaker") == "you" else "opponent",
                "n": int(a["n"]) if "n" in a else None,
                "phase": unescape(a.get("phase", "")),
                "input": a.get("input", ""),
                "timed_out": a.get("timed_out") == "true",
                "text": unescape(body),
            }
        )
    return out
