// Client for the DebateDojo API. Turns and verdicts arrive as Server-Sent Events over a POST,
// which EventSource can't do, so the stream is read and parsed by hand.

export type Mode = "debate" | "meeting" | "sales";
export type Side = "proposition" | "opposition";

export type Phase = { id: string; name: string; exchanges: number; seconds: number; you: string; opponent: string };
export type Format = { id: string; name: string; mode: Mode; blurb: string; phases: Phase[] };
export type Persona = { id: string; name: string; role: string; style: string; concerns: string[]; objections: string[] };
export type SalesSample = { product: string; buyer: string };
export type ModeCatalog = { id: Mode; formats: Format[]; personas: Persona[]; samples: (string | SalesSample)[] };
export type Catalog = { modes: ModeCatalog[] };

export type Slot = {
  index: number;
  phase_id: string;
  phase_name: string;
  exchange: number;
  exchanges: number;
  seconds: number;
  guidance: string;
  opponent_role: string;
};
export type Position = { done: boolean; turn: number; total: number; slot: Slot | null };

export type Delivery = {
  source: "voice" | "typed";
  words: number;
  wpm: number | null;
  fillers: Record<string, number>;
  filler_total: number;
  fillers_per_100: number;
  longest_pause_s: number | null;
  talk_seconds: number;
  limit_seconds: number;
  talk_ratio: number;
  over_time: boolean;
};

export type Flag = {
  id: number;
  claim: string;
  verdict: "unsupported" | "doubtful";
  reason: string;
  evidence_needed: string;
  method: string;
  sources: { title: string; url: string }[];
};

export type Turn = {
  id: number;
  idx: number;
  speaker: "user" | "opponent";
  slot: number;
  phase_id: string;
  phase_name: string;
  exchange: number;
  text: string;
  input: "voice" | "typed" | "model";
  duration_s: number | null;
  limit_s: number | null;
  timed_out: boolean;
  delivery: Delivery | null;
  flags: Flag[];
  fact_check: { checked: number; method: string } | null;
  created_at: string;
};

export type Criterion = { id: string; name: string; looks_for: string };

export type Score = {
  criterion: string;
  name: string;
  looks_for: string;
  score: number;
  explanation: string;
  quote: string;
  quote_exact: boolean;
  turn: number;
};
export type Scorecard = { scores: Score[]; overall: number; summary: string; decision: string };

export type Coaching = {
  improvements: { title: string; why: string; drill: string }[];
  weakest_turn: number;
  weakest_phase: string;
  original: string;
  rewrite: string;
  why_stronger: string[];
};

export type Session = {
  id: string;
  mode: Mode;
  format_id: string;
  format: Format;
  topic: string;
  side: Side | null;
  persona_id: string;
  context: string;
  status: "live" | "judging" | "finished";
  overall: number | null;
  created_at: string;
  finished_at: string | null;
  turns: Turn[];
  report: { scorecard: Scorecard; coaching: Coaching } | null;
  plan: Slot[];
  position: Position;
  persona: Persona;
  rubric: Criterion[];
};

export type SessionSummary = Omit<Session, "turns" | "report" | "plan" | "position" | "persona" | "rubric" | "format"> & {
  user_turns: number;
};

export type Progress = {
  mode: Mode;
  rubric: Criterion[];
  sessions: { id: string; topic: string; format_id: string; overall: number; finished_at: string; scores: Record<string, number> }[];
};

export type Health = { status: string; llm: string; model: string; fact_check: "web" | "knowledge"; timer_bounds: [number, number] };

export type NodeName = "record" | "fact_check" | "opponent" | "advance" | "judge" | "coach";

export type DojoEvent =
  | { type: "step"; node: NodeName; status: "running" | "done" | "skipped" | "failed"; ms?: number; detail?: string }
  | { type: "turn"; turn: Turn }
  | { type: "flags"; turn_id: number; flags: Flag[]; checked: number; method: string }
  | { type: "token"; text: string }
  | { type: "reply"; turn: Turn }
  | { type: "position"; position: Position }
  | { type: "scorecard"; scorecard: Scorecard }
  | { type: "coaching"; coaching: Coaching }
  | { type: "final"; status: Session["status"]; position: Position; ms: number }
  | { type: "error"; message: string };

export type TurnBody = {
  text: string;
  input: "typed" | "voice";
  duration_s: number;
  talk_seconds: number | null;
  longest_pause_s: number | null;
  timed_out: boolean;
};

export type StartBody = {
  mode: Mode;
  topic: string;
  format_id?: string;
  persona_id?: string;
  side?: Side;
  context?: string;
  timers?: Record<string, number>;
};

/** Split an SSE byte stream into parsed `data:` payloads. Returns the unconsumed remainder. */
export function parseSSE(buffer: string, emit: (event: DojoEvent) => void): string {
  const frames = buffer.split(/\r?\n\r?\n/);
  const rest = frames.pop() ?? "";
  for (const frame of frames) {
    const data = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data) emit(JSON.parse(data) as DojoEvent);
  }
  return rest;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function failure(res: Response): Promise<ApiError> {
  let detail = `Request failed (${res.status})`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = "Some of those details aren't valid. Check the form and try again.";
  } catch {
    /* not JSON */
  }
  return new ApiError(detail, res.status);
}

async function stream(url: string, body: unknown, onEvent: (e: DojoEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (!res.ok || !res.body) throw await failure(res);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer = parseSSE(buffer + value, onEvent);
  }
  parseSSE(buffer + "\n\n", onEvent);
}

const json = async <T>(res: Response): Promise<T> => {
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
};

export const api = {
  health: () => fetch("/api/health").then(json<Health>),
  catalog: () => fetch("/api/catalog").then(json<Catalog>),
  sessions: () => fetch("/api/sessions").then(json<SessionSummary[]>),
  session: (id: string) => fetch(`/api/sessions/${id}`).then(json<Session>),
  start: (body: StartBody) =>
    fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(
      json<Session>,
    ),
  remove: (id: string) => fetch(`/api/sessions/${id}`, { method: "DELETE" }).then(json<{ deleted: string }>),
  progress: (mode: Mode) => fetch(`/api/progress/${mode}`).then(json<Progress>),
  turn: (id: string, body: TurnBody, onEvent: (e: DojoEvent) => void, signal?: AbortSignal) =>
    stream(`/api/sessions/${id}/turns`, body, onEvent, signal),
  finish: (id: string, onEvent: (e: DojoEvent) => void, signal?: AbortSignal) =>
    stream(`/api/sessions/${id}/finish`, {}, onEvent, signal),
};
