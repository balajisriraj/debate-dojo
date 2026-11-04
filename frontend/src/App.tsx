import { useEffect, useState } from "react";
import { api, type Catalog, type Health } from "./api";
import { Arena } from "./components/Arena";
import { Home } from "./components/Home";
import { Record } from "./components/Record";
import { Setup } from "./components/Setup";
import { href, useRoute } from "./router";

export function App() {
  const route = useRoute();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    Promise.all([api.catalog(), api.health()])
      .then(([c, h]) => {
        setCatalog(c);
        setHealth(h);
      })
      .catch(() => setError("The dojo's server isn't answering. Start the API and try again."));
  };
  useEffect(load, []);

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="brand" href={href({ page: "home" })} aria-label="DebateDojo home">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-word">
            Debate<b>Dojo</b>
          </span>
        </a>
        <nav aria-label="Main">
          <a href={href({ page: "home" })} aria-current={route.page === "home" ? "page" : undefined}>
            Spar
          </a>
          <a href={href({ page: "record", mode: "debate" })} aria-current={route.page === "record" ? "page" : undefined}>
            Record
          </a>
        </nav>
        {health && (
          <span className="engine" title={health.llm === "anthropic" ? `Claude (${health.model})` : "Scripted model, offline"}>
            <span className={`dot ${health.llm}`} aria-hidden="true" />
            {health.llm === "anthropic" ? "Claude" : "Scripted model"}
          </span>
        )}
      </header>
      <main id="main" className="main">
        {error ? (
          <div className="state state-error" role="alert">
            <h1>No signal</h1>
            <p>{error}</p>
            <button className="btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : !catalog ? (
          <div className="state" aria-busy="true">
            <div className="loader" aria-hidden="true" />
            <p>Setting up the ring…</p>
          </div>
        ) : route.page === "home" ? (
          <Home catalog={catalog} />
        ) : route.page === "setup" ? (
          <Setup key={route.mode} catalog={catalog} mode={route.mode} />
        ) : route.page === "bout" ? (
          <Arena key={route.id} id={route.id} health={health} />
        ) : (
          <Record key={route.mode} mode={route.mode} />
        )}
      </main>
    </div>
  );
}
