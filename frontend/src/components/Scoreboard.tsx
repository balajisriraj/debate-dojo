import type { Session, Slot } from "../api";
import { MODE_COPY } from "../copy";
import { formatClock } from "../session";

export type ClockState = "armed" | "running" | "opponent" | "judging" | "final";

const CLOCK_LABEL: Record<ClockState, string> = {
  armed: "Starts when you do",
  running: "Your time",
  opponent: "On the mic",
  judging: "Judges scoring",
  final: "Final score",
};

export function Scoreboard({
  session,
  slot,
  remaining,
  clock,
  userTurns,
  overall,
}: {
  session: Session;
  slot: Slot | null;
  remaining: number;
  clock: ClockState;
  userTurns: number;
  overall: number | null;
}) {
  const copy = MODE_COPY[session.mode];
  const yourRole = session.side ?? (session.mode === "meeting" ? "Presenting" : "Selling");
  const theirRole = session.mode === "debate" ? (session.side === "proposition" ? "Opposition" : "Proposition") : session.persona.role;
  const low = clock === "running" && remaining <= 10;
  return (
    <section className={`scoreboard mode-${session.mode}`} aria-label="Scoreboard">
      <div className="board-row">
        <div className={`corner corner-you ${clock === "armed" || clock === "running" ? "is-up" : ""}`}>
          <span className="corner-label">You</span>
          <span className="corner-role">{yourRole}</span>
          <span className="corner-stat">
            {Math.min(userTurns, session.plan.length)} / {session.plan.length} turns
          </span>
        </div>

        <div className={`board-clock clock-${clock} ${low ? "is-low" : ""}`}>
          <span className="board-phase">
            {slot ? (
              <>
                {slot.phase_name}
                {slot.exchanges > 1 && <span className="board-exchange"> {slot.exchange} of {slot.exchanges}</span>}
              </>
            ) : (
              "Bout over"
            )}
          </span>
          <span className="clock-digits" role="timer" aria-label={clock === "final" ? `Overall ${overall ?? "pending"} out of 100` : `${formatClock(remaining)} remaining`}>
            {clock === "final" ? (overall ?? "--") : clock === "judging" ? "--:--" : formatClock(remaining)}
          </span>
          <span className="clock-label">{CLOCK_LABEL[clock]}</span>
        </div>

        <div className={`corner corner-opp ${clock === "opponent" ? "is-up" : ""}`}>
          <span className="corner-label">{copy.opponentLabel}</span>
          <span className="corner-role">{theirRole}</span>
          <span className="corner-stat">{session.persona.name}</span>
        </div>
      </div>
      <p className="board-topic">
        <span className="board-topic-tag">{copy.topicTag}</span>
        <span className="board-topic-text">{session.topic}</span>
      </p>
    </section>
  );
}
