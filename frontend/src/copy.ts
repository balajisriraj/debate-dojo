// Words the UI uses for each mode, in one place.
import type { Mode } from "./api";

export const MODE_COPY: Record<
  Mode,
  { name: string; card: string; blurb: string; topicLabel: string; topicHint: string; topicTag: string; opponentLabel: string; start: string }
> = {
  debate: {
    name: "Debate",
    card: "Formal debate",
    blurb: "Pick a motion and a side. The opponent takes the other side and argues it properly.",
    topicLabel: "The motion",
    topicHint: "Phrase it the formal way, e.g. This house would…",
    topicTag: "The motion",
    opponentLabel: "Opponent",
    start: "Ring the bell",
  },
  meeting: {
    name: "Meeting",
    card: "Meeting prep",
    blurb: "Describe the proposal you will make. A sceptical stakeholder pushes back the way the real one will.",
    topicLabel: "Your proposal",
    topicHint: "One line: what you want to happen.",
    topicTag: "The proposal",
    opponentLabel: "Stakeholder",
    start: "Walk into the room",
  },
  sales: {
    name: "Sales",
    card: "Objection handling",
    blurb: "Describe your product and the buyer. They raise price, timing, the tool they already use and the boss.",
    topicLabel: "What you sell",
    topicHint: "The product in a line, as you would describe it to a buyer.",
    topicTag: "The pitch",
    opponentLabel: "Buyer",
    start: "Start the call",
  },
};

export const VERDICT_LABEL = { unsupported: "Unsupported", doubtful: "Doubtful" } as const;

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}

export function clock(seconds: number): string {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function when(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
