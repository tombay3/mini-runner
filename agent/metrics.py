"""Compact, best-effort measurements. JSON stores remain the gameplay record."""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4


SCHEMA = """
CREATE TABLE runs (
    id TEXT PRIMARY KEY, profile TEXT, model_id TEXT, api TEXT, gateway TEXT,
    gw_provider TEXT, gw_model TEXT, saved_at TEXT, result TEXT, reason TEXT,
    initial_gold INTEGER, final_gold INTEGER, wall_ms REAL,
    decisions INTEGER NOT NULL DEFAULT 0 CHECK (decisions >= 0)
);
CREATE TABLE model_calls (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    diverged INTEGER CHECK (diverged IN (0,1)),
    status TEXT NOT NULL, latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER,
    cached_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER
);
CREATE INDEX calls_run ON model_calls(run_id);
"""


def divergence(step):
    candidates = step.get("candidates") or []
    choice = next((c for c in candidates if c.get("id") == step["decision"].get("requestedId")), None)
    if choice is None:
        return None
    try:
        highest = max(c["score"] for c in candidates)
        action = choice["offeredAction"]
        return int(choice["score"] < highest and all(
            (c["offeredAction"]["keyCode"], c["offeredAction"]["ticks"]) !=
            (action["keyCode"], action["ticks"]) for c in candidates if c["score"] == highest))
    except (KeyError, TypeError, ValueError):
        return None


@contextmanager
def database(path: Path, *, readonly=False):
    """Initialize an empty database atomically. Reads never create files."""
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    uri = path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rwc")
    with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 and not readonly:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                # A concurrent initializer may have committed between the two reads.
                if db.execute("PRAGMA user_version").fetchone()[0] != 2:
                    raise ValueError("Unrecognized metrics database")
            else:
                # SQLite can return BUSY immediately when two new connections
                # both request WAL mode, even with a configured busy timeout.
                deadline = monotonic() + 0.25
                while True:
                    try:
                        db.execute("PRAGMA journal_mode=WAL").fetchone()
                        break
                    except sqlite3.OperationalError as exc:
                        if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY or monotonic() >= deadline:
                            raise
                        sleep(0.01)
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                        for statement in SCHEMA.split(";"):
                            if statement.strip():
                                db.execute(statement)
                        db.execute("PRAGMA user_version=2")
        elif version != 2:
            raise ValueError(f"Unsupported metrics schema {version}")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_calls'").fetchone():
            raise ValueError("Unsupported metrics layout: expected the two-table V2 schema")
        with db:
            yield db


def number(value):
    if type(value) in (int, float) and 0 <= value <= 2**53 and math.isfinite(value):
        return value
    return None


def label(value):
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def token_usage(usage):
    """Keep valid counters independently, within SQLite's signed integer range."""
    usage = usage if isinstance(usage, dict) else {}
    counts = {}
    for name in ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens"):
        value = usage.get(name)
        counts[name] = value if type(value) is int and 0 <= value <= 2**63 - 1 else None
    for detail, total in (("cachedInputTokens", "inputTokens"),
                          ("cacheWriteTokens", "inputTokens"), ("reasoningTokens", "outputTokens")):
        if counts[detail] is not None and counts[total] is not None and counts[detail] > counts[total]:
            counts[detail] = None
    return counts


class Measurement:
    def __init__(self, path, run_id, telemetry=None):
        self.path = path
        self.run_id = run_id
        self.data = telemetry if isinstance(telemetry, dict) else {}
        self.partial = self.data.get("partial") is True
        self.request_id = None
        self.skipped = False

    def write(self, operation):
        if self.skipped:
            return
        try:
            with database(self.path) as db:
                operation(db)
        except Exception as exc:
            self.partial = True
            logging.getLogger("loderunner.agent.metrics").warning("Metrics incomplete: %s", type(exc).__name__)

    def run(self, db, snapshot, attempts):
        gold = snapshot.get("gold") or {}
        db.execute("""INSERT INTO runs(id,initial_gold,decisions) VALUES(?,?,?)
            ON CONFLICT(id) DO UPDATE SET decisions=decisions+excluded.decisions""",
            (self.run_id, number(gold.get("remainingCount")), attempts))

    def begin(self, snapshot):
        self.skipped = bool(snapshot.get("godMode"))
        self.write(lambda db: self.run(db, snapshot, 1))

    def configure(self, model):
        from .llm_client import configured_gateway
        identity = (model.profile, model.transport_model,
                    "decisions" if model.profile == "openai-decisions" else "chat_completions",
                    configured_gateway(model))
        def update(db):
            changed = db.execute("""UPDATE runs SET profile=?,model_id=?,api=?,gateway=? WHERE id=?
                AND (profile IS NULL OR profile=?) AND (model_id IS NULL OR model_id=?)
                AND (api IS NULL OR api=?) AND (gateway IS NULL OR gateway=?)""",
                (*identity, self.run_id, *identity))
            if not changed.rowcount:
                raise ValueError("Run selector changed")
        self.write(update)

    def request_start(self):
        self.request_id = str(uuid4())
        self.write(lambda db: db.execute("INSERT INTO model_calls(id,run_id,status) VALUES(?,?,'pending')",
                                         (self.request_id, self.run_id)))
        self.request_time = monotonic()

    def request_end(self, metadata=None):
        latency = (monotonic() - self.request_time) * 1000
        def finish(db):
            m = metadata or {}
            u = token_usage(m.get("usage"))
            db.execute("""UPDATE model_calls SET status=?,latency_ms=?,input_tokens=?,output_tokens=?,
                cached_tokens=?,cache_write_tokens=?,reasoning_tokens=? WHERE id=?""", (
                m.get("status", "error"), latency, u.get("inputTokens"), u.get("outputTokens"),
                u.get("cachedInputTokens"), u.get("cacheWriteTokens"), u.get("reasoningTokens"), self.request_id))
            for field, value in (("gw_provider", m.get("servingProvider")), ("gw_model", m.get("resolvedModel"))):
                if value:
                    db.execute(f"""UPDATE runs SET {field}=CASE WHEN {field} IS NULL OR {field}=?
                        THEN ? ELSE 'Mixed' END WHERE id=?""", (value, value, self.run_id))
        self.write(finish)

    def issue(self, step):
        if self.request_id is not None:
            self.write(lambda db: db.execute("UPDATE model_calls SET diverged=? WHERE id=?",
                                             (divergence(step), self.request_id)))

    def finish(self, result, reason, snapshot, saved_at, god_mode=False):
        self.skipped = bool(god_mode or snapshot.get("godMode"))
        def update(db):
            self.run(db, snapshot, 0)
            gold = snapshot.get("gold") or {}
            db.execute("""UPDATE runs SET saved_at=?,result=?,reason=?,
                final_gold=?,wall_ms=COALESCE(wall_ms,?) WHERE id=?""",
                (saved_at, result, label(reason), number(gold.get("remainingCount", gold.get("remaining"))),
                 number(self.data.get("wallMs")), self.run_id))
        self.write(update)


def eligible_games(db):
    return db.execute("""
        WITH calls AS (
            SELECT q.run_id, q.status, q.latency_ms, q.diverged,
                   row_number() OVER (PARTITION BY q.run_id ORDER BY q.latency_ms) AS position,
                   count(*) OVER (PARTITION BY q.run_id) AS total,
                   count(q.latency_ms) OVER (PARTITION BY q.run_id) AS measured
            FROM model_calls q
        ), usage AS (
            SELECT run_id, count(*) AS calls,
                   count(diverged) AS scored_calls, sum(diverged) AS divergences,
                   max(CASE WHEN position=total-measured+(measured+1)/2 THEN latency_ms END) AS median_ms
            FROM calls GROUP BY run_id HAVING min(status='ok')=1
        )
        SELECT r.id,r.saved_at,r.profile,r.model_id,r.api,r.gateway,r.gw_provider,r.gw_model,r.result,
               r.initial_gold-r.final_gold AS gold,r.wall_ms,u.calls,u.scored_calls,u.divergences,u.median_ms,
               r.decisions
        FROM runs r JOIN usage u ON u.run_id=r.id
        WHERE r.saved_at IS NOT NULL AND (r.result='success' OR
            (r.result='failure' AND r.reason IN ('runner dead','runner_dead',
            'agent max playback time reached','agent safety step limit reached')))
        ORDER BY julianday(r.saved_at) DESC,r.id
    """).fetchall()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify","delete"])
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("AGENT_METRICS_PATH",
                        Path(__file__).resolve().parents[1]/"__data1/metrics.sqlite3")))
    parser.add_argument("--run", required=True, action="append")
    args = parser.parse_args()
    if args.command == "delete" and (len(args.run) != 1 or not args.db.is_file()):
        parser.error("delete requires one run ID and an existing database")
    with database(args.db, readonly=args.command == "verify") as db:
        if args.command == "delete":
            db.execute("DELETE FROM runs WHERE id=?", (args.run[0],))
        else:
            print(json.dumps([rid for rid in args.run if db.execute(
                "SELECT 1 FROM runs WHERE id=? AND saved_at IS NOT NULL", (rid,)).fetchone()]))
