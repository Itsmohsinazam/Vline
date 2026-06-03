"""
VLINE – Database Layer
Stores every detected plate with timestamp, vehicle type, confidence, snapshot.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from config import DB_PATH


class VlineDatabase:
    """Thread-safe SQLite wrapper for VLINE detections."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_schema()

    # ── Connection management ─────────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return self._local.conn

    # ── Schema ────────────────────────────────────────────────────────────────
    def _init_schema(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS detections (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                plate         TEXT    NOT NULL,
                vehicle_type  TEXT    NOT NULL DEFAULT 'Unknown',
                confidence    REAL    NOT NULL DEFAULT 0.0,
                plate_score   REAL    NOT NULL DEFAULT 0.0,
                source        TEXT    NOT NULL DEFAULT 'camera',
                snapshot_path TEXT,
                region        TEXT,
                timestamp     TEXT    NOT NULL,
                date          TEXT    NOT NULL,
                time          TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_plate     ON detections(plate);
            CREATE INDEX IF NOT EXISTS idx_date      ON detections(date);
            CREATE INDEX IF NOT EXISTS idx_vtype     ON detections(vehicle_type);

            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                source     TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at   TEXT,
                total_detections INTEGER DEFAULT 0
            );
        """)
        conn.commit()

    # ── Write ─────────────────────────────────────────────────────────────────
    def add_detection(
        self,
        plate: str,
        vehicle_type: str,
        confidence: float,
        plate_score: float,
        source: str,
        snapshot_path: Optional[str] = None,
        region: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> int:
        now = timestamp or datetime.now()
        ts_str   = now.strftime("%Y-%m-%d %H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        conn = self._conn()
        with self._lock:
            cur = conn.execute(
                """INSERT INTO detections
                   (plate, vehicle_type, confidence, plate_score,
                    source, snapshot_path, region, timestamp, date, time)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (plate.upper(), vehicle_type, round(confidence, 4),
                 round(plate_score, 4), source, snapshot_path,
                 region, ts_str, date_str, time_str),
            )
            conn.commit()
        return cur.lastrowid

    def start_session(self, source: str) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO sessions (source, started_at) VALUES (?,?)",
            (source, now),
        )
        conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int, total: int):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn().execute(
            "UPDATE sessions SET ended_at=?, total_detections=? WHERE id=?",
            (now, total, session_id),
        )
        self._conn().commit()

    # ── Read ──────────────────────────────────────────────────────────────────
    def get_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            """SELECT * FROM detections ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = conn.execute(
            "SELECT COUNT(*) FROM detections WHERE date=?", (today,)
        ).fetchone()[0]

        by_type = conn.execute(
            """SELECT vehicle_type, COUNT(*) as cnt
               FROM detections GROUP BY vehicle_type ORDER BY cnt DESC"""
        ).fetchall()

        last_10 = conn.execute(
            """SELECT plate, vehicle_type, timestamp, source
               FROM detections ORDER BY id DESC LIMIT 10"""
        ).fetchall()

        unique_plates = conn.execute(
            "SELECT COUNT(DISTINCT plate) FROM detections"
        ).fetchone()[0]

        return {
            "total":        total,
            "today":        today_count,
            "unique_plates":unique_plates,
            "by_type":      {r["vehicle_type"]: r["cnt"] for r in by_type},
            "last_10":      [dict(r) for r in last_10],
        }

    def search(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        q = f"%{query.upper()}%"
        rows = self._conn().execute(
            """SELECT * FROM detections
               WHERE plate LIKE ? OR vehicle_type LIKE ?
               ORDER BY id DESC LIMIT ?""",
            (q, q, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM detections WHERE date=? ORDER BY id DESC",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_detection(self, detection_id: int):
        with self._lock:
            self._conn().execute("DELETE FROM detections WHERE id=?", (detection_id,))
            self._conn().commit()

    def clear_all(self):
        with self._lock:
            self._conn().execute("DELETE FROM detections")
            self._conn().execute("DELETE FROM sessions")
            self._conn().commit()
