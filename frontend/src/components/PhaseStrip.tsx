import type { Session } from "../api";
import { clock } from "../copy";

/** The format's phases left to right, with a pip per exchange: done, live, or still to come. */
export function PhaseStrip({ session, turn, done }: { session: Session; turn: number; done: boolean }) {
  return (
    <ol className="phase-strip" aria-label="Phases">
      {session.format.phases.map((phase) => {
        const slots = session.plan.filter((s) => s.phase_id === phase.id);
        const first = slots[0].index;
        const last = slots[slots.length - 1].index;
        const state = done || turn > last ? "done" : turn >= first ? "live" : "next";
        return (
          <li key={phase.id} className={`phase phase-${state}`} aria-current={state === "live" ? "step" : undefined}>
            <span className="phase-name">{phase.name}</span>
            <span className="phase-time">{clock(phase.seconds)}</span>
            <span className="pips" aria-hidden="true">
              {slots.map((s) => (
                <span key={s.index} className={`pip ${done || turn > s.index ? "pip-done" : turn === s.index ? "pip-live" : ""}`} />
              ))}
            </span>
            <span className="sr-only">{state === "done" ? "done" : state === "live" ? "in progress" : "to come"}</span>
          </li>
        );
      })}
    </ol>
  );
}
