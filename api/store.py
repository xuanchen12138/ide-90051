"""Small single-process SQLite repository; no external credentials persisted."""
import hashlib
import json
import sqlite3
from pathlib import Path

from domain.models import SensorReading, iso, utc_now


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS readings (id TEXT PRIMARY KEY, observed_at TEXT NOT NULL,
              source TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_run_kind ON events(run_id,kind,id);
            CREATE INDEX IF NOT EXISTS readings_source_time ON readings(source,observed_at);
        """)
        self.connection.commit()

    def put_reading(self, reading: SensorReading) -> str:
        data = reading.model_dump(mode="json")
        identity = dict(data)
        identity.pop("receivedAt", None)
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        existing = self.connection.execute("SELECT fingerprint FROM readings WHERE id = ?", (str(reading.readingId),)).fetchone()
        if existing:
            return "duplicate" if existing["fingerprint"] == fingerprint else "conflict"
        self.connection.execute("INSERT INTO readings VALUES (?, ?, ?, ?, ?)",
                                (str(reading.readingId), iso(reading.observedAt), reading.source, fingerprint, json.dumps(data)))
        self.connection.commit()
        return "accepted"

    def latest_physical(self, site_id: str) -> SensorReading | None:
        rows = self.connection.execute("SELECT payload FROM readings WHERE source = 'physical' ORDER BY observed_at DESC LIMIT 100")
        for row in rows:
            reading = SensorReading.model_validate_json(row["payload"])
            if reading.siteId == site_id:
                return reading
        return None

    def get_reading(self, reading_id: str) -> dict | None:
        row = self.connection.execute("SELECT payload FROM readings WHERE id = ?", (reading_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def event(self, run_id: str, kind: str, payload: dict, now=None) -> dict:
        created = iso(now or utc_now())
        cursor = self.connection.execute("INSERT INTO events(run_id,created_at,kind,payload) VALUES(?,?,?,?)", (run_id, created, kind, json.dumps(payload)))
        self.connection.commit()
        return {"id": cursor.lastrowid, "runId": run_id, "at": created, "type": kind, **payload}

    def events(self, run_id: str | None = None, limit: int | None = None, exclude: tuple[str, ...] = ()) -> list[dict]:
        sql = "SELECT * FROM events"
        args: list = []
        if run_id:
            sql += " WHERE run_id = ?"
            args.append(run_id)
        if exclude:
            sql += (" AND " if run_id else " WHERE ") + "kind NOT IN (" + ",".join("?" for _ in exclude) + ")"
            args.extend(exclude)
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        rows = self.connection.execute(sql, args).fetchall()
        return [{"id": row["id"], "runId": row["run_id"], "at": row["created_at"], "type": row["kind"], **json.loads(row["payload"])} for row in reversed(rows)]

    def evaluation(self, reading_id: str) -> dict | None:
        row = self.connection.execute("SELECT run_id,payload FROM events WHERE kind = 'reading-evaluated' AND json_extract(payload, '$.readingId') = ? ORDER BY id DESC LIMIT 1", (reading_id,)).fetchone()
        return {"runId": row["run_id"], **json.loads(row["payload"])} if row else None

    def has_render(self, reading_id: str) -> bool:
        return self.connection.execute("SELECT 1 FROM events WHERE kind = 'browser-render' AND json_extract(payload, '$.readingId') = ? LIMIT 1", (reading_id,)).fetchone() is not None

    def cache(self, key: str, value: dict | None = None) -> dict | None:
        if value is not None:
            self.connection.execute("INSERT OR REPLACE INTO cache VALUES(?, ?)", (key, json.dumps(value)))
            self.connection.commit()
            return value
        row = self.connection.execute("SELECT payload FROM cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def close(self):
        self.connection.close()
