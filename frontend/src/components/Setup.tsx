import { type FormEvent, useState } from "react";
import { api, type Catalog, type Mode, type SalesSample, type Side } from "../api";
import { clock, MODE_COPY } from "../copy";
import { go, href } from "../router";
import { Icon } from "./Icon";

const STEP = 15;

export function Setup({ catalog, mode }: { catalog: Catalog; mode: Mode }) {
  const entry = catalog.modes.find((m) => m.id === mode)!;
  const copy = MODE_COPY[mode];
  const [formatId, setFormatId] = useState(entry.formats[0].id);
  const [personaId, setPersonaId] = useState(entry.personas[0].id);
  const [side, setSide] = useState<Side>("proposition");
  const [topic, setTopic] = useState("");
  const [buyer, setBuyer] = useState("");
  const [context, setContext] = useState("");
  const [timers, setTimers] = useState<Record<string, number>>({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const format = entry.formats.find((f) => f.id === formatId)!;
  const seconds = (id: string, fallback: number) => timers[id] ?? fallback;
  const total = format.phases.reduce((sum, p) => sum + p.exchanges * seconds(p.id, p.seconds), 0);

  const samples = entry.samples;
  const useSample = (s: string | SalesSample) => {
    if (typeof s === "string") setTopic(s);
    else {
      setTopic(s.product);
      setBuyer(s.buyer);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (topic.trim().length < 3) {
      setError(`Add ${copy.topicLabel.toLowerCase()} first.`);
      return;
    }
    setSending(true);
    setError(null);
    const bits = [mode === "sales" && buyer.trim() ? `Buyer: ${buyer.trim()}` : "", context.trim()].filter(Boolean);
    try {
      const session = await api.start({
        mode,
        topic: topic.trim(),
        format_id: formatId,
        persona_id: mode === "debate" ? undefined : personaId,
        side: mode === "debate" ? side : undefined,
        context: bits.join("\n"),
        timers: Object.fromEntries(Object.entries(timers).filter(([id, s]) => format.phases.some((p) => p.id === id && p.seconds !== s))),
      });
      go({ page: "bout", id: session.id });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start the session.");
      setSending(false);
    }
  };

  return (
    <form className={`setup mode-${mode}`} onSubmit={submit} noValidate>
      <a className="back" href={href({ page: "home" })}>
        <Icon name="back" size={18} /> All modes
      </a>
      <header className="setup-head">
        <p className="kicker">{copy.card}</p>
        <h1 className="display display-md">Set the card</h1>
        <p className="lede">{copy.blurb}</p>
      </header>

      <div className="setup-grid">
        <section className="panel" aria-labelledby="topic-label">
          <label id="topic-label" htmlFor="topic" className="field-label">
            {copy.topicLabel}
          </label>
          <textarea
            id="topic"
            className="input input-xl"
            rows={2}
            maxLength={300}
            value={topic}
            placeholder={copy.topicHint}
            onChange={(e) => setTopic(e.target.value)}
            aria-describedby="topic-samples"
            aria-invalid={Boolean(error) && topic.trim().length < 3}
          />
          <div id="topic-samples" className="chips" role="group" aria-label="Examples">
            <span className="chips-label">Try</span>
            {samples.map((s) => {
              const label = typeof s === "string" ? s : s.product;
              return (
                <button key={label} type="button" className="chip" onClick={() => useSample(s)}>
                  {label}
                </button>
              );
            })}
          </div>

          {mode === "sales" && (
            <>
              <label htmlFor="buyer" className="field-label">
                Who you are selling to
              </label>
              <input id="buyer" className="input" maxLength={200} value={buyer} placeholder="e.g. Practice manager at a mid-sized clinic" onChange={(e) => setBuyer(e.target.value)} />
            </>
          )}
          {mode !== "debate" && (
            <>
              <label htmlFor="context" className="field-label">
                Background <span className="optional">optional</span>
              </label>
              <textarea
                id="context"
                className="input"
                rows={3}
                maxLength={1200}
                value={context}
                placeholder={mode === "meeting" ? "Anything the stakeholder already knows: budget, past attempts, deadlines." : "What the buyer uses today, team size, anything you know."}
                onChange={(e) => setContext(e.target.value)}
              />
            </>
          )}

          {mode === "debate" ? (
            <fieldset className="choice">
              <legend className="field-label">Your side</legend>
              <div className="sides">
                {(["proposition", "opposition"] as const).map((s) => (
                  <label key={s} className={`side side-${s}`}>
                    <input type="radio" name="side" value={s} checked={side === s} onChange={() => setSide(s)} />
                    <span className="side-name">{s}</span>
                    <span className="side-desc">{s === "proposition" ? "You argue for the motion" : "You argue against it"}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <fieldset className="choice">
              <legend className="field-label">Who you are up against</legend>
              <div className="option-list">
                {entry.personas.map((p) => (
                  <label key={p.id} className="option">
                    <input type="radio" name="persona" value={p.id} checked={personaId === p.id} onChange={() => setPersonaId(p.id)} />
                    <span className="option-title">{p.name}</span>
                    <span className="option-desc">{p.style}</span>
                    <span className="option-tags">{(mode === "meeting" ? p.concerns : p.objections).join(" · ")}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </section>

        <section className="panel" aria-labelledby="format-label">
          {entry.formats.length > 1 ? (
            <fieldset className="choice">
              <legend id="format-label" className="field-label">
                Format
              </legend>
              <div className="option-list">
                {entry.formats.map((f) => (
                  <label key={f.id} className="option">
                    <input type="radio" name="format" value={f.id} checked={formatId === f.id} onChange={() => setFormatId(f.id)} />
                    <span className="option-title">{f.name}</span>
                    <span className="option-desc">{f.blurb}</span>
                    <span className="option-tags">{f.phases.map((p) => (p.exchanges > 1 ? `${p.name} ×${p.exchanges}` : p.name)).join(" · ")}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <div>
              <h2 id="format-label" className="field-label">
                Format: {format.name}
              </h2>
              <p className="muted">{format.blurb}</p>
            </div>
          )}

          <fieldset className="choice timers">
            <legend className="field-label">
              Turn timers <span className="optional">your time per turn</span>
            </legend>
            <ul>
              {format.phases.map((p) => {
                const value = seconds(p.id, p.seconds);
                const set = (v: number) => setTimers((t) => ({ ...t, [p.id]: Math.max(15, Math.min(600, v)) }));
                return (
                  <li key={p.id} className="timer-row">
                    <span className="timer-phase">
                      {p.name}
                      {p.exchanges > 1 && <small> ×{p.exchanges}</small>}
                    </span>
                    <span className="stepper">
                      <button type="button" onClick={() => set(value - STEP)} aria-label={`${p.name}: ${STEP} seconds less`} disabled={value <= 15}>
                        <Icon name="minus" size={18} />
                      </button>
                      <output aria-live="polite" aria-label={`${p.name} turn length`}>
                        {clock(value)}
                      </output>
                      <button type="button" onClick={() => set(value + STEP)} aria-label={`${p.name}: ${STEP} seconds more`} disabled={value >= 600}>
                        <Icon name="plus" size={18} />
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className="muted small">
              About {Math.max(1, Math.round((total * 1.8) / 60))} minutes in all, with the opponent's replies. The clock starts when you start
              speaking or typing.
            </p>
          </fieldset>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-primary btn-xl" type="submit" disabled={sending}>
            <Icon name="bell" /> {sending ? "Setting up…" : copy.start}
          </button>
        </section>
      </div>
    </form>
  );
}
