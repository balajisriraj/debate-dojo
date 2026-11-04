import type { Delivery, Mode, Turn } from "../api";
import { clock, MODE_COPY, plural, VERDICT_LABEL } from "../copy";
import { segments } from "../session";
import { Icon } from "./Icon";

function DeliveryLine({ d }: { d: Delivery }) {
  const bits: string[] = [];
  if (d.source === "voice") {
    if (d.wpm !== null) bits.push(`${Math.round(d.wpm)} wpm`);
    bits.push(plural(d.filler_total, "filler"));
    if (d.longest_pause_s !== null) bits.push(`longest pause ${d.longest_pause_s}s`);
  } else {
    bits.push(plural(d.words, "word"));
    if (d.filler_total) bits.push(plural(d.filler_total, "filler"));
  }
  return (
    <footer className="turn-meta">
      <span className={`src src-${d.source}`}>
        <Icon name={d.source === "voice" ? "mic" : "send"} size={14} />
        {d.source === "voice" ? "Spoken" : "Typed"}
      </span>
      {bits.map((b) => (
        <span key={b}>{b}</span>
      ))}
      <span className={d.over_time ? "over" : ""}>
        <Icon name="clock" size={14} /> {clock(Math.min(d.talk_seconds, 5999))} of {clock(d.limit_seconds)}
      </span>
    </footer>
  );
}

export function TurnCard({ turn, mode, streaming = false }: { turn: Turn; mode: Mode; streaming?: boolean }) {
  const you = turn.speaker === "user";
  const label = you ? "You" : MODE_COPY[mode].opponentLabel;
  const parts = you ? segments(turn.text, turn.flags) : [{ text: turn.text }];
  const unmatched = turn.flags.filter((f) => !parts.some((p) => p.flag?.id === f.id));
  return (
    <article className={`turn turn-${you ? "you" : "opp"} ${streaming ? "is-streaming" : ""}`} aria-label={`${label}, ${turn.phase_name}`}>
      <header className="turn-tab">
        <span className="turn-corner">{label}</span>
        <span className="turn-phase">
          {turn.phase_name}
          {turn.exchange > 1 || turn.phase_id === "rapid" ? ` · ${turn.exchange}` : ""}
        </span>
        {turn.timed_out && <span className="tag tag-time">Time ran out</span>}
        {you && turn.fact_check && (
          <span className={`tag ${turn.flags.length ? "tag-flag" : "tag-clean"}`}>
            <Icon name={turn.flags.length ? "flag" : "check"} size={14} />
            {turn.flags.length ? plural(turn.flags.length, "flag") : turn.fact_check.checked ? "Claims check out" : "No factual claims"}
          </span>
        )}
      </header>
      <p className="turn-text">
        {turn.text ? (
          parts.map((p, i) =>
            p.flag ? (
              <mark key={i} className={`claim claim-${p.flag.verdict}`} aria-describedby={`flag-${p.flag.id}`} tabIndex={0}>
                {p.text}
              </mark>
            ) : (
              <span key={i}>{p.text}</span>
            ),
          )
        ) : (
          <span className="muted">{streaming ? "" : "Nothing said before the clock ran out."}</span>
        )}
        {streaming && <span className="caret" aria-hidden="true" />}
      </p>
      {turn.flags.length > 0 && (
        <ul className="flags" aria-label="Fact-check flags">
          {turn.flags.map((f) => (
            <li key={f.id} id={`flag-${f.id}`} className={`flag flag-${f.verdict}`}>
              <span className="flag-verdict">
                <Icon name="flag" size={14} /> {VERDICT_LABEL[f.verdict]}
              </span>
              <span className="flag-body">
                {unmatched.includes(f) && <q className="flag-claim">{f.claim}</q>}
                <span className="flag-reason">{f.reason}</span>
                <span className="flag-need">
                  <b>Would need:</b> {f.evidence_needed}
                </span>
                {f.sources.length > 0 && (
                  <span className="flag-sources">
                    {f.sources.map((s) => (
                      <a key={s.url} href={s.url} target="_blank" rel="noreferrer">
                        {s.title || new URL(s.url).hostname}
                      </a>
                    ))}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {you && turn.delivery && <DeliveryLine d={turn.delivery} />}
    </article>
  );
}
