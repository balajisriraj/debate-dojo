"""A deterministic stand-in for Claude, so the whole product runs offline, in tests and in CI.

It reads the same tagged prompts Claude gets and answers from rules rather than a network:

- the opponent keys off the user's actual words: it quotes their strongest point and answers
  the kind of claim it is (a bare statistic, an appeal to unnamed research, an absolute, a causal
  leap), then plays its role for the phase and the mode;
- the fact-checker flags figures without sources, unnamed studies, absolutes and superlatives;
- the judge scores each rubric criterion from observable features of the user's turns and quotes
  the sentence that best evidences the score;
- the coach turns the three lowest criteria into advice and rewrites the weakest turn.

It is not a language model, but it is honest about what it sees, and it is good enough to
practise against and to calibrate the evals.
"""

from __future__ import annotations

import asyncio
import json
import re
import zlib
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

from . import rubric as rb
from .prompts import parse_transcript, tags
from .text import content_words, overlap, sentences, shorten, words

T = TypeVar("T", bound=BaseModel)


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


_NUMWORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty"
    r"|seventy|eighty|ninety|a hundred|hundred|a thousand|thousand|a million|million|billion|a dozen|dozen)"
)
_UNIT = (
    r"(?:per ?cent|percent|pounds|dollars|euros|days?|weeks?|months?|years?|hours?|minutes?|people|staff|agents?"
    r"|customers?|clients?|teachers?|pupils?|students?|times|percentage points|engineers?|developers?|versions?|teams?)"
)
NUMBER = _rx(
    r"(?:[£$€]\s?\d[\d,.]*\w*|\b\d[\d,.]*\s*(?:%|per ?cent\b|percent\b)|\b\d[\d,.]*\b"
    r"|\b(?:half|a third|a quarter|twice|double|triple)\b"
    rf"|\b{_NUMWORD}(?:[\s-]+{_NUMWORD})*\s+{_UNIT}\b)"
)
# A statistic worth checking: a percentage, money, a big number, a ratio. "Three months" is a plan, not a statistic.
STATISTIC = _rx(
    r"(?:[£$€]\s?\d|\b\d[\d,.]*\s*(?:%|per ?cent\b|percent\b)|\b\d{3,}|\b\d[\d,.]*\s*(?:million|billion|thousand)\b"
    r"|\b\d+ (?:in|out of) \d+\b|\b(?:half|a third|a quarter|twice|double|triple) (?:of|as|the)\b"
    rf"|\b{_NUMWORD}(?:[\s-]+{_NUMWORD})*\s+(?:per ?cent|percent|pounds|dollars|euros)\b)"
)
# Plans, conditions and offers state intentions, not facts, so the fact-checker leaves them alone.
INTENTION = _rx(
    r"^(?:if|when|unless)\b|\b(?:we will|we'll|i will|i'll|i propose|we propose|let's|can we|could we|we would"
    r"|we'd|we can|i can|you can|we run|we offer|we stop)\b"
)
UNNAMED_RESEARCH = _rx(
    r"\b(?:studies|a study|research|experts?|scientists|surveys?|the data)\s+(?:show|shows|prove|proves|suggest|suggests|say|says|found|finds|tell us)\b|\bit is (?:a )?(?:proven|known) fact\b"
)
SOURCE = _rx(
    r"\b(?:according to|published|survey by|report (?:by|from)|data from|figures from|in (?:its|their) \d{4}|source[sd]? (?:is|are|from)|census)\b"
)
ABSOLUTE = _rx(
    r"\b(?:always|never|everyone|everybody|nobody|no one|every single|all of them|completely|totally|guaranteed|proven|impossible|100 ?%)\b"
)
SUPERLATIVE = _rx(
    r"\b(?:the (?:best|worst|most \w+|biggest|largest|only|fastest|cheapest|leading|first ever)|number one)\b"
)
CAUSAL = _rx(r"\b(?:leads? to|causes?|results? in|because of|drives?|means that)\b")
ACK = _rx(
    r"\b(?:i understand|i hear you|i hear that|that's fair|that is fair|fair point|fair enough|fair concern|fair question|makes sense|you're right|you are right|i get that|i get it|totally get|good question|great question|i appreciate|that's a real|that is a real|completely understand|understandable|i can see why|legitimate|valid concern|reasonable concern|of course|absolutely right|no doubt)\b"
)
NEXT_STEP = _rx(
    r"\b(?:next week|next steps?|pilot|trial|demo|book (?:a|in)|diary|calendar|set up (?:a|time)|shall we|can we (?:set|book|schedule|agree|meet|start|run)|could we (?:set|book|schedule|agree|meet|start|run)|would you be open|on (?:monday|tuesday|wednesday|thursday|friday)|by (?:monday|tuesday|wednesday|thursday|friday|the end of))\b"
)
REFRAME = _rx(
    r"\b(?:cost of|instead of|compared (?:with|to)|think of it|the real question|what if|over a year|per (?:month|week|day|year)|rather than|the risk of|doing nothing|in the long run|pays for itself|value|return on|saves?|saving|savings|the real cost)\b"
)
SALES_EVIDENCE = _rx(
    r"\b(?:for example|for instance|case study|customers?|clients?|results?|references?|measured|pilot|trial|data|survey|evidence|according to|teams like yours|clinics like yours|companies like yours)\b"
)
EXAMPLE = _rx(
    r"\b(?:for example|for instance|such as|take the case|take a|consider|look at|in practice|imagine|picture a)\b"
)
SIGNPOST = _rx(
    r"\b(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|finally|in summary|to sum up|to conclude|in short|my next point|two reasons|three reasons|on the other hand|the first|the second|the third|let me start|to start|overall|in conclusion)\b"
)
REASON = _rx(
    r"\b(?:because|since|which means|so that|therefore|as a result|that's why|that is why|this matters|leads to|the reason|which is why|this means|so the)\b"
)
REBUT_REF = _rx(
    r"\b(?:you said|you say|you claim(?:ed)?|you argued?|my opponent|the opposition|the proposition|the other side|their point|their case|they claim|they say|you mentioned|your point|your argument|you suggest(?:ed)?|you asked|your question|your concern|your worry|they never|they ignored|they haven't|they argued|they said|their \w+ (?:point|argument|claim|case))\b"
)
ASK = _rx(
    r"\b(?:i'm asking|i am asking|my ask|i'd like you to|i would like you to|can we agree|could we agree|will you|approve|approval|sign off|sign-off|a decision|decide|green light|commit to|i need you to|support (?:this|a|the))\b"
)
WHEN = _rx(
    r"\b(?:by (?:monday|tuesday|wednesday|thursday|friday|the end of|next|tomorrow|\d)|next (?:week|month|quarter)|this (?:week|month|quarter)|end of (?:the )?(?:week|month|quarter)|in (?:two|three|four|six|\d+) weeks|monday|tuesday|wednesday|thursday|friday)\b"
)
COMMON = _rx(
    r"\b(?:we both|we all|both of us|shared|you care about|your goal|your team|your budget|the same goal|same thing|agree that|we agree|in common|together|you've said|as you said|you mentioned|what matters to you|for you)\b"
)
PROPOSE = _rx(
    r"\b(?:i propose|i'm proposing|we should|i recommend|i'm recommending|the proposal is|my proposal|what i'm suggesting|i'm suggesting|i want us to|let's|the plan is)\b"
)
HEDGE = _rx(
    r"\b(?:maybe|perhaps|i guess|kind of|sort of|i suppose|probably|hopefully|might be|not sure|i think maybe)\b"
)
QUESTION_START = _rx(
    r"^(?:what|how|when|who|which|why|could you|can you|would you|is it|are you|do you|does|have you|tell me)\b"
)


def _hits(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def _pick(options: list[str], seed: str) -> str:
    return options[zlib.crc32(seed.encode()) % len(options)]


def _clause(text: str, pattern: re.Pattern[str], max_words: int = 16) -> str | None:
    """The sentence (trimmed to a clause) where ``pattern`` first matches."""
    for s in sentences(text):
        if pattern.search(s):
            parts = [p for p in re.split(r"(?<=,)\s+|[;:]\s+", s) if p.strip()]
            matching = [p for p in parts if pattern.search(p) and len(p.split()) >= 3]
            if matching:
                best = max(matching, key=lambda p: len(p.split())).rstrip(",")
                trimmed = LEADING.sub("", best)
                return shorten(trimmed if len(trimmed.split()) >= 3 else best, max_words)
            return shorten(s, max_words)
    return None


def key_point(text: str, max_words: int = 14) -> str:
    """The user's most substantive sentence, trimmed to a quotable clause."""
    ss = sentences(text)
    if not ss:
        return shorten(text, max_words)
    best = max(ss, key=lambda s: (len(content_words(s)) + 2 * _hits(REASON, s), -ss.index(s)))
    trimmed = _lead_trim(best)
    best = trimmed if len(trimmed.split()) >= 3 else best
    if len(best.split()) > max_words:
        # Too long to quote whole: take its most substantive clause instead.
        clauses = [
            c.strip(" ,")
            for c in re.split(r",\s+(?:and|but|so|which|because)?\s*|;\s+|:\s+", best)
            if len(c.split()) >= 4
        ]
        if clauses:
            best = max(clauses, key=lambda c: (len(content_words(c)), -clauses.index(c)))
    return shorten(best, max_words)


def _questions(text: str) -> list[str]:
    return [s for s in sentences(text) if s.endswith("?") or QUESTION_START.search(s)]


def _clarifying(text: str) -> list[str]:
    """Real questions about the other person's situation, not a next step phrased as a question."""
    return [q for q in sentences(text) if q.endswith("?") and not NEXT_STEP.search(q)]


def motion_core(topic: str) -> str:
    core = re.sub(
        r"^\s*(?:this house|th)\s+(?:would|believes that|believes|should|supports|regrets)\s+", "", topic, flags=re.I
    )
    return core.strip().rstrip(".")


# ─────────────────────────────── the opponent ───────────────────────────────

CONCERNS = {
    "cost": (
        "What does this cost, all in, including the time it takes people away from their actual work?",
        {
            "cost",
            "costs",
            "price",
            "spend",
            "money",
            "pounds",
            "hours",
            "salary",
            "budget",
            "cheap",
            "expensive",
            "fund",
        },
    ),
    "payback": (
        "When does this pay back? I need a date, not a feeling.",
        {"payback", "pay", "return", "roi", "saves", "save", "saving", "months", "weeks", "year"},
    ),
    "budget": (
        "This isn't in this year's budget. What do we stop doing to fund it?",
        {"budget", "fund", "stop", "reallocate", "cost", "spend", "trade"},
    ),
    "opportunity cost": (
        "Even if it works, is it the best use of the money? What else could the same budget do?",
        {"alternative", "instead", "priority", "priorities", "best", "compared", "option", "options"},
    ),
    "risk": (
        "What breaks first if this goes wrong, and how would we know?",
        {"risk", "risks", "break", "fail", "failure", "monitor", "rollback", "test", "measure", "safe"},
    ),
    "delivery": (
        "Who actually builds and runs this? My team is already at capacity.",
        {"team", "build", "capacity", "people", "who", "owner", "own", "resource", "hire"},
    ),
    "maintenance": (
        "Who maintains it in a year, once the launch energy has gone?",
        {"maintain", "maintenance", "own", "owner", "support", "long", "year", "upkeep"},
    ),
    "reversibility": (
        "If it doesn't work, how do we undo it, and what does undoing it cost?",
        {"undo", "reverse", "revert", "trial", "pilot", "back", "stop", "exit", "review"},
    ),
    "disruption": (
        "How do we keep the day job running while we change this?",
        {"disruption", "day", "cover", "rota", "service", "customers", "running", "continuity"},
    ),
    "workload": (
        "My people are stretched already. Where does the extra work go?",
        {"workload", "work", "stretched", "hours", "time", "capacity", "burnout", "load"},
    ),
    "timing": (
        "Why now? We have a busy quarter ahead.",
        {"now", "timing", "quarter", "when", "time", "wait", "deadline", "start"},
    ),
    "adoption": (
        "How do you get people to actually use it, rather than quietly work around it?",
        {"adoption", "use", "training", "people", "champions", "habit", "change", "feedback"},
    ),
}

OBJECTION_LINES = {
    "price": [
        "Honestly, it's more than we were expecting to spend. There are cheaper tools out there that do most of this.",
        "I'll be straight with you: the price is the problem. I can't justify that against what we pay now.",
    ],
    "timing": [
        "The timing is bad. We've got a lot on this quarter and nobody has the bandwidth for a new tool.",
        "Maybe later in the year. Right now really isn't the moment to change anything.",
    ],
    "incumbent": [
        "We already use something for this. It isn't perfect, but it works, and switching is a project in itself.",
        "We've got a system already and people know it. Why would we rip that out?",
    ],
    "authority": [
        "Look, even if I liked it, this isn't my call. I'd need to check with my boss before anything happens.",
        "I'd have to run it past my manager, and she's going to ask some hard questions.",
    ],
}
OBJECTION_LABEL = {
    "price": "the price",
    "timing": "the timing",
    "incumbent": "our current system",
    "authority": "getting my boss on board",
}
OBJECTION_KEYS = {
    "price": {
        "price",
        "cost",
        "costs",
        "expensive",
        "cheaper",
        "budget",
        "spend",
        "money",
        "afford",
        "pay",
        "fee",
        "value",
    },
    "timing": {"timing", "time", "quarter", "busy", "bandwidth", "later", "now", "moment", "wait", "year"},
    "incumbent": {
        "already",
        "system",
        "current",
        "switch",
        "switching",
        "existing",
        "spreadsheet",
        "migrate",
        "migration",
        "replace",
        "tool",
    },
    "authority": {"boss", "manager", "sign", "approve", "decision", "check", "together", "join", "involve", "case"},
}
CLARIFY_ANSWERS = {
    "price": "To answer your question, we pay a fixed monthly fee for what we have now, and this year's budget is already set.",
    "timing": "To answer your question, it's the end of the quarter and we're short-staffed until the new hires start.",
    "incumbent": "To answer your question, it's an older system plus a lot of spreadsheets, and people know where everything is.",
    "authority": "To answer your question, my manager signs off anything over a set amount, and she'll want to see it working first.",
}

# Each argument: (label, the line). The label is how the opponent refers back to it later.
POLICY_AGAINST = [
    (
        "the blunt-instrument problem",
        "This motion is a blunt instrument. It treats every case the same, when the problem is concentrated in a few.",
    ),
    (
        "displacement",
        "Rules like this rarely remove a behaviour. They move it somewhere less visible, where it is harder to manage.",
    ),
    (
        "the better alternative",
        "There is a better option: targeted rules, clear expectations and teaching judgement, which keeps the benefit without the cost.",
    ),
    (
        "the burden of proof",
        "The side asking for change carries the burden of proof, and that burden has not been met.",
    ),
]
BELIEF_AGAINST = [
    (
        "the typical case",
        "The case for this motion is built on the best examples, not the typical ones. Judge it on the ordinary case.",
    ),
    ("the hidden costs", "The costs are real, they are just paid by people who are not in this room."),
    (
        "the scale of the claim",
        "A claim this broad needs evidence across the board, not a handful of stories that happen to fit.",
    ),
    (
        "the burden of proof",
        "The side asking you to accept the motion carries the burden of proof, and that burden has not been met.",
    ),
]
ARGS_FOR = [
    (
        "the cost of waiting",
        "The status quo is not neutral. Every month we wait, the harm this motion targets keeps landing on the people least able to avoid it.",
    ),
    (
        "clear rules",
        "A clear rule is easier to follow and fairer to enforce than a thousand individual judgement calls.",
    ),
    (
        "the principle",
        "When a choice imposes costs on other people, it stops being purely private. That is the principle at stake.",
    ),
    ("doing it carefully", "And this can be done carefully: start small, measure it honestly, and adjust."),
]
# What the opponent says back when the user did take on one of its arguments.
COUNTERS = {
    "the blunt-instrument problem": "a clear rule aimed at the wrong target is still the wrong rule.",
    "displacement": "saying the behaviour has nowhere else to go is a hope, not a plan.",
    "the better alternative": "you dismissed the alternative without ever testing it.",
    "the burden of proof": "repeating a claim more firmly is not the same as proving it.",
    "the typical case": "your answer still leans on the best case rather than the usual one.",
    "the hidden costs": "naming a cost is not the same as showing it is worth paying.",
    "the scale of the claim": "one more example does not make a general rule.",
    "the cost of waiting": "the cost of acting badly is higher than the cost of waiting a little.",
    "clear rules": "simple is not the same as fair, and a simple rule still has to be right.",
    "the principle": "a principle that cannot say where it stops is not much of a principle.",
    "doing it carefully": "a careful version of a bad idea is still a bad idea.",
}
LEADING = re.compile(
    r"^(?:but|and|so|yet|also|well|now|first(?:ly)?|second(?:ly)?|third(?:ly)?|finally|in summary|to conclude|look)\b[,\s]*",
    re.I,
)


def _lead_trim(text: str) -> str:
    out = LEADING.sub("", text.strip())
    return out[:1].upper() + out[1:] if out else text


def _arguments(ctx: dict) -> tuple[list[tuple[str, str]], bool]:
    against = ctx.get("your_side", "opposition") != "proposition"
    belief = bool(re.match(r"^\s*this house (?:believes|regrets)", ctx.get("topic", ""), re.I))
    if not against:
        return ARGS_FOR, against
    return (BELIEF_AGAINST if belief else POLICY_AGAINST), against


def _engage_debate(last: str, seed: str) -> str:
    """Answer the kind of claim the user just made, in their own words."""
    if not last.strip():
        return "Nothing from you on that turn, so let me use the time."
    if (c := _clause(last, UNNAMED_RESEARCH)) and not SOURCE.search(last):
        return f'You leaned on "{c}". Which studies? An unnamed study cannot be cross-examined, and research on this is far more mixed than that.'
    if (c := _clause(last, NUMBER)) and not SOURCE.search(last):
        return f'You put a number on it: "{c}". A figure with no source is a guess in a suit. Where does it come from, and what is it measured against?'
    if c := _clause(last, ABSOLUTE):
        return f'You said "{c}". That is a very big word to carry. It only takes one counter-example to break it, and there are plenty.'
    if c := _clause(last, CAUSAL):
        return f'You claim "{c}". That is a causal chain, and every link needs holding up. Right now correlation is doing most of the work.'
    point = key_point(last)
    return _pick(
        [
            f'Your central point was "{point}". It sounds reasonable, but it skips the hard part: what it costs, and who pays.',
            f'You told us "{point}". I accept the concern. I do not accept that it gets you to this conclusion.',
            f'Let me take your strongest line head on: "{point}". It describes a problem. It does not show this is the answer.',
        ],
        seed,
    )


def _debate(ctx: dict, last: str, users: list[str], opps: list[str], seed: str) -> str:
    role, exchange = ctx["role"], ctx["exchange"]
    args, against = _arguments(ctx)
    core = motion_core(ctx.get("topic", "the motion"))
    stance = "this motion should fall" if against else "this motion should pass"
    stance_cap = stance[0].upper() + stance[1:]
    engage = _engage_debate(last, seed)
    # Which of our own arguments did they take on? Answer those, press the ones they dodged.
    made = [a for a in args if any(a[1] in o for o in opps)]
    engaged = [a for a in made if overlap(last, a[1]) >= 0.25]
    dodged = [a for a in made if a not in engaged]

    if role == "opening":
        body = " ".join(a[1] for a in args[:3])
        return f"{engage} Let me set out our case. {body} So when you weigh this, ask who carries the cost if it is wrong. We say {stance}."
    if role == "constructive":
        value = re.search(r"\bvalue (?:is|of|here is) (\w+)", last, re.I)
        theirs = f"You built your case on {value.group(1).lower()}. " if value else ""
        mine = (
            "My value is liberty, and my criterion is whether a policy respects people's capacity to choose for themselves."
            if against
            else "My value is fairness, and my criterion is whether a policy protects the people who bear the costs."
        )
        body = " ".join(a[1] for a in args[:2])
        return f"{theirs}{engage} {mine} Judged that way: {body} That is why {stance}."
    if role == "answer":
        qs = [q for q in _questions(last) if q.endswith("?")] or _questions(last)
        if qs:
            q = shorten(qs[-1], 18)
            lead = _pick(
                ["Yes, with a condition.", "No, and here is why.", "Partly, and the part that matters is this."], seed
            )
            reason = args[exchange % len(args)][1]
            back = (
                f"if the answer is to {core}, why must it apply to everyone, including those who cause no harm?"
                if against
                else "what would you do instead, and how would you know it was working?"
            )
            return f'You asked "{q}?" {lead} {reason} Now let me ask you one back: {back}'
        return f"That was a speech, not a question, so I will answer the point instead. {engage} Ask me something specific and I will answer it."
    if role == "rebuttal":
        generic = engage.startswith(("Your central point", "You told us", "Let me take your strongest"))
        parts = [] if engaged and generic else [engage]
        if engaged:
            label = engaged[0][0]
            options = sentences(last) or [last]
            clause = max(options, key=lambda x: (not REBUT_REF.search(x), overlap(x, engaged[0][1])))
            parts.append(f'You did take on {label}: "{shorten(_lead_trim(clause), 14)}". But {COUNTERS[label]}')
        elif users[:-1]:
            parts.append(f'Earlier you argued "{key_point(users[0], 12)}". That still does not answer {args[0][0]}.')
        press = (dodged or [a for a in args if a not in engaged])[0]
        parts.append(f"And {press[0]} went unanswered entirely. {press[1]}")
        parts.append(f"Which leaves you asserting, and us explaining. {stance_cap}.")
        return " ".join(parts)
    if role == "closing":
        theirs = key_point(next((u for u in users if u.strip()), last), 12)
        won = (dodged or args)[0][0]
        closing_line = (
            f'You closed on "{key_point(last, 12)}", but a closing has to weigh the clashes, not restate a slogan. '
            if last.strip()
            else ""
        )
        return (
            f"{closing_line}Let me weigh this debate. There were two clashes that mattered. "
            f'The first was your claim that "{theirs}". You asserted it, but you never showed the mechanism. '
            f"The second was {won}, and that one went to us without a real fight. "
            f"When one side explains and the other only repeats, the room should know what to do. {stance_cap}."
        )
    # rapid fire: short, sharp, and always answering the last thing said
    point = args[(exchange - 1) % len(args)][1]
    short = engage.split(". ")[0].rstrip(".") + "."
    return f"{short} {point}"


def concern_in(opp_text: str | None) -> str | None:
    """Which concern an opponent turn raised, if it was one of ours."""
    return next((c for c, (q, _) in CONCERNS.items() if opp_text and q in opp_text), None)


def concern_answered(user_text: str, concern: str) -> bool:
    return bool(set(words(user_text)) & CONCERNS[concern][1])


def objection_in(opp_text: str | None) -> str | None:
    """Which objection an opponent turn raised, if it was one of ours."""
    return next((o for o, lines in OBJECTION_LINES.items() if opp_text and any(x in opp_text for x in lines)), None)


def objection_handled(user_text: str, objection: str) -> bool:
    return bool(set(words(user_text)) & OBJECTION_KEYS[objection])


def _meeting(ctx: dict, last: str, opps: list[str], seed: str) -> str:
    role = ctx["role"]
    title = ctx.get("persona_role", "the stakeholder").lower()
    now = ctx.get("concern_now", "cost")
    question = CONCERNS.get(now, CONCERNS["cost"])[0]
    prev_concern = concern_in(opps[-1] if opps else None)
    numbers = _clause(last, STATISTIC, 12) or _clause(last, NUMBER, 12)
    point = key_point(last, 12)
    ack = bool(ACK.search(last))

    if not last.strip():
        lead = "You ran out of time there, and in a real meeting that silence would be noticed."
    elif role == "probe":
        credit = (
            f'I appreciate that you came with a number: "{numbers}".'
            if numbers
            else f'I can see the appeal of "{point}".'
        )
        return (
            f"Thanks, that's clear enough to discuss. {credit} But as {title}, I have to push on something. {question}"
        )
    elif prev_concern:
        answered = concern_answered(last, prev_concern)
        if role == "decide" and not answered:
            lead = f"You never quite answered my point on {prev_concern}, and I will hold you to that."
        elif answered and ack:
            lead = (
                f'That\'s a fair answer on {prev_concern}: "{numbers or key_point(last, 12)}" is what I needed to hear.'
            )
        elif answered:
            lead = f'That partly answers my point on {prev_concern}. I\'d still want to see "{numbers or point}" written down, with the working.'
        else:
            lead = f'With respect, that didn\'t answer my question on {prev_concern}. You talked about "{point}", but what I asked about was {prev_concern}.'
    else:
        lead = f'You said "{point}". Let me take that at face value for now.'

    if role == "decide":
        ask = _clause(last, ASK, 16)
        when = _clause(last, WHEN, 16)
        if ask:
            timing = " and you've put a date on it" if when else ", though I'd want a date on it"
            return (
                f'{lead} Still, that\'s a clear ask: "{ask}"{timing}. I can support a limited version, on one condition: '
                "we agree up front what success looks like, and we review it together before anything is extended."
            )
        return (
            f"{lead} I'm still not sure what you want from me. Is it budget, a decision or just my support? "
            "Come back with a specific ask and a date, and I'll give you a straight answer."
        )
    return f"{lead} Let me push on something else. {question}"


def _sales(ctx: dict, last: str, opps: list[str], seed: str) -> str:
    role = ctx["role"]
    prev = objection_in(opps[-1] if opps else None)
    now = ctx.get("objection_now", "").split(":")[0].strip()
    qs = _clarifying(last)
    ack = bool(ACK.search(last))
    handled_signals = bool(SALES_EVIDENCE.search(last) or REFRAME.search(last) or NUMBER.search(last) or qs)
    step = _clause(last, NEXT_STEP, 16)

    parts: list[str] = []
    if not last.strip():
        parts.append("Sorry, I lost you there. Are you still with me?")
    elif prev is None and not opps:
        if qs:
            parts.append(
                f'You asked "{shorten(qs[0], 14)}" Honestly, it\'s mostly manual at the moment, and it takes more time than anyone would like.'
            )
        else:
            parts.append(f'Okay, thanks. So "{key_point(last, 12)}".')
        if role != "decide":
            parts.append("But I should be upfront with you before we go any further.")
    elif prev is None:
        parts.append("" if role == "decide" else f'Okay, "{key_point(last, 12)}".')
    elif role == "decide" and step:
        if not (ack or objection_handled(last, prev)):
            parts.append(f"We still haven't really settled {OBJECTION_LABEL[prev]}, but fine.")
    else:
        if qs:
            parts.append(CLARIFY_ANSWERS[prev])
        on_topic = objection_handled(last, prev)
        if ack and (handled_signals or on_topic):
            echo = _clause(last, REFRAME, 12) or _clause(last, SALES_EVIDENCE, 12) or key_point(last, 12)
            parts.append(f'Okay, that\'s fair. "{echo}" makes me look at it a bit differently.')
        elif ack:
            parts.append(f'I appreciate you hearing me out, but "{key_point(last, 12)}" doesn\'t solve it for me.')
        elif on_topic and handled_signals:
            parts.append(f'Hm. You\'re moving quickly past it, but "{key_point(last, 12)}" is at least an answer.')
        else:
            parts.append(
                f"You've skipped past what I said about {OBJECTION_LABEL[prev]}. \"{key_point(last, 12)}\" is fine, but that's still the thing stopping me."
            )

    if role == "decide":
        if step:
            parts.append(
                f'Alright. "{step}" works for me. Send me a short summary I can forward, and put it in the diary.'
            )
        else:
            parts.append(
                f"You said \"{key_point(last, 12)}\", but I'm not sure what you're asking me to do next. Send me some information and I'll have a look when I can."
            )
    elif now in OBJECTION_LINES:
        parts.append(_pick(OBJECTION_LINES[now], seed + now))
    else:
        parts.append(
            "Alright, you've answered most of what I had. Say I was interested: what would the next step actually look like?"
        )
    return " ".join(p for p in parts if p)


def opponent_reply(system: str, messages: list[dict]) -> str:
    t = tags(system)
    phase = re.search(r'<phase id="([^"]*)" name="[^"]*" role="(\w+)" exchange="(\d+)" of="(\d+)"', system)
    persona = re.search(r'<persona name="([^"]*)" role="([^"]*)">', system)
    ctx = {
        "mode": t.get("mode", "debate"),
        "topic": t.get("topic", ""),
        "your_side": t.get("your_side"),
        "context": t.get("context", ""),
        "concern_now": t.get("concern_now"),
        "objection_now": t.get("objection_now", ""),
        "role": phase.group(2) if phase else "rebuttal",
        "exchange": int(phase.group(3)) if phase else 1,
        "persona_role": persona.group(2) if persona else "",
    }
    users = [_strip_notes(m["content"]) for m in messages if m["role"] == "user"]
    opps = [m["content"] for m in messages if m["role"] == "assistant"]
    last = users[-1] if users else ""
    seed = last + ctx["role"] + str(ctx["exchange"])
    if ctx["mode"] == "meeting":
        return _meeting(ctx, last, opps, seed)
    if ctx["mode"] == "sales":
        return _sales(ctx, last, opps, seed)
    return _debate(ctx, last, users, opps, seed)


def _strip_notes(text: str) -> str:
    text = text.replace("(The user ran out of time without saying anything.)", "")
    return text.replace("(Time ran out on this turn.)", "").strip()


# ─────────────────────────────── the fact-checker ───────────────────────────────


REPORTED = _rx(
    r"^(?:but |so |and )?(?:you|they|my opponent|the other side|the opposition|the proposition)\s+"
    r"(?:said|say|says|claim|claims|claimed|argued|argue|argues|suggest|suggested|think|thinks|called|call)\b"
)


def fact_check(text: str) -> dict:
    claims = []
    for s in sentences(text):
        if s.endswith("?") or REPORTED.match(s):
            continue  # questions, and claims the user attributes to the other side, are not theirs to check
        claim = shorten(s, 28)
        sourced = bool(SOURCE.search(s))
        intention = bool(INTENTION.search(s))
        if UNNAMED_RESEARCH.search(s) and not sourced:
            claims.append(
                {
                    "claim": claim,
                    "verdict": "unsupported",
                    "reason": "It appeals to research without naming it, so it cannot be checked or challenged.",
                    "evidence_needed": "A named study or report, what it measured, and when.",
                }
            )
        elif STATISTIC.search(s) and not sourced and not intention:
            figure = STATISTIC.search(s).group(0).strip()
            if "%" in figure or "cent" in figure.lower():
                need = "The survey or dataset behind the percentage, with its sample size and year."
            elif re.search(r"[£$€]|pounds|dollars|euros", figure, re.I):
                need = "A costed estimate or the published figure, with what it includes."
            else:
                need = "Where the figure comes from and what it is measured against."
            claims.append(
                {
                    "claim": claim,
                    "verdict": "unsupported",
                    "reason": f"A specific figure ({figure}) is stated with no source.",
                    "evidence_needed": need,
                }
            )
        elif ABSOLUTE.search(s) and not intention:
            word = ABSOLUTE.search(s).group(0)
            claims.append(
                {
                    "claim": claim,
                    "verdict": "doubtful",
                    "reason": f'An absolute ("{word}") that one counter-example would break.',
                    "evidence_needed": "Evidence that it holds across cases, or a softer claim such as 'most' backed by data.",
                }
            )
        elif SUPERLATIVE.search(s) and not intention:
            claims.append(
                {
                    "claim": claim,
                    "verdict": "doubtful",
                    "reason": "A superlative with nothing to compare it against.",
                    "evidence_needed": "A like-for-like comparison with the alternatives.",
                }
            )
        elif sourced and STATISTIC.search(s):
            claims.append(
                {
                    "claim": claim,
                    "verdict": "supported",
                    "reason": "The figure is attributed to a source; the source itself was not verified.",
                    "evidence_needed": "A link to the source, to have it ready if challenged.",
                }
            )
    return {"claims": claims}


# ─────────────────────────────── the judge ───────────────────────────────


def _per_turn(users: list[str], opps_before: list[str | None]) -> list[dict]:
    feats = []
    for text, opp in zip(users, opps_before, strict=True):
        ws = words(text)
        n = len(ws)
        ss = sentences(text)
        feats.append(
            {
                "text": text,
                "words": n,
                "sentences": ss,
                "reasons": _hits(REASON, text),
                "examples": _hits(EXAMPLE, text),
                "numbers": _hits(NUMBER, text),
                "sourced": _hits(SOURCE, text),
                "signposts": _hits(SIGNPOST, text),
                "rebut_refs": _hits(REBUT_REF, text),
                "overlap": overlap(text, opp) if opp else None,
                "ack": _hits(ACK, " ".join(ss[:2])) if ss else 0,
                "ack_any": _hits(ACK, text),
                "questions": len([q for q in ss if q.endswith("?")]),
                "reframes": _hits(REFRAME, text),
                "sales_evidence": _hits(SALES_EVIDENCE, text),
                "next_steps": _hits(NEXT_STEP, text),
                "asks": _hits(ASK, text),
                "whens": _hits(WHEN, text),
                "common": _hits(COMMON, text),
                "proposes": _hits(PROPOSE, text),
                "hedges": _hits(HEDGE, text),
                "avg_sentence": (n / len(ss)) if ss else 0,
                "has_opp": opp is not None,
                "clarifying": len(_clarifying(text)),
                "concern": (c := concern_in(opp)),
                "concern_answered": bool(c and concern_answered(text, c)),
                "objection": (o := objection_in(opp)),
                "objection_handled": bool(o and objection_handled(text, o)),
            }
        )
    return feats


def _clamp(x: float) -> int:
    return max(1, min(10, round(x)))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _peak(xs: list[float]) -> float:
    """Half the best turn, half the average: one strong turn counts, but so does consistency."""
    return (max(xs) + _mean(xs)) / 2 if xs else 0.0


def _best_sentence(
    feats: list[dict], pattern: re.Pattern[str] | None, *, want_low: bool = False, only: list[int] | None = None
) -> tuple[int, str]:
    """The sentence that best evidences a score: the strongest match, or for a low score, the weakest."""
    candidates = []
    for i, f in enumerate(feats):
        if only is not None and i not in only:
            continue
        for j, s in enumerate(f["sentences"]):
            hits = _hits(pattern, s) if pattern else len(content_words(s))
            candidates.append((hits, len(s.split()), -i, -j, i, s))
    if not candidates:
        nonempty = [(i, f["text"]) for i, f in enumerate(feats) if f["text"].strip()]
        return nonempty[0] if nonempty else (0, "")
    if want_low:
        # The earliest, most substantive sentence that shows the weakness.
        pick = min(candidates, key=lambda c: (c[0], -c[2], -c[1], -c[3]))
    else:
        pick = max(candidates, key=lambda c: (c[0], c[1], c[2], c[3]))
    return pick[4], pick[5]


def _first_sentence(f: dict) -> str:
    return f["sentences"][0] if f["sentences"] else f["text"].strip()


def _score(criterion: str, score: int, explanation: str, turn_i: int, quote: str) -> dict:
    return {"criterion": criterion, "score": score, "explanation": explanation, "quote": quote, "turn": turn_i + 1}


def _band(score: int, low: str, mid: str, high: str) -> str:
    return low if score <= 4 else mid if score <= 6 else high


def _delivery_score(d: dict, feats: list[dict]) -> tuple[int, str]:
    spoken = d.get("spoken_turns", 0) > 0
    s = 9.0 if spoken else 7.5
    notes = []
    fp100 = d.get("fillers_per_100", 0.0) or 0.0
    s -= min(5.0, fp100 * 0.8)
    if fp100 >= 2:
        notes.append(f"{fp100:g} filler words per 100 words")
    wpm = d.get("avg_wpm")
    if wpm is not None:
        if wpm < 120:
            s -= min(3.0, (120 - wpm) / 15)
            notes.append(f"a slow average pace of {wpm:g} words a minute")
        elif wpm > 175:
            s -= min(3.0, (wpm - 175) / 15)
            notes.append(f"a rushed average pace of {wpm:g} words a minute")
    pause = d.get("longest_pause_s")
    if pause is not None and pause > 3:
        s -= 1
        notes.append(f"a longest pause of {pause:g} seconds")
    over = d.get("over_time_turns", 0)
    if over:
        s -= 1.5 * over
        notes.append(f"{over} turn{'s' * (over != 1)} over time")
    ratio = d.get("avg_talk_ratio")
    if spoken and ratio is not None and ratio < 0.35:
        s -= 1
        notes.append("much of the available time left unused")
    if not spoken and _mean([f["words"] for f in feats]) < 20:
        s -= 1.5
        notes.append("very short turns")
    score = _clamp(s)
    if not spoken:
        lead = "All turns were typed, so pace and pauses could not be measured; this scores concision and filler words."
    else:
        lead = f"Across {d['spoken_turns']} spoken turn{'s' * (d['spoken_turns'] != 1)}" + (
            f", you averaged {wpm:g} words a minute." if wpm else "."
        )
    if notes:
        detail = " The judge marked down " + ", ".join(notes) + "."
    else:
        detail = " Clean delivery: few fillers and the time well used."
    return score, lead + detail


def judge(message: str) -> dict:
    t = tags(message)
    mode = t.get("mode", "debate")
    turns = parse_transcript(message)
    delivery = json.loads(t.get("delivery") or "{}")
    flags = json.loads(t.get("flags") or "[]")

    users, opps_before, last_opp = [], [], None
    for turn in turns:
        if turn["speaker"] == "user":
            text = "" if turn["text"].startswith("(no response") else turn["text"]
            users.append(text)
            opps_before.append(last_opp)
        else:
            last_opp = turn["text"]
    feats = _per_turn(users, opps_before)
    replies = [i for i, f in enumerate(feats) if f["has_opp"]]
    scores: list[dict] = []

    if mode == "debate":
        sig = [min(1, f["reasons"] / 2) * 0.65 + min(1, f["words"] / 70) * 0.35 for f in feats]
        s = _clamp(2 + 8 * _mean(sig))
        i, q = _best_sentence(feats, REASON, want_low=s <= 4)
        total = sum(f["reasons"] for f in feats)
        scores.append(
            _score(
                "argument",
                s,
                _band(
                    s,
                    f"Claims mostly arrive without a reason attached; only {total} reasoning link{'s' * (total != 1)} ('because', 'which means') across your turns. Say why each point is true and why it matters.",
                    f"Your case has a recognisable shape, with {total} explicit reasoning links, but some claims are asserted rather than argued. Push each one through to its impact.",
                    f"Claims come with reasons and consequences, {total} explicit links in all. The case holds together as an argument, not a list of opinions.",
                ),
                i,
                q,
            )
        )

        flagged = len([f for f in flags if f["verdict"] != "supported"])
        sig = [min(1, (f["examples"] + f["sourced"] * 2 + min(f["numbers"], 2) * 0.5) / 2) for f in feats]
        s = _clamp(2.5 + 7.5 * _peak(sig) - 1.5 * flagged)
        flagged_claims = [f for f in flags if f["verdict"] != "supported"]
        if flagged_claims:
            fc = flagged_claims[0]
            i, q = fc["turn"] - 1, fc["claim"]
        else:
            i, q = _best_sentence(
                feats, re.compile(EXAMPLE.pattern + "|" + NUMBER.pattern + "|" + SOURCE.pattern, re.I), want_low=s <= 4
            )
        flag_note = (
            f" The fact-checker flagged {flagged} claim{'s' * (flagged != 1)} as unsupported or doubtful."
            if flagged
            else ""
        )
        scores.append(
            _score(
                "evidence",
                s,
                _band(
                    s,
                    f"Little of what you said could be checked: few examples, and figures without sources.{flag_note} Name where a number comes from, or use a concrete example instead.",
                    f"There is some support here, but it is uneven.{flag_note} Tie your best example to your biggest claim.",
                    f"Your support is specific and checkable, with examples and attributed figures.{flag_note}",
                ),
                i,
                q,
            )
        )

        if replies:
            sig = [min(1, (feats[i]["overlap"] or 0) * 1.6 + feats[i]["rebut_refs"] * 0.35) for i in replies]
            s = _clamp(1.5 + 8.5 * _mean(sig))
            i, q = _best_sentence(
                feats,
                REBUT_REF if any(feats[r]["rebut_refs"] for r in replies) else None,
                want_low=s <= 4,
                only=replies,
            )
            if s <= 4:
                i, q = replies[0], _first_sentence(feats[replies[0]])
            scores.append(
                _score(
                    "rebuttal",
                    s,
                    _band(
                        s,
                        "You mostly ignored what the opponent had just said and carried on with your own case. Name their point, then say why it fails.",
                        "You engaged some of the opponent's points, but the strongest ones went unanswered. Answer their best point first.",
                        "You took the opponent's actual arguments head on, in their terms, and explained why they fail.",
                    ),
                    i,
                    q,
                )
            )
        else:
            i, q = 0, _first_sentence(feats[0]) if feats else ""
            scores.append(
                _score(
                    "rebuttal",
                    5,
                    "There was no opponent speech to answer before your only turn, so rebuttal could not really be tested.",
                    i,
                    q,
                )
            )

        sig = [min(1, f["signposts"] / 2) * 0.7 + (0.3 if 8 <= f["avg_sentence"] <= 24 else 0.1) for f in feats]
        s = _clamp(2 + 8 * _mean(sig))
        i, q = _best_sentence(feats, SIGNPOST, want_low=s <= 4)
        n_sign = sum(f["signposts"] for f in feats)
        scores.append(
            _score(
                "structure",
                s,
                _band(
                    s,
                    f"Hard to follow: {n_sign} signpost{'s' * (n_sign != 1)} in total, so the listener has to work out where one point ends and the next begins. Number your points.",
                    f"There is some order, with {n_sign} signposts, but not every speech has a clear line through it. Tell the room your points before you make them.",
                    f"Well signposted ({n_sign} markers such as 'first' and 'finally'); each speech has a clear line through it.",
                ),
                i,
                q,
            )
        )

    elif mode == "meeting":
        persona = re.search(r'<persona name="[^"]*" role="([^"]*)">', message)
        title = persona.group(1).lower() if persona else "stakeholder"
        sig = [
            min(1, f["proposes"] * 0.4 + 0.4) * (1 if f["avg_sentence"] <= 22 else 0.6) - min(0.3, f["hedges"] * 0.1)
            for f in feats
        ]
        s = _clamp(2 + 8 * _mean(sig))
        longest = max(
            ((i, sent) for i, f in enumerate(feats) for sent in f["sentences"]),
            key=lambda x: len(x[1].split()),
            default=(0, ""),
        )
        i, q = longest if s <= 4 else _best_sentence(feats, PROPOSE)
        avg = round(_mean([f["avg_sentence"] for f in feats if f["sentences"]]), 1)
        scores.append(
            _score(
                "clarity",
                s,
                _band(
                    s,
                    f"The proposal is hard to pin down: sentences average {avg:g} words and hedges ('maybe', 'sort of') soften every point. Say what you propose in one plain sentence.",
                    f"The proposal is understandable, but it takes a while to surface (sentences average {avg:g} words). Lead with the outcome.",
                    f"Clear and direct: it was obvious what you proposed and why, in sentences that average {avg:g} words.",
                ),
                i,
                q,
            )
        )

        # Figures don't belong in every turn, so this counts them across the session.
        total = sum(min(f["numbers"], 3) for f in feats)
        sig = min(1, total / max(1, 0.8 * len(feats)))
        s = _clamp(2 + 8 * sig - 0.8 * len([f for f in flags if f["verdict"] != "supported"]))
        i, q = _best_sentence(feats, NUMBER, want_low=s <= 4)
        n_num = sum(f["numbers"] for f in feats)
        scores.append(
            _score(
                "data",
                s,
                _band(
                    s,
                    f"Only {n_num} figures across {len(feats)} turns, and few where the stakeholder pushed. A {title} will not move on enthusiasm: bring the cost, the time and the expected result.",
                    f"Some figures ({n_num}), but not where the stakeholder pushed hardest. Have the number ready for the concern you expect.",
                    f"The case is concrete: {n_num} figures covering what it costs and what it returns. Make sure each one has its working.",
                ),
                i,
                q,
            )
        )

        pushed = [i for i in replies if feats[i]["concern"]] or replies
        if pushed:
            sig = [
                min(
                    1,
                    0.5 * feats[i]["concern_answered"]
                    + 0.3 * min(1, feats[i]["ack"])
                    + 0.2 * min(1, (feats[i]["overlap"] or 0) * 2)
                    + 0.1 * min(1, feats[i]["numbers"]),
                )
                for i in pushed
            ]
            s = _clamp(1.5 + 8.5 * _mean(sig))
            dodged = [i for i in pushed if not feats[i]["concern_answered"]]
            if s <= 6 and dodged:
                i, q = dodged[0], _first_sentence(feats[dodged[0]])
            else:
                i, q = _best_sentence(feats, ACK, only=pushed)
            scores.append(
                _score(
                    "pushback",
                    s,
                    _band(
                        s,
                        "When the stakeholder raised a concern, you mostly restated the pitch instead of answering it. Repeat their concern back, then answer that concern.",
                        "You answered some concerns directly and talked past others. The concern you skip is the one they remember.",
                        "You took each concern seriously and answered the question actually asked.",
                    ),
                    i,
                    q,
                )
            )
        else:
            scores.append(
                _score(
                    "pushback",
                    5,
                    "No pushback came before your only turn, so this could not be tested.",
                    0,
                    _first_sentence(feats[0]) if feats else "",
                )
            )

        sig = [min(1, f["common"] * 0.5) for f in feats]
        s = _clamp(2 + 8 * max(sig, default=0) * 0.6 + 8 * _mean(sig) * 0.4)
        i, q = _best_sentence(feats, COMMON, want_low=s <= 4)
        scores.append(
            _score(
                "common_ground",
                s,
                _band(
                    s,
                    "You argued from your own goals and rarely connected the proposal to what this stakeholder cares about. Find the outcome you both want and start there.",
                    "You touched on shared goals, but only in passing. Make the common ground the frame, not a footnote.",
                    "You framed the proposal in terms the stakeholder already cares about, which made agreeing easy.",
                ),
                i,
                q,
            )
        )

        final = feats[-1] if feats else None
        ask_sig = 0.0
        if final:
            ask_sig = (
                min(1, final["asks"] * 0.5 + final["whens"] * 0.35) * 0.75
                + min(1, max(f["asks"] for f in feats) * 0.5) * 0.25
            )
        s = _clamp(1.5 + 8.5 * ask_sig)
        if s <= 4 and final:
            i, q = len(feats) - 1, (final["sentences"][-1] if final["sentences"] else final["text"].strip())
        else:
            i, q = _best_sentence(feats, re.compile(ASK.pattern + "|" + WHEN.pattern, re.I))
        scores.append(
            _score(
                "ask",
                s,
                _band(
                    s,
                    "The meeting ended without a specific request. Say exactly what you want decided, by whom and by when.",
                    "There is an ask in there, but it is soft or has no date. Make it a yes-or-no question with a deadline.",
                    "A clear, specific ask with a time attached. The stakeholder knew exactly what saying yes would mean.",
                ),
                i,
                q,
            )
        )

    else:  # sales
        objected = [i for i in replies if feats[i]["objection"]] or replies
        if objected:
            sig = [1.0 if feats[i]["ack"] else 0.35 if feats[i]["ack_any"] else 0.0 for i in objected]
            s = _clamp(1 + 9 * _mean(sig))
            if s <= 6:
                miss = next((i for i in objected if not feats[i]["ack"]), objected[0])
                i, q = miss, _first_sentence(feats[miss])
            else:
                i, q = _best_sentence(feats, ACK, only=objected)
            missed = len([i for i in objected if not feats[i]["ack"]])
            replies = objected
            scores.append(
                _score(
                    "acknowledge",
                    s,
                    _band(
                        s,
                        f"You went straight to answering, or past the objection entirely, in {missed} of {len(replies)} replies. The buyer has to feel heard before they will listen.",
                        f"You acknowledged some objections but not others ({missed} of {len(replies)} replies skipped it). Make it a habit: name the concern before you answer it.",
                        f"You recognised {len(objected) - missed} of {len(objected)} objections before answering them, so the buyer felt heard rather than handled.",
                    ),
                    i,
                    q,
                )
            )
        else:
            scores.append(
                _score(
                    "acknowledge",
                    5,
                    "The buyer raised no objection before your only turn, so this could not be tested.",
                    0,
                    _first_sentence(feats[0]) if feats else "",
                )
            )

        sig = [min(1, f["clarifying"]) for i, f in enumerate(feats) if i in objected] or [0.0]
        s = _clamp(1.5 + 8.5 * _mean(sig))
        if s <= 4:
            i, q = objected[0] if objected else 0, _first_sentence(feats[objected[0] if objected else 0])
        else:
            asked = [(i, x) for i, f in enumerate(feats) for x in _clarifying(f["text"]) if i in objected]
            i, q = asked[0] if asked else _best_sentence(feats, None)
        scores.append(
            _score(
                "clarify",
                s,
                _band(
                    s,
                    "You rarely asked what was really behind an objection, so you answered the surface version. One good question saves a paragraph of pitch.",
                    "You asked some clarifying questions; use them every time an objection is vague.",
                    "You asked good questions to find out what was really behind each objection before answering it.",
                ),
                i,
                q,
            )
        )

        sig = [min(1, f["reframes"] / 2) for f in feats]
        s = _clamp(2 + 8 * _mean(sig))
        i, q = _best_sentence(feats, REFRAME, want_low=s <= 4, only=objected if s <= 4 else None)
        scores.append(
            _score(
                "reframe",
                s,
                _band(
                    s,
                    f"You reframed in {sum(1 for i in objected if feats[i]['reframes'])} of {len(objected)} replies to an objection; otherwise you argued on the buyer's terms. Shift the frame: the cost of doing nothing, value over price, the risk of the status quo.",
                    "You reframed some objections, but defended on price or timing elsewhere. Lead with the frame you want.",
                    "You moved the conversation onto better ground, from price to value and from risk to the cost of standing still.",
                ),
                i,
                q,
            )
        )

        sig = [min(1, (f["sales_evidence"] + min(f["numbers"], 2)) / 2) for f in feats]
        s = _clamp(2 + 8 * _peak(sig) - 0.8 * len([f for f in flags if f["verdict"] != "supported"]))
        i, q = _best_sentence(
            feats,
            re.compile(SALES_EVIDENCE.pattern + "|" + NUMBER.pattern, re.I),
            want_low=s <= 4,
            only=objected if s <= 4 else None,
        )
        scores.append(
            _score(
                "evidence",
                s,
                _band(
                    s,
                    f"Claims mostly arrived without proof the buyer could check ({sum(1 for f in feats if f['sales_evidence'] or f['numbers'])} of {len(feats)} turns offered any). Offer a result, a reference customer or a trial instead of an adjective.",
                    "Some proof, but generic. Make it specific to a buyer like this one.",
                    "You backed claims with proof the buyer could check, such as results, references or a trial.",
                ),
                i,
                q,
            )
        )

        final = feats[-1] if feats else None
        sig_step = min(1, (final["next_steps"] if final else 0) * 0.6 + (final["whens"] if final else 0) * 0.3)
        s = _clamp(
            1.5 + 8.5 * (0.75 * sig_step + 0.25 * min(1, max((f["next_steps"] for f in feats), default=0) * 0.5))
        )
        if s <= 4 and final:
            i, q = len(feats) - 1, (final["sentences"][-1] if final["sentences"] else final["text"].strip())
        else:
            i, q = _best_sentence(feats, NEXT_STEP)
        scores.append(
            _score(
                "next_step",
                s,
                _band(
                    s,
                    "The conversation ended without a concrete next step, which usually means it ends there. Propose something small, with a date.",
                    "You suggested a next step but left it open. Put a day and a time on it before you hang up.",
                    "You closed for a concrete next step with a time on it.",
                ),
                i,
                q,
            )
        )

    if mode == "debate":
        s, explanation = _delivery_score(delivery, feats)
        fillers_pattern = re.compile(r"\b(?:um+|uh+|erm|basically|you know|sort of|like)\b", re.I)
        i, q = (
            _best_sentence(feats, fillers_pattern, want_low=False)
            if delivery.get("filler_total")
            else _best_sentence(feats, None)
        )
        scores.append(_score("delivery", s, explanation, i, q))

    overall = round(_mean([x["score"] for x in scores]) * 10)
    decisions = {
        "debate": ("Won on points", "Split decision", "Lost on points"),
        "meeting": ("Proposal approved", "Approved with conditions", "Not yet convinced"),
        "sales": ("Deal moving", "Interested, not committed", "Stalled"),
    }[mode]
    decision = decisions[0] if overall >= 70 else decisions[1] if overall >= 55 else decisions[2]
    best = max(scores, key=lambda x: x["score"])
    worst = min(scores, key=lambda x: x["score"])
    names = {c.id: c.name.lower() for c in rb.RUBRICS[mode]}
    summary = (
        f"Your strongest area was {names[best['criterion']]} ({best['score']}/10) and your weakest was "
        f"{names[worst['criterion']]} ({worst['score']}/10). Fix the second and the first will count for more."
    )
    return {"scores": scores, "summary": summary, "decision": decision}


# ─────────────────────────────── the coach ───────────────────────────────

ADVICE = {
    "argument": (
        "Attach a reason to every claim",
        "Your claims arrive on their own. A judge cannot reward what you do not explain.",
        "For each point, say it in three parts out loud: claim, because, which means.",
    ),
    "evidence": (
        "Back your biggest claim with something checkable",
        "Your weakest evidence sat under your most important point.",
        "Before each session, write down one example and one sourced figure for your main argument.",
    ),
    "rebuttal": (
        "Answer their best point first",
        "You spent your time on your own case while the opponent's strongest point went unanswered.",
        "Start every rebuttal with: 'They said X. That fails because Y.'",
    ),
    "structure": (
        "Signpost your speech",
        "Without markers, the listener has to work out where your points start and stop.",
        "Open each speech with 'I have two points' and number them as you go.",
    ),
    "delivery": (
        "Slow down and cut the fillers",
        "Filler words and pace made strong content sound less sure than it was.",
        "Record one turn, count your fillers, then repeat it with a one-second pause where each filler was.",
    ),
    "clarity": (
        "Lead with the outcome in one sentence",
        "The proposal took too long to surface, so the stakeholder was judging it before they understood it.",
        "Write your pitch's first sentence as 'I propose X so that Y', and say it before anything else.",
    ),
    "data": (
        "Bring the number they will ask for",
        "Stakeholders move on figures, and you mostly offered enthusiasm.",
        "List the three numbers this stakeholder will want (cost, time, result) and prepare each with its working.",
    ),
    "pushback": (
        "Repeat the concern, then answer it",
        "When pushed, you restated the pitch instead of answering the question asked.",
        "Practise: 'So your worry is X. Here is how we handle X.'",
    ),
    "common_ground": (
        "Start from what they already want",
        "You argued from your goals; the stakeholder cares about theirs.",
        "Before the meeting, write down the one outcome you and this stakeholder both want, and open with it.",
    ),
    "ask": (
        "End with a specific ask and a date",
        "Without a clear request, a good discussion ends with nothing decided.",
        "Finish with one sentence: 'Can we agree to X by Y?'",
    ),
    "acknowledge": (
        "Acknowledge before you answer",
        "You went straight to rebutting, so the buyer felt handled rather than heard.",
        "Open every objection reply with a genuine acknowledgement, then pause before your answer.",
    ),
    "clarify": (
        "Ask what is really behind the objection",
        "You answered the surface objection, not the real one underneath it.",
        "Answer each objection with a question first: 'When you say price, compared with what?'",
    ),
    "reframe": (
        "Move the conversation onto value",
        "You defended on the buyer's terms, which makes every objection harder.",
        "Prepare one reframe for each common objection: price to value, timing to the cost of waiting.",
    ),
    "next_step": (
        "Close for a small, dated next step",
        "The conversation ended without a commitment, which usually means it ends there.",
        "End every practice call by proposing one small step with a day and a time.",
    ),
}


CONCERN_ANSWERS = {
    "cost": "All in, it costs [your figure], most of it my time to set up, and nothing in new spend.",
    "payback": "It pays back by [your date]: keeping even one experienced person saves [your figure] in hiring and training.",
    "budget": "It needs no new budget. The only cost is [your figure] hours of my time, taken from work we are pausing.",
    "opportunity cost": "Compared with the other options, like [the alternative], this is the cheapest thing we can try, and it is reversible.",
    "risk": "What breaks first is response times, so we track them weekly and stop if they slip by more than [your threshold].",
    "delivery": "I own it, with [a named colleague] as backup, and it needs nothing built.",
    "maintenance": "After launch it runs on a monthly check that takes [your figure] hours, and I keep that.",
    "reversibility": "If it doesn't work, we go back to the current set-up within a week, at no cost.",
    "disruption": "Cover stays the same throughout: the rota changes, the hours of service do not.",
    "workload": "No one takes on extra work; we drop [a low-value task] to make room.",
    "timing": "Now is when it costs least, before the busy season, and we review it before that starts.",
    "adoption": "The team asked for this, and two of them will run it with me, so it is theirs, not imposed.",
}
COMMON_GOAL = {
    "finance director": "a team that costs less to run, not more",
    "engineering lead": "fewer surprises in delivery",
    "head of operations": "a service that holds up while the team stays well",
}


def _rewrite(mode: str, user_text: str, opp_before: str | None, persona_role: str, topic: str) -> tuple[str, list[str]]:
    if mode == "sales":
        objection = objection_in(opp_before) or "price"
        acks = {
            "price": "That's a fair concern, and I'd rather you raised it now than later.",
            "timing": "That makes sense. Nobody wants a new project in a busy quarter.",
            "incumbent": "I understand. If something works, switching needs a very good reason.",
            "authority": "That's completely reasonable. A decision like this should involve her.",
        }
        clarifiers = {
            "price": "Can I ask what you're comparing it with?",
            "timing": "Can I ask what's taking most of the team's time this quarter?",
            "incumbent": "What do people like most about the current system, and what do they work around?",
            "authority": "What will matter most to her when she looks at it?",
        }
        reframes = {
            "price": "the real comparison isn't our price against theirs, it's what the current way costs you in staff time every week",
            "timing": "the busy quarter is exactly when the manual work hurts most, so waiting has a cost too",
            "incumbent": "you wouldn't rip anything out on day one; it runs alongside what you have until it earns its place",
            "authority": "it makes sense for your manager to see it, and I'd rather she asked her hard questions directly",
        }
        text = (
            f"{acks[objection]} {clarifiers[objection]} The way I'd look at it is that {reframes[objection]}. "
            "Teams like yours usually measure it in hours saved on [the task it replaces]. Rather than ask you to take my word for it, "
            "could we run a two-week pilot with one team and review the results together, with your manager in the room, on Thursday the week after?"
        )
        why = [
            "It acknowledges the objection before answering it, so the buyer feels heard.",
            "It asks a question to find out what is really behind the objection.",
            "It reframes the objection instead of defending on the buyer's terms.",
            "It closes for a small, dated next step instead of hoping for one.",
        ]
        return text, why
    if mode == "meeting":
        concern = concern_in(opp_before) or "cost"
        goal = COMMON_GOAL.get(persona_role.lower(), "the same outcome for the team")
        proposal = motion_core(topic)
        proposal = proposal[:1].lower() + proposal[1:]
        text = (
            f"That's the right question, and I'd ask it in your seat. {CONCERN_ANSWERS[concern]} "
            f"What we both want is {goal}. So here is my ask: can we agree to {proposal}, with the measures written down now "
            "and a review with you before anything is extended?"
        )
        why = [
            f"It answers the {concern} concern directly instead of restating the pitch.",
            "It puts a number where the stakeholder pushed, with placeholders for your real figures.",
            "It names the common ground before asking for anything.",
            "It ends with a specific, dated ask.",
        ]
        return text, why
    ss = [_sourced(_lead_trim(x)) for x in sentences(user_text)]
    ranked = sorted(ss, key=lambda x: -len(content_words(x)))
    p1 = ranked[0].rstrip(".!?") if ranked else "the harm this motion targets is real and it is happening now"
    p2 = ranked[1].rstrip(".!?") if len(ranked) > 1 else "the alternative has been tried and has not worked"
    lower = lambda x: x[:1].lower() + x[1:]  # noqa: E731
    if opp_before:
        line = next((a[1] for a in POLICY_AGAINST + BELIEF_AGAINST + ARGS_FOR if a[1] in opp_before), None)
        their = shorten(line, 12) if line else key_point(opp_before, 12)
        text = (
            f'My opponent says "{their}". That fails for two reasons. First, {lower(p1)}, which means their worry does not outweigh the harm we started with. '
            f"Second, {lower(p2)}. They have offered no alternative that works at the same scale, so the choice is between acting and hoping. "
            "So weigh it this way: who carries the cost if each side is wrong? On that test, our case stands."
        )
        why = [
            "It names the opponent's point in their words before answering it.",
            "It signposts two numbered reasons, so the judge can follow the clash.",
            "It keeps your original points but ties each one to an impact.",
            "It ends by telling the judge how to weigh the debate.",
        ]
    else:
        text = (
            f"I have two points tonight. First, {lower(p1)}. That matters because it is the harm this motion exists to fix. "
            f"Second, {lower(p2)}, and in practice that looks like [a specific example you have seen]. "
            "So the question for the room is simple: who carries the cost if we do nothing? On that test, the motion should pass."
        )
        why = [
            "It tells the room how many points are coming, then numbers them.",
            "Every figure is attributed to a named source, so the fact-checker has nothing to flag.",
            "It ties each point to why it matters instead of leaving it as an assertion.",
            "It finishes by framing the question the judge should decide on.",
        ]
    return text, why


def _sourced(sentence: str) -> str:
    """Rewrite an unsourced figure or an appeal to unnamed research as an attributed one, with placeholders."""
    out = UNNAMED_RESEARCH.sub("[a named survey, with its year] found", sentence)
    if not SOURCE.search(sentence) and "[a named survey" not in out and NUMBER.search(out):
        out = "According to [your source], " + out[:1].lower() + out[1:]
    return out


def _turn_quality(mode: str, users: list[str], opps_before: list[str | None], i: int) -> float:
    """A rough per-turn quality, for picking the turn most worth rewriting."""
    f = _per_turn([users[i]], [opps_before[i]])[0]
    if not f["text"].strip():
        return -1.0
    if mode == "sales":
        if f["objection"] is None:
            return 3.0 + f["next_steps"]  # openings and closes are rarely the turn to rewrite
        return (
            2 * min(1, f["ack"])
            + min(1, f["clarifying"])
            + min(1, f["reframes"])
            + min(1, f["sales_evidence"])
            + f["objection_handled"]
        )
    if mode == "meeting":
        if f["concern"] is None:
            return 3.0 + min(1, f["numbers"])
        return 2 * f["concern_answered"] + min(1, f["ack"]) + min(1, f["numbers"]) + min(1, f["common"])
    score = min(2, f["reasons"]) + min(2, f["signposts"]) + min(1, f["examples"] + f["sourced"])
    if f["has_opp"]:
        score += min(2, f["rebut_refs"] + (f["overlap"] or 0) * 3)
    else:
        score += 1.5
    unsourced = bool(UNNAMED_RESEARCH.search(f["text"]) or STATISTIC.search(f["text"])) and not f["sourced"]
    return score - 1.5 * unsourced


def coach(message: str) -> dict:
    t = tags(message)
    mode = t.get("mode", "debate")
    turns = parse_transcript(message)
    card = json.loads(t.get("scorecard") or '{"scores": []}')
    order = [c.id for c in rb.RUBRICS[mode]]
    ranked = sorted(
        card["scores"], key=lambda s: (s["score"], order.index(s["criterion"]) if s["criterion"] in order else 99)
    )
    improvements = []
    for s in ranked[:3]:
        title, why, drill = ADVICE[s["criterion"]]
        if s["score"] >= 7:
            why = f"Already solid at {s['score']}/10, so this is about consistency: do it in every turn, not just your best one."
        else:
            why = f"{why} It scored {s['score']}/10 this session."
        improvements.append({"title": title, "why": why, "drill": drill})

    users, opps_before, last_opp = [], [], None
    for turn in turns:
        if turn["speaker"] == "user":
            users.append("" if turn["text"].startswith("(no response") else turn["text"])
            opps_before.append(last_opp)
        else:
            last_opp = turn["text"]
    weakest = 1 + min(range(len(users)), key=lambda i: (_turn_quality(mode, users, opps_before, i), i)) if users else 1
    persona = re.search(r'<persona name="[^"]*" role="([^"]*)">', message)
    rewrite, why = _rewrite(
        mode,
        users[weakest - 1] if users else "",
        opps_before[weakest - 1] if users else None,
        persona.group(1) if persona else "",
        t.get("topic", ""),
    )
    return {"improvements": improvements, "weakest_turn": weakest, "rewrite": rewrite, "why_stronger": why}


# ─────────────────────────────── the model ───────────────────────────────


class ScriptedLLM:
    """Implements the ``LLM`` protocol with the rules above."""

    name = "scripted"

    def __init__(self, delay: float = 0.0) -> None:
        # Seconds between streamed words and before each decision, so a demo feels like a live model.
        self.delay = delay

    async def structured(
        self, system: str, messages: list[dict], schema: type[T], effort: str, think: bool = False
    ) -> T:
        last = messages[-1]["content"]
        if self.delay:
            await asyncio.sleep(self.delay * (30 if think else 10))
        if schema is rb.FactCheck:
            return schema.model_validate(fact_check(tags(last).get("turn", "")))
        if schema is rb.Scorecard:
            return schema.model_validate(judge(last))
        if schema is rb.Coaching:
            return schema.model_validate(coach(last))
        raise ValueError(f"ScriptedLLM has no script for {schema.__name__}")

    async def stream(self, system: str, messages: list[dict], effort: str) -> AsyncIterator[str]:
        reply = opponent_reply(system, messages)
        for i, word in enumerate(reply.split(" ")):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield word if i == 0 else " " + word

    async def research(self, system: str, text: str) -> tuple[str, list[dict]]:
        return "", []
