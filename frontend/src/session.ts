// The arena's live state: one reducer folds the stream of agent events into the session view.
import type { Coaching, DojoEvent, Flag, NodeName, Position, Scorecard, Session, Turn } from "./api";

export type Step = { node: NodeName; status: "running" | "done" | "skipped" | "failed"; ms?: number; detail?: string };

export type Live = {
  turns: Turn[];
  position: Position;
  status: Session["status"];
  /** The opponent's reply while it streams, before it is saved as a turn. */
  streaming: string | null;
  steps: Step[];
  scorecard: Scorecard | null;
  coaching: Coaching | null;
  error: string | null;
  busy: boolean;
};

export function fromSession(s: Session): Live {
  return {
    turns: s.turns,
    position: s.position,
    status: s.status,
    streaming: null,
    steps: [],
    scorecard: s.report?.scorecard ?? null,
    coaching: s.report?.coaching ?? null,
    error: null,
    busy: false,
  };
}

/** A new request: clear the last one's trace and error. */
export function begin(live: Live): Live {
  return { ...live, steps: [], error: null, busy: true };
}

export function reduce(live: Live, event: DojoEvent): Live {
  switch (event.type) {
    case "step": {
      const steps = [...live.steps];
      const open = steps.findIndex((s) => s.node === event.node && s.status === "running");
      const step: Step = { node: event.node, status: event.status, ms: event.ms, detail: event.detail };
      if (open >= 0 && event.status !== "running") steps[open] = step;
      else steps.push(step);
      return { ...live, steps };
    }
    case "turn":
      return { ...live, turns: [...live.turns.filter((t) => t.id !== event.turn.id), event.turn], streaming: "" };
    case "flags":
      return {
        ...live,
        turns: live.turns.map((t) =>
          t.id === event.turn_id ? { ...t, flags: event.flags as Flag[], fact_check: { checked: event.checked, method: event.method } } : t,
        ),
      };
    case "token":
      return { ...live, streaming: (live.streaming ?? "") + event.text };
    case "reply":
      return { ...live, turns: [...live.turns, event.turn], streaming: null };
    case "position":
      return { ...live, position: event.position, status: event.position.done ? "judging" : live.status };
    case "scorecard":
      return { ...live, scorecard: event.scorecard };
    case "coaching":
      return { ...live, coaching: event.coaching };
    case "final":
      return { ...live, status: event.status, position: event.position, busy: false, streaming: null };
    case "error":
      return { ...live, error: event.message, busy: false, streaming: null };
  }
}

/** A failed request rolls back the turn it recorded, so the view drops it too. */
export function rollback(live: Live, before: Live, message: string): Live {
  return { ...before, steps: live.steps, error: message, busy: false };
}

export const userTurns = (turns: Turn[]) => turns.filter((t) => t.speaker === "user");

/** Split a turn's text around its flagged claims, so the flags can be marked inline. */
export function segments(text: string, flags: Flag[]): { text: string; flag?: Flag }[] {
  const spans: { start: number; end: number; flag: Flag }[] = [];
  const lower = text.toLowerCase();
  for (const flag of flags) {
    const at = lower.indexOf(flag.claim.toLowerCase().replace(/\.\.\.$/, ""));
    if (at < 0) continue;
    const end = at + flag.claim.replace(/\.\.\.$/, "").length;
    if (spans.some((s) => at < s.end && end > s.start)) continue;
    spans.push({ start: at, end, flag });
  }
  spans.sort((a, b) => a.start - b.start);
  const out: { text: string; flag?: Flag }[] = [];
  let cursor = 0;
  for (const s of spans) {
    if (s.start > cursor) out.push({ text: text.slice(cursor, s.start) });
    out.push({ text: text.slice(s.start, s.end), flag: s.flag });
    cursor = s.end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) });
  return out;
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
