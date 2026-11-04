import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type DojoEvent, type Health, type Session, type Turn, type TurnBody } from "../api";
import { countFillers, totalFillers, wordCount, wordsPerMinute } from "../delivery";
import { MODE_COPY, plural } from "../copy";
import { go, href } from "../router";
import { begin, fromSession, type Live, reduce, rollback, type Step, userTurns } from "../session";
import { useCountdown } from "../useCountdown";
import { useVoice } from "../useVoice";
import { Icon } from "./Icon";
import { PhaseStrip } from "./PhaseStrip";
import { Report } from "./Report";
import { type ClockState, Scoreboard } from "./Scoreboard";
import { TurnCard } from "./TurnCard";

const AGENTS: { node: Step["node"]; name: string; idle: string }[] = [
  { node: "fact_check", name: "Fact-checker", idle: "Checks each claim you make" },
  { node: "opponent", name: "Opponent", idle: "Answers your last point" },
  { node: "judge", name: "Judge", idle: "Scores you at the bell" },
  { node: "coach", name: "Coach", idle: "Finds your three fixes" },
];

const reduceMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function Arena({ id, health }: { id: string; health: Health | null }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const draftRef = useRef("");
  const liveRef = useRef<Live | null>(null);
  const spokeThisTurn = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  draftRef.current = draft;
  liveRef.current = live;

  useEffect(() => {
    api
      .session(id)
      .then((s) => {
        setSession(s);
        setLive(fromSession(s));
      })
      .catch((err) => setLoadError(err instanceof ApiError && err.status === 404 ? "That bout doesn't exist any more." : "Couldn't load this bout."));
  }, [id]);

  const slot = live?.position.slot ?? null;
  const voice = useVoice((text) => {
    spokeThisTurn.current = true;
    setDraft((d) => (d.trim() ? `${d.trimEnd()} ${text}` : text));
  });

  const sendRef = useRef<(timedOut: boolean) => void>(() => {});
  const countdown = useCountdown(slot?.seconds ?? 60, () => sendRef.current(true));

  const run = useCallback(
    async (call: (onEvent: (e: DojoEvent) => void) => Promise<void>, restore?: string) => {
      const before = liveRef.current!;
      setLive(begin(before));
      let replied = false;
      let failed: string | null = null;
      try {
        await call((e) => {
          if (e.type === "reply") {
            replied = true;
            voice.speak(e.turn.text);
          }
          if (e.type === "error") failed = e.message;
          setLive((l) => (l ? reduce(l, e) : l));
        });
      } catch (err) {
        failed = err instanceof Error ? err.message : "The connection dropped.";
      }
      if (failed) {
        // Before the reply, the server rolled the turn back: put the words back in the box.
        if (!replied) {
          setLive((l) => (l ? rollback(l, before, failed!) : l));
          if (restore !== undefined) setDraft(restore);
        } else setLive((l) => (l ? { ...l, error: failed, busy: false } : l));
      }
    },
    [voice],
  );

  const send = useCallback(
    (timedOut: boolean) => {
      const l = liveRef.current;
      if (!l || l.busy || !l.position.slot) return;
      const text = draftRef.current.trim();
      if (!text && !timedOut) return;
      const spoken = voice.collect();
      const body: TurnBody = {
        text,
        input: spoken || spokeThisTurn.current ? "voice" : "typed",
        duration_s: Math.round(countdown.elapsed() * 10) / 10,
        talk_seconds: spoken?.talkSeconds ?? null,
        longest_pause_s: spoken?.longestPause ?? null,
        timed_out: timedOut,
      };
      spokeThisTurn.current = false;
      setDraft("");
      countdown.reset();
      setNotice(timedOut ? "Time. Your turn went in as it stood." : null);
      void run((onEvent) => api.turn(id, body, onEvent), text);
    },
    [countdown, id, run, voice],
  );
  sendRef.current = send;

  const finish = () => void run((onEvent) => api.finish(id, onEvent));

  // Follow the transcript as it grows.
  const lastLen = (live?.turns.length ?? 0) + (live?.streaming?.length ?? 0);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: reduceMotion() ? "auto" : "smooth" });
  }, [lastLen]);

  // Hand the floor back once the opponent finishes.
  const busy = live?.busy ?? false;
  useEffect(() => {
    if (!busy && live?.position.slot) inputRef.current?.focus({ preventScroll: true });
  }, [busy, live?.position.slot]);

  if (loadError)
    return (
      <div className="state state-error" role="alert">
        <h1>Bout not found</h1>
        <p>{loadError}</p>
        <a className="btn" href={href({ page: "home" })}>
          Back to the card
        </a>
      </div>
    );
  if (!session || !live)
    return (
      <div className="state" aria-busy="true">
        <div className="loader" aria-hidden="true" />
        <p>Loading the bout…</p>
      </div>
    );

  const copy = MODE_COPY[session.mode];
  const done = live.position.done;
  const finished = live.status === "finished";
  const yours = userTurns(live.turns);
  const opponentTalking = live.busy && live.streaming !== null;
  const clockState: ClockState = finished ? "final" : done || (live.busy && live.status === "judging") ? "judging" : opponentTalking ? "opponent" : countdown.started ? "running" : "armed";
  const streamingTurn: Turn | null =
    live.streaming !== null && slot
      ? {
          id: -1, idx: -1, speaker: "opponent", slot: slot.index, phase_id: slot.phase_id, phase_name: slot.phase_name, exchange: slot.exchange,
          text: live.streaming, input: "model", duration_s: null, limit_s: null, timed_out: false, delivery: null, flags: [], fact_check: null, created_at: "",
        }
      : null;
  const liveWords = wordCount(draft + " " + voice.interim);
  const liveFillers = totalFillers(countFillers(draft + " " + voice.interim));
  const livePace = voice.listening || spokeThisTurn.current ? wordsPerMinute(liveWords, countdown.elapsed()) : null;
  const usedRatio = slot ? Math.min(1, (slot.seconds - countdown.remaining) / slot.seconds) : 0;
  const canFinishEarly = !done && yours.length > 0 && !live.busy;
  const needsVerdict = done && !finished && !live.busy;

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      send(false);
    }
  };
  const toggleMic = () => {
    if (voice.listening) voice.stop();
    else {
      countdown.start();
      voice.start();
    }
  };

  const rematch = async () => {
    const s = await api.start({
      mode: session.mode,
      topic: session.topic,
      format_id: session.format_id,
      persona_id: session.persona_id,
      side: session.side ?? undefined,
      context: session.context,
      timers: Object.fromEntries(session.format.phases.map((p) => [p.id, p.seconds])),
    });
    go({ page: "bout", id: s.id });
  };

  return (
    <div className={`arena mode-${session.mode} ${done ? "is-over" : "is-live"}`}>
      <div className="arena-top">
        <Scoreboard
          session={session}
          slot={slot}
          remaining={countdown.remaining}
          clock={clockState}
          userTurns={yours.length}
          overall={live.scorecard?.overall ?? null}
        />
        <div className="strip-row">
          <PhaseStrip session={session} turn={live.position.turn} done={done} />
          <div className="arena-tools">
            {voice.canSpeak && (
              <button className="icon-btn" onClick={voice.toggleMute} aria-pressed={voice.muted} aria-label={voice.muted ? "Unmute the opponent" : "Mute the opponent"} title={voice.muted ? "Unmute the opponent" : "Mute the opponent"}>
                <Icon name={voice.muted ? "muted" : "speaker"} />
              </button>
            )}
            {canFinishEarly && (
              <button className="btn btn-ghost" onClick={finish}>
                End and score
              </button>
            )}
          </div>
        </div>
      </div>

      {done ? (
        <div className="arena-report">
          {live.error && (
            <div className="banner banner-error" role="alert">
              {live.error}
            </div>
          )}
          {needsVerdict && !live.scorecard ? (
            <div className="state">
              <p>The bout is over but the verdict never arrived.</p>
              <button className="btn btn-primary" onClick={finish}>
                Get the verdict
              </button>
            </div>
          ) : (
            <Report session={session} turns={live.turns} scorecard={live.scorecard} coaching={live.coaching} steps={live.steps} />
          )}
          {finished && (
            <div className="report-actions">
              <button className="btn btn-primary" onClick={() => void rematch()}>
                <Icon name="bell" /> Rematch
              </button>
              <a className="btn" href={href({ page: "record", mode: session.mode })}>
                <Icon name="chart" /> See your record
              </a>
              <a className="btn btn-ghost" href={href({ page: "setup", mode: session.mode })}>
                New {copy.name.toLowerCase()} bout
              </a>
            </div>
          )}
          <details className="transcript-full">
            <summary>Full transcript · {plural(live.turns.length, "turn")}</summary>
            <div className="transcript">
              {live.turns.map((t) => (
                <TurnCard key={t.id} turn={t} mode={session.mode} />
              ))}
            </div>
          </details>
        </div>
      ) : (
        <div className="arena-body">
          <section className="transcript-col" aria-label="Transcript">
            <div className="transcript" aria-live="polite" aria-relevant="additions">
              {live.turns.length === 0 && !streamingTurn && (
                <div className="floor">
                  <p className="kicker">Seconds out</p>
                  <p className="floor-title">The floor is yours.</p>
                  <p className="floor-guide">{slot?.guidance}</p>
                </div>
              )}
              {live.turns.map((t) => (
                <TurnCard key={t.id} turn={t} mode={session.mode} />
              ))}
              {streamingTurn && <TurnCard turn={streamingTurn} mode={session.mode} streaming />}
              <div ref={endRef} />
            </div>

            <form
              className={`composer ${voice.listening ? "is-listening" : ""}`}
              onSubmit={(e) => {
                e.preventDefault();
                send(false);
              }}
            >
              {(live.error || notice || voice.error) && (
                <p className={`composer-note ${live.error || voice.error ? "is-error" : ""}`} role="status">
                  {live.error ?? voice.error ?? notice}
                </p>
              )}
              <label htmlFor="turn" className="composer-label">
                <span>
                  Your {slot?.phase_name.toLowerCase()} {slot && slot.exchanges > 1 ? `(${slot.exchange} of ${slot.exchanges})` : ""}
                </span>
                <span className="composer-guide">{slot?.guidance}</span>
              </label>
              <div className="composer-row">
                <textarea
                  id="turn"
                  ref={inputRef}
                  className="input composer-input"
                  rows={3}
                  value={voice.interim ? `${draft}${draft ? " " : ""}${voice.interim}` : draft}
                  onChange={(e) => {
                    setDraft(e.target.value);
                    if (e.target.value.trim()) countdown.start();
                  }}
                  onKeyDown={onKey}
                  readOnly={voice.listening}
                  disabled={live.busy}
                  placeholder={live.busy ? `${copy.opponentLabel} is answering…` : voice.canListen ? "Speak or type your turn. The clock starts when you do." : "Type your turn. The clock starts when you do."}
                  aria-describedby="meter"
                />
                <div className="composer-actions">
                  {voice.canListen && (
                    <button
                      type="button"
                      className={`mic ${voice.listening ? "is-on" : ""}`}
                      onClick={toggleMic}
                      disabled={live.busy}
                      aria-pressed={voice.listening}
                      aria-label={voice.listening ? "Stop listening" : "Speak your turn"}
                    >
                      <Icon name={voice.listening ? "stop" : "mic"} size={26} />
                    </button>
                  )}
                  <button type="submit" className="btn btn-primary send" disabled={live.busy || !draft.trim()}>
                    Send <Icon name="send" />
                  </button>
                </div>
              </div>
              <div id="meter" className="meter" aria-live="off">
                <span className="meter-bar" aria-hidden="true">
                  <span style={{ transform: `scaleX(${usedRatio})` }} className={usedRatio > 0.85 ? "is-late" : ""} />
                </span>
                <span>{plural(liveWords, "word")}</span>
                {livePace !== null && <span>{Math.round(livePace)} wpm</span>}
                <span className={liveFillers ? "has-fillers" : ""}>{plural(liveFillers, "filler")}</span>
                <span className="meter-hint">{voice.listening ? "Listening…" : "Ctrl + Enter to send"}</span>
              </div>
            </form>
          </section>

          <aside className="ringside" aria-label="Ringside">
            <section className="ring-card">
              <h2 className="ring-title">Ringside</h2>
              <ul className="agents">
                {AGENTS.map((a) => {
                  const step = live.steps.find((s) => s.node === a.node);
                  const status = step?.status ?? "idle";
                  return (
                    <li key={a.node} className={`agent agent-${status}`}>
                      <span className="agent-dot" aria-hidden="true" />
                      <span className="agent-name">{a.name}</span>
                      <span className="agent-detail">
                        {status === "running" ? "working…" : status === "idle" ? a.idle : (step?.detail ?? status)}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <p className="muted small">
                {health?.fact_check === "web"
                  ? "Claims are checked with web search. Only pages it actually found are cited."
                  : "Claims are checked on the model's own knowledge, without web search. It never invents sources."}
              </p>
            </section>
            <section className="ring-card">
              <h2 className="ring-title">{copy.opponentLabel}</h2>
              <p className="ring-persona">{session.persona.name}</p>
              <p className="muted">{session.persona.style}</p>
            </section>
            {yours.at(-1)?.delivery && (
              <section className="ring-card">
                <h2 className="ring-title">Last turn</h2>
                <LastDelivery turn={yours.at(-1)!} />
              </section>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function LastDelivery({ turn }: { turn: Turn }) {
  const d = turn.delivery!;
  const tiles = [
    { label: "Pace", value: d.wpm !== null ? `${Math.round(d.wpm)}` : "-", unit: d.wpm !== null ? "wpm" : d.source === "typed" ? "typed" : "" },
    { label: "Fillers", value: `${d.filler_total}`, unit: `${d.fillers_per_100}/100w` },
    { label: "Talk time", value: `${Math.round(d.talk_ratio * 100)}`, unit: "% used" },
  ];
  const named = Object.entries(d.fillers).filter(([, n]) => n > 0);
  return (
    <>
      <dl className="tiles">
        {tiles.map((t) => (
          <div key={t.label}>
            <dt>{t.label}</dt>
            <dd>
              {t.value} <small>{t.unit}</small>
            </dd>
          </div>
        ))}
      </dl>
      {named.length > 0 && <p className="muted small">Fillers: {named.map(([w, n]) => `"${w}" ×${n}`).join(", ")}</p>}
      {d.longest_pause_s !== null && <p className="muted small">Longest pause {d.longest_pause_s}s</p>}
    </>
  );
}
