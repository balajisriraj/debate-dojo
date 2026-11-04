import { useEffect, useState } from "react";
import { api, type Mode, type Progress } from "../api";
import { MODE_COPY, plural, when } from "../copy";
import { href } from "../router";
import { Icon } from "./Icon";

const MODES: Mode[] = ["debate", "meeting", "sales"];

type Point = { x: number; y: number; label: string; value: number; id: string };

/** One series per panel, so the line needs no legend: the panel title names it. */
function Spark({ title, points, max, big = false }: { title: string; points: Point[]; max: number; big?: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  // The viewBox matches the rendered size at 1920 wide, so ticks keep their real size.
  const w = big ? 1520 : 300;
  const h = big ? 190 : 120;
  const pad = { l: big ? 40 : 28, r: 16, t: 16, b: big ? 30 : 22 };
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const x = (i: number) => pad.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const ticks = big ? [0, 25, 50, 75, 100] : [0, 5, 10];
  const last = points.at(-1);
  const first = points[0];
  const change = last && first && points.length > 1 ? last.value - first.value : null;
  const shown = hover ?? points.length - 1;

  return (
    <figure className={`spark ${big ? "spark-big" : ""}`}>
      <figcaption>
        <span className="spark-title">{title}</span>
        {last && (
          <span className="spark-last">
            {last.value}
            <small>/{max}</small>
            {change !== null && change !== 0 && (
              <span className={`delta ${change > 0 ? "up" : "down"}`}>
                {change > 0 ? "+" : ""}
                {change}
              </span>
            )}
          </span>
        )}
      </figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${title}: ${points.map((p) => p.value).join(", ")}`} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid" x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} />
            <text className="tick" x={pad.l - 8} y={y(t) + 4} textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        {points.length > 1 && <path className="line" d={path} />}
        {points.map((p, i) => (
          <g key={p.id}>
            <circle className={`dot ${i === points.length - 1 ? "dot-last" : ""} ${hover === i ? "dot-hover" : ""}`} cx={x(i)} cy={y(p.value)} r={big ? 6 : 4.5} />
            {/* A hit target bigger than the mark. */}
            <rect
              className="hit"
              x={x(i) - Math.max(10, iw / Math.max(1, points.length) / 2)}
              y={pad.t}
              width={Math.max(20, iw / Math.max(1, points.length))}
              height={ih}
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              tabIndex={big ? 0 : -1}
              aria-label={`${p.label}: ${p.value}`}
            />
          </g>
        ))}
        {big && points.length > 0 && (
          <text className="tick" x={x(0)} y={h - 8} textAnchor={points.length === 1 ? "middle" : "start"}>
            Bout 1
          </text>
        )}
        {big && points.length > 1 && (
          <text className="tick" x={x(points.length - 1)} y={h - 8} textAnchor="end">
            Bout {points.length}
          </text>
        )}
      </svg>
      {big && points[shown] && (
        <p className="spark-tip" aria-live="polite">
          <b>{points[shown].value}</b> · {points[shown].label}
        </p>
      )}
    </figure>
  );
}

export function Record({ mode }: { mode: Mode }) {
  const [data, setData] = useState<Progress | null>(null);
  const [error, setError] = useState(false);
  const [table, setTable] = useState(false);

  useEffect(() => {
    setData(null);
    setError(false);
    api.progress(mode).then(setData).catch(() => setError(true));
  }, [mode]);

  const sessions = data?.sessions ?? [];
  const best = sessions.length ? Math.max(...sessions.map((s) => s.overall)) : null;
  const overallPoints: Point[] = sessions.map((s, i) => ({ x: i, y: s.overall, value: Math.round(s.overall), label: `${when(s.finished_at)}, ${s.topic}`, id: s.id }));

  return (
    <div className="record">
      <header className="record-head">
        <div>
          <p className="kicker">Fight record</p>
          <h1 className="display display-md">Your record</h1>
          <p className="lede">Every bout's scores, criterion by criterion. This is where you see whether practice is working.</p>
        </div>
        <div className="record-controls">
          {sessions.length > 0 && (
            <button className="btn btn-ghost" onClick={() => setTable((t) => !t)} aria-pressed={table}>
              {table ? "Show charts" : "Show as a table"}
            </button>
          )}
        <div className="tabs" role="tablist" aria-label="Mode">
          {MODES.map((m) => (
            <a key={m} role="tab" aria-selected={m === mode} className={`tab ${m === mode ? "is-on" : ""}`} href={href({ page: "record", mode: m })}>
              {MODE_COPY[m].name}
            </a>
          ))}
        </div>
        </div>
      </header>

      {error ? (
        <div className="state state-error" role="alert">
          <p>Couldn't load your record.</p>
        </div>
      ) : !data ? (
        <div className="state" aria-busy="true">
          <div className="loader" aria-hidden="true" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="empty empty-big">
          <p className="floor-title">No {MODE_COPY[mode].name.toLowerCase()} bouts on record yet.</p>
          <p className="muted">Finish a bout and its scorecard lands here.</p>
          <a className="btn btn-primary" href={href({ page: "setup", mode })}>
            <Icon name="bell" /> Start one
          </a>
        </div>
      ) : (
        <>
          <dl className="record-stats">
            <div>
              <dt>Bouts</dt>
              <dd>{sessions.length}</dd>
            </div>
            <div>
              <dt>Latest</dt>
              <dd>{Math.round(sessions.at(-1)!.overall)}</dd>
            </div>
            <div>
              <dt>Best</dt>
              <dd>{Math.round(best!)}</dd>
            </div>
            <div>
              <dt>Since bout 1</dt>
              <dd>{sessions.length > 1 ? `${sessions.at(-1)!.overall - sessions[0].overall >= 0 ? "+" : ""}${Math.round(sessions.at(-1)!.overall - sessions[0].overall)}` : "-"}</dd>
            </div>
          </dl>

          {table ? (
            <div className="table-wrap">
              <table className="record-table">
                <caption className="sr-only">Scores per bout</caption>
                <thead>
                  <tr>
                    <th scope="col">Bout</th>
                    <th scope="col">Topic</th>
                    {data.rubric.map((c) => (
                      <th key={c.id} scope="col">
                        {c.name}
                      </th>
                    ))}
                    <th scope="col">Overall</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s, i) => (
                    <tr key={s.id}>
                      <td>
                        <a href={href({ page: "bout", id: s.id })}>{i + 1}</a>
                      </td>
                      <td>{s.topic}</td>
                      {data.rubric.map((c) => (
                        <td key={c.id}>{s.scores[c.id] ?? "-"}</td>
                      ))}
                      <td>
                        <b>{Math.round(s.overall)}</b>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <>
              <section className="panel chart-panel" aria-label="Overall score per bout">
                <Spark title="Overall" points={overallPoints} max={100} big />
              </section>
              <section className="multiples" aria-label="Scores per criterion">
                {data.rubric.map((c) => (
                  <div className="panel" key={c.id}>
                    <Spark
                      title={c.name}
                      max={10}
                      points={sessions
                        .filter((s) => s.scores[c.id] !== undefined)
                        .map((s, i) => ({ x: i, y: s.scores[c.id], value: s.scores[c.id], label: s.topic, id: s.id }))}
                    />
                  </div>
                ))}
              </section>
            </>
          )}

          <section className="bouts">
            <h2 className="section-title">{plural(sessions.length, "bout")}</h2>
            <ul className="bout-list">
              {[...sessions].reverse().map((s) => (
                <li key={s.id}>
                  <a href={href({ page: "bout", id: s.id })}>
                    <span className="bout-topic">{s.topic}</span>
                    <span className="bout-meta">{when(s.finished_at)}</span>
                    <span className="bout-result">
                      <b>{Math.round(s.overall)}</b>
                      <small>/100</small>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
