"""SQLite memory: the full debate log per session, and the scores that feed the progress view.

Every turn is kept with its phase, its timings, its fact-check flags and its delivery metrics,
so a session can be replayed exactly and the judge always sees the real record.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    mode        TEXT NOT NULL,
    format_id   TEXT NOT NULL,
    format      TEXT NOT NULL,           -- the format as run, with the user's timers applied
    topic       TEXT NOT NULL,
    side        TEXT,
    persona_id  TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'live',  -- live | judging | finished
    overall     REAL,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    speaker     TEXT NOT NULL,           -- user | opponent
    slot        INTEGER NOT NULL,
    phase_id    TEXT NOT NULL,
    phase_name  TEXT NOT NULL,
    exchange    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    input       TEXT NOT NULL,           -- voice | typed | model
    duration_s  REAL,
    limit_s     INTEGER,
    timed_out   INTEGER NOT NULL DEFAULT 0,
    delivery    TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (session_id, idx)
);
CREATE TABLE IF NOT EXISTS flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id         INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    claim           TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    evidence_needed TEXT NOT NULL,
    method          TEXT NOT NULL,       -- knowledge | web
    sources         TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS fact_checks (
    turn_id  INTEGER PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
    checked  INTEGER NOT NULL,
    method   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    scorecard  TEXT NOT NULL,
    coaching   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    mode       TEXT NOT NULL,
    criterion  TEXT NOT NULL,
    score      INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, criterion)
);
CREATE INDEX IF NOT EXISTS turns_by_session ON turns(session_id, idx);
CREATE INDEX IF NOT EXISTS scores_by_mode ON scores(mode, created_at);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    # ── sessions ──
    def create_session(
        self,
        *,
        id: str,
        mode: str,
        format_id: str,
        format: dict,
        topic: str,
        side: str | None,
        persona_id: str,
        context: str,
    ) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO sessions (id, mode, format_id, format, topic, side, persona_id, context, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (id, mode, format_id, json.dumps(format), topic, side, persona_id, context, now()),
            )

    def session(self, session_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        session = self._session_row(row)
        session["turns"] = self.turns(session_id)
        report = self.db.execute("SELECT * FROM reports WHERE session_id = ?", (session_id,)).fetchone()
        session["report"] = (
            {"scorecard": json.loads(report["scorecard"]), "coaching": json.loads(report["coaching"])}
            if report
            else None
        )
        return session

    def sessions(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id AND t.speaker = 'user') AS user_turns"
            " FROM sessions s ORDER BY s.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            s = self._session_row(row)
            s["user_turns"] = row["user_turns"]
            s.pop("format")
            out.append(s)
        return out

    def set_status(self, session_id: str, status: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))

    def delete_session(self, session_id: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount > 0

    @staticmethod
    def _session_row(row: sqlite3.Row) -> dict:
        s = dict(row)
        s["format"] = json.loads(s["format"])
        return s

    # ── turns ──
    def add_turn(
        self,
        session_id: str,
        *,
        speaker: str,
        slot: dict,
        text: str,
        input: str,
        duration_s: float | None = None,
        limit_s: int | None = None,
        timed_out: bool = False,
        delivery: dict | None = None,
    ) -> dict:
        with self.lock, self.db:
            (idx,) = self.db.execute(
                "SELECT COALESCE(MAX(idx), -1) + 1 FROM turns WHERE session_id = ?", (session_id,)
            ).fetchone()
            cur = self.db.execute(
                "INSERT INTO turns (session_id, idx, speaker, slot, phase_id, phase_name, exchange, text, input,"
                " duration_s, limit_s, timed_out, delivery, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    idx,
                    speaker,
                    slot["index"],
                    slot["phase_id"],
                    slot["phase_name"],
                    slot["exchange"],
                    text,
                    input,
                    duration_s,
                    limit_s,
                    int(timed_out),
                    json.dumps(delivery) if delivery else None,
                    now(),
                ),
            )
        return self.turn(cur.lastrowid)

    def turn(self, turn_id: int) -> dict:
        row = self.db.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        return self._turn_row(
            row, self._flags_for([turn_id]).get(turn_id, []), self._checks_for([turn_id]).get(turn_id)
        )

    def turns(self, session_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM turns WHERE session_id = ? ORDER BY idx", (session_id,)).fetchall()
        ids = [r["id"] for r in rows]
        flags, checks = self._flags_for(ids), self._checks_for(ids)
        return [self._turn_row(r, flags.get(r["id"], []), checks.get(r["id"])) for r in rows]

    def delete_turn(self, turn_id: int) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM turns WHERE id = ?", (turn_id,))

    def user_turn_count(self, session_id: str) -> int:
        (n,) = self.db.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id = ? AND speaker = 'user'", (session_id,)
        ).fetchone()
        return n

    @staticmethod
    def _turn_row(row: sqlite3.Row, flags: list[dict], check: dict | None) -> dict:
        t = dict(row)
        t["timed_out"] = bool(t["timed_out"])
        t["delivery"] = json.loads(t["delivery"]) if t["delivery"] else None
        t["flags"] = flags
        t["fact_check"] = check
        return t

    # ── fact-check flags ──
    def add_fact_check(self, turn_id: int, *, checked: int, method: str, flags: list[dict]) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO fact_checks (turn_id, checked, method) VALUES (?, ?, ?)",
                (turn_id, checked, method),
            )
            self.db.executemany(
                "INSERT INTO flags (turn_id, claim, verdict, reason, evidence_needed, method, sources)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        turn_id,
                        f["claim"],
                        f["verdict"],
                        f["reason"],
                        f["evidence_needed"],
                        method,
                        json.dumps(f.get("sources", [])),
                    )
                    for f in flags
                ],
            )

    def _flags_for(self, turn_ids: list[int]) -> dict[int, list[dict]]:
        if not turn_ids:
            return {}
        marks = ",".join("?" * len(turn_ids))
        out: dict[int, list[dict]] = {}
        for r in self.db.execute(f"SELECT * FROM flags WHERE turn_id IN ({marks}) ORDER BY id", turn_ids):
            f = dict(r)
            f["sources"] = json.loads(f["sources"])
            out.setdefault(f.pop("turn_id"), []).append(f)
        return out

    def _checks_for(self, turn_ids: list[int]) -> dict[int, dict]:
        if not turn_ids:
            return {}
        marks = ",".join("?" * len(turn_ids))
        rows = self.db.execute(f"SELECT * FROM fact_checks WHERE turn_id IN ({marks})", turn_ids)
        return {r["turn_id"]: {"checked": r["checked"], "method": r["method"]} for r in rows}

    # ── reports and progress ──
    def save_report(self, session_id: str, mode: str, scorecard: dict, coaching: dict) -> None:
        stamp = now()
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO reports (session_id, scorecard, coaching, created_at) VALUES (?, ?, ?, ?)",
                (session_id, json.dumps(scorecard), json.dumps(coaching), stamp),
            )
            self.db.execute("DELETE FROM scores WHERE session_id = ?", (session_id,))
            self.db.executemany(
                "INSERT INTO scores (session_id, mode, criterion, score, created_at) VALUES (?, ?, ?, ?, ?)",
                [(session_id, mode, s["criterion"], s["score"], stamp) for s in scorecard["scores"]],
            )
            self.db.execute(
                "UPDATE sessions SET status = 'finished', overall = ?, finished_at = ? WHERE id = ?",
                (scorecard["overall"], stamp, session_id),
            )

    def progress(self, mode: str) -> list[dict]:
        """Finished sessions in a mode, oldest first, each with its score per criterion."""
        rows = self.db.execute(
            "SELECT s.id, s.topic, s.format_id, s.overall, s.finished_at, sc.criterion, sc.score"
            " FROM sessions s JOIN scores sc ON sc.session_id = s.id"
            " WHERE s.mode = ? AND s.status = 'finished' ORDER BY s.finished_at, s.id",
            (mode,),
        ).fetchall()
        sessions: dict[str, dict] = {}
        for r in rows:
            s = sessions.setdefault(
                r["id"],
                {
                    "id": r["id"],
                    "topic": r["topic"],
                    "format_id": r["format_id"],
                    "overall": r["overall"],
                    "finished_at": r["finished_at"],
                    "scores": {},
                },
            )
            s["scores"][r["criterion"]] = r["score"]
        return list(sessions.values())
