// Delivery metrics in the browser, for the live meter while the user speaks. The server computes
// the canonical numbers with the same rules (backend/debatedojo/metrics.py); both are tested
// against fixtures/delivery-cases.json, so the meter and the judge never disagree.

export const FILLERS = ["um", "uh", "like", "you know", "basically", "sort of"] as const;
export type Filler = (typeof FILLERS)[number];

const TOKEN = /[a-z0-9]+(?:'[a-z]+)?|[,]|[.!?;:]/g;
const UM = new Set(["um", "umm", "ummm", "erm", "hmm"]);
const UH = new Set(["uh", "uhh", "uhm", "er"]);
const LIKE_AFTER = new Set(["um", "uh", "and", "so", "was", "is", "it's", "were", "i'm", "they're", "we're", "you're", "be", "been", "just", "but"]);
const LIKE_NOT_BEFORE = new Set(["a", "an", "the", "this", "that", "these", "those", "it", "me", "you", "him", "her", "us", "them", "my", "your", "our", "their", "his", "its", "to", "what", "how", "when"]);
const YK_NOT_AFTER = new Set(["do", "did", "don't", "didn't", "if", "as", "would", "could", "should", "will", "might", "may", "let", "what", "how", "you", "now", "then"]);
const YK_NOT_BEFORE = new Set(["what", "how", "why", "when", "where", "who", "which", "that", "if", "whether", "the", "a", "an", "about", "him", "her", "them", "it", "this", "me", "us", "more", "better"]);
const SORT_NOT_AFTER = new Set(["a", "the", "what", "that", "this", "some", "any", "which", "every", "one", "no", "each", "same", "right", "wrong"]);

export function tokenize(text: string): string[] {
  const matches = text.toLowerCase().replaceAll("’", "'").match(TOKEN) ?? [];
  return matches.map((t) => (".!?;:".includes(t) ? "." : t));
}

export function countFillers(text: string): Record<Filler, number> {
  const tokens = tokenize(text);
  const counts = Object.fromEntries(FILLERS.map((f) => [f, 0])) as Record<Filler, number>;
  tokens.forEach((tok, i) => {
    const prev = i > 0 ? tokens[i - 1] : ".";
    const next = i + 1 < tokens.length ? tokens[i + 1] : ".";
    if (UM.has(tok)) counts.um++;
    else if (UH.has(tok)) counts.uh++;
    else if (tok === "basically") counts.basically++;
    else if (tok === "like") {
      if (prev === "," || next === "," || UM.has(next) || UH.has(next) || (LIKE_AFTER.has(prev) && !LIKE_NOT_BEFORE.has(next))) counts.like++;
    } else if (tok === "you" && next === "know") {
      const after = i + 2 < tokens.length ? tokens[i + 2] : ".";
      if (after === "," || after === "." || (!YK_NOT_AFTER.has(prev) && !YK_NOT_BEFORE.has(after))) counts["you know"]++;
    } else if (tok === "sort" && next === "of" && !SORT_NOT_AFTER.has(prev)) counts["sort of"]++;
  });
  return counts;
}

export const totalFillers = (counts: Record<string, number>) => Object.values(counts).reduce((a, b) => a + b, 0);

export function wordCount(text: string): number {
  return tokenize(text).filter((t) => t !== "," && t !== ".").length;
}

/** Pace over time spent speaking. Too short a sample says nothing, so it is null. */
export function wordsPerMinute(words: number, seconds: number | null): number | null {
  if (!seconds || seconds < 3 || words === 0) return null;
  return Math.round((words / (seconds / 60)) * 10) / 10;
}

/**
 * The longest silence while the mic was open, from the times speech results arrived.
 * Recognition fires as words land, so a long gap between results is a pause in speech.
 */
export function longestPause(startedAt: number, resultTimes: number[], endedAt: number): number | null {
  if (!resultTimes.length) return null;
  const marks = [startedAt, ...resultTimes, endedAt].sort((a, b) => a - b);
  let longest = 0;
  for (let i = 1; i < marks.length; i++) longest = Math.max(longest, marks[i] - marks[i - 1]);
  return Math.round(longest / 100) / 10;
}
