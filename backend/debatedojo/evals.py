"""Judge-calibration evals: run whole sessions and check the agents did their jobs.

Each case is a scripted user. The runner plays every turn through the real graph, then checks
the fact-check flags, the opponent's engagement, the scorecard's shape and bounds, the coaching
and the house style. It runs offline on the scripted model in CI, and unchanged against Claude.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ROOT, get_settings
from .rubric import RUBRICS
from .service import Service
from .store import Store
from .text import DASHES, find_quote, overlap, stems

DEFAULT_CASES = ROOT / "evals" / "cases.yaml"
ENGAGE_MIN = 0.2  # share of the user's content words the reply must pick up


@dataclass
class Result:
    id: str
    failures: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures

    def check(self, name: str, ok: bool, why: str) -> None:
        # A check category passes for the case only if every instance of it passes.
        self.checks[name] = self.checks.get(name, True) and ok
        if not ok:
            self.failures.append(why)


async def run_case(service: Service, case: dict) -> Result:
    result = Result(case["id"])
    session = service.start(
        mode=case["mode"],
        topic=case["topic"],
        format_id=case.get("format"),
        persona_id=case.get("persona"),
        side=case.get("side"),
        context=case.get("context", ""),
    )
    written: list[str] = []  # everything the agents wrote, for the style check
    replies: dict[int, str] = {}
    flags: list[dict] = []
    card, coaching = None, None
    for n, turn in enumerate(case["turns"], 1):
        turn = turn if isinstance(turn, dict) else {"text": turn}
        async for event in service.turn(
            session["id"],
            turn["text"],
            input=turn.get("input", "typed"),
            duration_s=float(turn.get("talk_seconds", 30)),
            talk_seconds=turn.get("talk_seconds"),
            longest_pause_s=turn.get("longest_pause_s"),
        ):
            if event["type"] == "reply":
                replies[n] = event["turn"]["text"]
                written.append(replies[n])
            elif event["type"] == "flags":
                flags += event["flags"]
                written += [f"{f['reason']} {f['evidence_needed']}" for f in event["flags"]]
            elif event["type"] == "scorecard":
                card = event["scorecard"]
            elif event["type"] == "coaching":
                coaching = event["coaching"]
            elif event["type"] == "error":
                result.check("runs", False, f"turn {n} failed: {event['message']}")
                return result
    user_texts = [t["text"] if isinstance(t, dict) else t for t in case["turns"]]

    # fact-checker
    claims = [f["claim"].lower() for f in flags]
    for phrase in case.get("flagged", []):
        result.check(
            "flagged", any(phrase.lower() in c for c in claims), f"'{phrase}' was not flagged (flags: {claims})"
        )
    for phrase in case.get("not_flagged", []):
        result.check("not_flagged", not any(phrase.lower() in c for c in claims), f"'{phrase}' was flagged")

    # opponent
    for n, text in enumerate(user_texts, 1):
        reply = replies.get(n, "")
        if stems(text):  # a turn with no content words gives the reply nothing to pick up
            result.check("engages", overlap(reply, text) >= ENGAGE_MIN, f"reply to turn {n} ignores it: {reply[:90]}")
    for n, phrase in (case.get("reply_includes") or {}).items():
        reply = replies.get(int(n), "")
        result.check("reply_includes", phrase.lower() in reply.lower(), f"reply to turn {n} is missing '{phrase}'")

    # judge
    if card is None:
        result.check("report", False, "no scorecard")
        return result
    scores = {s["criterion"]: s for s in card["scores"]}
    for c in RUBRICS[case["mode"]]:
        s = scores.get(c.id)
        ok = bool(s and s["explanation"].strip() and s["quote"].strip())
        result.check("report", ok, f"{c.id} lacks an explanation or a quote")
        if s:
            located = find_quote(s["quote"], user_texts)
            result.check("report", located is not None, f"{c.id} quote is not the user's words: {s['quote'][:60]}")
            written.append(s["explanation"])
    for criterion, bounds in (case.get("scores") or {}).items():
        got = scores[criterion]["score"]
        if "max" in bounds:
            result.check(
                "calibration", got <= bounds["max"], f"{criterion} scored {got}, expected at most {bounds['max']}"
            )
        if "min" in bounds:
            result.check(
                "calibration", got >= bounds["min"], f"{criterion} scored {got}, expected at least {bounds['min']}"
            )
    written += [card["summary"], card["decision"]]

    # coach
    ok = bool(coaching and len(coaching["improvements"]) == 3 and coaching["rewrite"].strip())
    result.check("coach", ok, "coaching needs three improvements and a rewrite")
    if coaching:
        result.check(
            "coach",
            1 <= coaching["weakest_turn"] <= len(user_texts),
            "the rewrite points at a turn that does not exist",
        )
        written += [coaching["rewrite"], *coaching["why_stronger"]]
        written += [f"{i['title']} {i['why']} {i['drill']}" for i in coaching["improvements"]]

    dashed = [w for w in written if DASHES.search(w)]
    result.check("style", not dashed, f"uses an em or en dash: {dashed[:1]}")
    return result


async def evaluate(service: Service, cases: list[dict]) -> list[Result]:
    return [await run_case(service, case) for case in cases]


def summarise(results: list[Result]) -> dict[str, tuple[int, int]]:
    totals: dict[str, list[int]] = {}
    for r in results:
        for name, ok in r.checks.items():
            t = totals.setdefault(name, [0, 0])
            t[0] += ok
            t[1] += 1
    return {k: (v[0], v[1]) for k, v in totals.items()}


async def run(cases_path: str | None = None, verbose: bool = False) -> bool:
    cases = yaml.safe_load(Path(cases_path or DEFAULT_CASES).read_text(encoding="utf-8"))
    settings = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        service = Service.from_settings(settings, store=Store(Path(tmp) / "evals.db"))
        print(f"Running {len(cases)} cases on the {settings.llm} model\n")
        results = await evaluate(service, cases)
    for r in results:
        if verbose or not r.passed:
            print(f"{'PASS' if r.passed else 'FAIL'}  {r.id}" + "".join(f"\n      - {f}" for f in r.failures))
    print()
    for name, (ok, total) in summarise(results).items():
        print(f"  {name:<15} {ok}/{total}")
    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} cases passed")
    return passed == len(results)
