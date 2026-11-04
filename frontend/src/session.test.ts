import { describe, expect, it } from "vitest";
import { type DojoEvent, type Flag, parseSSE, type Position, type Turn } from "./api";
import { begin, formatClock, type Live, reduce, rollback, segments } from "./session";

describe("parseSSE", () => {
  it("parses complete frames and keeps the partial one", () => {
    const got: DojoEvent[] = [];
    const rest = parseSSE('event: token\r\ndata: {"type":"token","text":"You"}\r\n\r\nevent: token\r\ndata: {"type":"tok', (e) => got.push(e));
    expect(got).toEqual([{ type: "token", text: "You" }]);
    expect(rest).toBe('event: token\r\ndata: {"type":"tok');
  });

  it("handles several frames in one chunk and ignores comments", () => {
    const got: DojoEvent[] = [];
    const rest = parseSSE(': ping\n\ndata: {"type":"token","text":"a"}\n\ndata: {"type":"token","text":"b"}\n\n', (e) => got.push(e));
    expect(got.map((e) => (e.type === "token" ? e.text : ""))).toEqual(["a", "b"]);
    expect(rest).toBe("");
  });
});

const pos = (turn: number, done = false): Position => ({ done, turn, total: 3, slot: null });
const turn = (over: Partial<Turn>): Turn => ({
  id: 1, idx: 0, speaker: "user", slot: 0, phase_id: "opening", phase_name: "Opening", exchange: 1, text: "", input: "typed",
  duration_s: 10, limit_s: 60, timed_out: false, delivery: null, flags: [], fact_check: null, created_at: "", ...over,
});
const flag = (claim: string): Flag => ({ id: 1, claim, verdict: "unsupported", reason: "r", evidence_needed: "e", method: "knowledge", sources: [] });
const start: Live = { turns: [], position: pos(0), status: "live", streaming: null, steps: [], scorecard: null, coaching: null, error: null, busy: false };

describe("reduce", () => {
  it("records the turn, streams the reply, attaches flags and advances", () => {
    const events: DojoEvent[] = [
      { type: "step", node: "record", status: "running" },
      { type: "step", node: "record", status: "done", ms: 3, detail: "5 words" },
      { type: "turn", turn: turn({ id: 1, text: "Studies show 73% agree." }) },
      { type: "token", text: "Which " },
      { type: "token", text: "studies?" },
      { type: "flags", turn_id: 1, flags: [flag("Studies show 73% agree")], checked: 1, method: "knowledge" },
      { type: "reply", turn: turn({ id: 2, idx: 1, speaker: "opponent", text: "Which studies?" }) },
      { type: "position", position: pos(1) },
      { type: "final", status: "live", position: pos(1), ms: 900 },
    ];
    let live = begin(start);
    const seen: (string | null)[] = [];
    for (const e of events) {
      live = reduce(live, e);
      seen.push(live.streaming);
    }
    expect(seen).toContain("Which studies?");
    expect(live.streaming).toBeNull();
    expect(live.steps).toEqual([{ node: "record", status: "done", ms: 3, detail: "5 words" }]);
    expect(live.turns.map((t) => t.speaker)).toEqual(["user", "opponent"]);
    expect(live.turns[0].flags).toHaveLength(1);
    expect(live.turns[0].fact_check).toEqual({ checked: 1, method: "knowledge" });
    expect(live.position.turn).toBe(1);
    expect(live.busy).toBe(false);
  });

  it("moves to judging at the end and keeps the report", () => {
    let live = reduce(begin(start), { type: "position", position: pos(3, true) });
    expect(live.status).toBe("judging");
    live = reduce(live, { type: "scorecard", scorecard: { scores: [], overall: 64, summary: "s", decision: "Split decision" } });
    live = reduce(live, { type: "final", status: "finished", position: pos(3, true), ms: 1 });
    expect(live.scorecard?.overall).toBe(64);
    expect(live.status).toBe("finished");
  });

  it("drops a rolled-back turn when the stream fails", () => {
    const before = begin(start);
    let live = reduce(before, { type: "turn", turn: turn({ id: 9, text: "lost?" }) });
    live = reduce(live, { type: "error", message: "Something went wrong" });
    expect(live.error).toBe("Something went wrong");
    const back = rollback(live, before, "Something went wrong");
    expect(back.turns).toEqual([]);
    expect(back.error).toBe("Something went wrong");
  });
});

describe("segments", () => {
  it("marks flagged claims inline, ignoring case and truncation", () => {
    const parts = segments("Phones are bad. Studies show that 73% agree, and nobody disagrees.", [
      flag("studies show that 73% agree"),
      flag("missing from the text"),
    ]);
    expect(parts.map((p) => [p.text, Boolean(p.flag)])).toEqual([
      ["Phones are bad. ", false],
      ["Studies show that 73% agree", true],
      [", and nobody disagrees.", false],
    ]);
  });

  it("matches a claim the checker shortened with an ellipsis", () => {
    const parts = segments("A very long claim that goes on and on.", [flag("A very long claim...")]);
    expect(parts[0]).toMatchObject({ text: "A very long claim" });
  });
});

it("formats a countdown", () => {
  expect(formatClock(185)).toBe("3:05");
  expect(formatClock(0.2)).toBe("0:01");
  expect(formatClock(-4)).toBe("0:00");
});
