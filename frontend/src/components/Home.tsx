import { useEffect, useState } from "react";
import { api, type Catalog, type Mode, type SessionSummary } from "../api";
import { MODE_COPY, when } from "../copy";
import { href } from "../router";
import { Icon } from "./Icon";

const ORDER: Mode[] = ["debate", "meeting", "sales"];

export function Home({ catalog }: { catalog: Catalog }) {
  const [recent, setRecent] = useState<SessionSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.sessions().then(setRecent).catch(() => setFailed(true));
  }, []);

  return (
    <div className="home">
      <section className="hero">
        <p className="kicker">Tonight's card</p>
        <h1 className="display">
          Spar with an AI
          <br />
          that <em>argues back.</em>
        </h1>
        <p className="lede">
          Argue it out against the clock, out loud or typed. A fact-checker flags your shaky claims as you go, then the judges
          score you on a rubric and a coach shows you what to fix.
        </p>
      </section>

      <section aria-labelledby="pick" className="cards-section">
        <h2 id="pick" className="section-title">
          Pick your fight
        </h2>
        <div className="mode-cards">
          {ORDER.map((mode, i) => {
            const copy = MODE_COPY[mode];
            const formats = catalog.modes.find((m) => m.id === mode)?.formats ?? [];
            return (
              <a key={mode} className={`mode-card mode-${mode}`} href={href({ page: "setup", mode })}>
                <span className="bout-no">Bout {i + 1}</span>
                <span className="mode-name">{copy.name}</span>
                <span className="mode-card-title">{copy.card}</span>
                <span className="mode-blurb">{copy.blurb}</span>
                <span className="mode-formats">{formats.map((f) => f.name).join(" · ")}</span>
                <span className="mode-go">
                  Step in <Icon name="send" size={18} />
                </span>
              </a>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="recent" className="recent">
        <div className="section-head">
          <h2 id="recent" className="section-title">
            Recent bouts
          </h2>
          <a className="link" href={href({ page: "record", mode: "debate" })}>
            <Icon name="chart" size={18} /> Your record
          </a>
        </div>
        {failed ? (
          <p className="muted">Couldn't load your recent bouts.</p>
        ) : recent === null ? (
          <div className="skeleton-list" aria-busy="true" aria-label="Loading recent bouts">
            <span />
            <span />
          </div>
        ) : recent.length === 0 ? (
          <div className="empty">
            <p>No bouts yet. Your first one takes about five minutes.</p>
          </div>
        ) : (
          <ul className="bout-list">
            {recent.slice(0, 6).map((s) => (
              <li key={s.id}>
                <a href={href({ page: "bout", id: s.id })}>
                  <span className={`pill pill-${s.mode}`}>{MODE_COPY[s.mode].name}</span>
                  <span className="bout-topic">{s.topic}</span>
                  <span className="bout-meta">{when(s.created_at)}</span>
                  <span className="bout-result">
                    {s.status === "finished" && s.overall !== null ? (
                      <>
                        <b>{Math.round(s.overall)}</b>
                        <small>/100</small>
                      </>
                    ) : (
                      <span className="pill pill-live">{s.status === "live" ? "In progress" : "Awaiting verdict"}</span>
                    )}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
