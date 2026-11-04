import type { Coaching, Scorecard, Session, Turn } from "../api";
import { plural } from "../copy";
import type { Step } from "../session";
import { Icon } from "./Icon";

function band(score: number): string {
  return score < 4 ? "weak" : score < 6 ? "developing" : score < 8 ? "solid" : "strong";
}

function Bar({ score }: { score: number }) {
  return (
    <span className={`bar bar-${band(score)}`} aria-hidden="true">
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} className={i < score ? "on" : ""} style={{ animationDelay: `${i * 35}ms` }} />
      ))}
    </span>
  );
}

function Judging({ steps }: { steps: Step[] }) {
  const state = (node: "judge" | "coach") => steps.find((s) => s.node === node)?.status ?? "waiting";
  return (
    <section className="judging" aria-busy="true" aria-live="polite">
      <p className="kicker">The bell has gone</p>
      <h2 className="display display-md">The judges are scoring</h2>
      <ol className="judging-steps">
        <li className={`js-${state("judge")}`}>Scoring every criterion against the rubric, with your own words as evidence</li>
        <li className={`js-${state("coach")}`}>The coach is picking your three highest-leverage fixes</li>
      </ol>
    </section>
  );
}

export function Report({
  session,
  turns,
  scorecard,
  coaching,
  steps,
}: {
  session: Session;
  turns: Turn[];
  scorecard: Scorecard | null;
  coaching: Coaching | null;
  steps: Step[];
}) {
  if (!scorecard) return <Judging steps={steps} />;
  const yours = turns.filter((t) => t.speaker === "user");
  const phaseOf = (n: number) => yours[n - 1]?.phase_name ?? "";
  const spoken = yours.filter((t) => t.delivery?.source === "voice");
  const paces = spoken.map((t) => t.delivery!.wpm).filter((w): w is number => w !== null);
  const fillers = yours.reduce((n, t) => n + (t.delivery?.filler_total ?? 0), 0);
  const flags = yours.reduce((n, t) => n + t.flags.length, 0);
  const overTime = yours.filter((t) => t.delivery?.over_time).length;

  return (
    <div className="report">
      <section className="scorecard" aria-labelledby="scorecard-title">
        <header className="scorecard-head">
          <div>
            <p className="kicker">Judges' scorecard</p>
            <h2 id="scorecard-title" className="decision">
              {scorecard.decision}
            </h2>
            <p className="summary">{scorecard.summary}</p>
          </div>
          <div className="overall" aria-label={`Overall ${scorecard.overall} out of 100`}>
            <span className="overall-num">{scorecard.overall}</span>
            <span className="overall-of">/100</span>
          </div>
        </header>

        <dl className="stat-row">
          <div>
            <dt>Turns</dt>
            <dd>{yours.length}</dd>
          </div>
          <div>
            <dt>Avg pace</dt>
            <dd>{paces.length ? `${Math.round(paces.reduce((a, b) => a + b, 0) / paces.length)} wpm` : "Typed"}</dd>
          </div>
          <div>
            <dt>Fillers</dt>
            <dd>{fillers}</dd>
          </div>
          <div>
            <dt>Claims flagged</dt>
            <dd>{flags}</dd>
          </div>
          <div>
            <dt>Over time</dt>
            <dd>{plural(overTime, "turn")}</dd>
          </div>
        </dl>

        <ol className="criteria">
          {scorecard.scores.map((s, i) => (
            <li key={s.criterion} className="criterion" style={{ animationDelay: `${i * 70}ms` }}>
              <div className="criterion-head">
                <h3>{s.name}</h3>
                <Bar score={s.score} />
                <span className="criterion-score">
                  <b>{s.score}</b>/10
                </span>
              </div>
              <p className="criterion-why">{s.explanation}</p>
              {s.quote ? (
                <figure className="evidence">
                  <blockquote>{s.quote}</blockquote>
                  <figcaption>
                    Your words, turn {s.turn}
                    {phaseOf(s.turn) && ` · ${phaseOf(s.turn)}`}
                  </figcaption>
                </figure>
              ) : (
                <p className="muted small">No words to quote from this turn.</p>
              )}
            </li>
          ))}
        </ol>
      </section>

      {coaching ? (
        <section className="coach" aria-labelledby="coach-title">
          <p className="kicker kicker-gold">In your corner</p>
          <h2 id="coach-title" className="display display-sm">
            Three things to fix before the next bout
          </h2>
          <ol className="improvements">
            {coaching.improvements.map((tip, i) => (
              <li key={tip.title}>
                <span className="imp-no">{i + 1}</span>
                <div>
                  <h3>{tip.title}</h3>
                  <p>{tip.why}</p>
                  <p className="drill">
                    <Icon name="whistle" size={16} /> <b>Drill:</b> {tip.drill}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <div className="rewrite">
            <figure className="rewrite-col rewrite-before">
              <figcaption>
                What you said · turn {coaching.weakest_turn}
                {coaching.weakest_phase && `, ${coaching.weakest_phase}`}
              </figcaption>
              <blockquote>{coaching.original || "Nothing, the clock ran out."}</blockquote>
            </figure>
            <figure className="rewrite-col rewrite-after">
              <figcaption>
                <Icon name="spark" size={16} /> The model answer
              </figcaption>
              <blockquote>{coaching.rewrite}</blockquote>
            </figure>
          </div>
          <div className="why-stronger">
            <h3>Why it's stronger</h3>
            <ul>
              {coaching.why_stronger.map((w) => (
                <li key={w}>
                  <Icon name="check" size={16} /> {w}
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : (
        <Judging steps={steps} />
      )}
      <p className="sr-only" aria-live="polite">
        {coaching ? `Scored ${scorecard.overall} out of 100 in ${session.mode}.` : ""}
      </p>
    </div>
  );
}
