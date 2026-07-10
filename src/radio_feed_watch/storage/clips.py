"""Clip file storage + SQLite metadata + retention."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radio_feed_watch.config import ClipsConfig
from radio_feed_watch.models import ClipRecord, SourceType, new_id, utcnow
from radio_feed_watch.sources.base import AudioClip

logger = logging.getLogger(__name__)


class ClipStore:
    def __init__(self, config: ClipsConfig, db_path: str | Path = "./data/db/radio_feed_watch.db"):
        self.config = config
        self.root = Path(config.dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clips (
                    clip_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    path TEXT NOT NULL,
                    duration_s REAL,
                    saved INTEGER NOT NULL DEFAULT 0,
                    text TEXT,
                    external_id TEXT,
                    bytes INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clips_ts ON clips(ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clips_saved ON clips(saved)"
            )

    def save_clip(self, clip: AudioClip, text: str | None = None) -> ClipRecord:
        if not self.config.enabled:
            raise RuntimeError("Clip storage is disabled")

        ts = clip.ts if clip.ts.tzinfo else clip.ts.replace(tzinfo=timezone.utc)
        clip_id = new_id(f"{clip.source_id}_")
        ext = "mp3"
        if "wav" in clip.content_type:
            ext = "wav"
        elif "ogg" in clip.content_type or "opus" in clip.content_type:
            ext = "opus"

        day = ts.strftime("%Y%m%d")
        dest_dir = self.root / clip.source_id / day
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{clip_id}.{ext}"
        path.write_bytes(clip.audio)

        record = ClipRecord(
            clip_id=clip_id,
            source_id=clip.source_id,
            source_type=clip.source_type,
            source_label=clip.source_label,
            ts=ts,
            path=str(path),
            duration_s=clip.duration_s,
            saved=False,
            text=text,
            external_id=clip.external_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clips (
                    clip_id, source_id, source_type, source_label, ts, path,
                    duration_s, saved, text, external_id, bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    record.clip_id,
                    record.source_id,
                    record.source_type.value,
                    record.source_label,
                    record.ts.isoformat(),
                    record.path,
                    record.duration_s,
                    record.text,
                    record.external_id,
                    len(clip.audio),
                ),
            )
        return record

    def set_saved(self, clip_id: str, saved: bool = True) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE clips SET saved = ? WHERE clip_id = ?", (1 if saved else 0, clip_id))

    def get(self, clip_id: str) -> ClipRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,)).fetchone()
        if not row:
            return None
        return ClipRecord(
            clip_id=row["clip_id"],
            source_id=row["source_id"],
            source_type=SourceType(row["source_type"]),
            source_label=row["source_label"],
            ts=datetime.fromisoformat(row["ts"]),
            path=row["path"],
            duration_s=row["duration_s"],
            saved=bool(row["saved"]),
            text=row["text"],
            external_id=row["external_id"],
        )

    def update_text(self, clip_id: str, text: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE clips SET text = ? WHERE clip_id = ?", (text, clip_id))

    def purge_expired(self) -> int:
        """Delete unpinned clips older than retention_days / over max_total_gb."""
        cutoff = utcnow() - timedelta(days=self.config.retention_days)
        deleted = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT clip_id, path FROM clips WHERE saved = 0 AND ts < ?",
                (cutoff.isoformat(),),
            ).fetchall()
            for row in rows:
                Path(row["path"]).unlink(missing_ok=True)
                conn.execute("DELETE FROM clips WHERE clip_id = ?", (row["clip_id"],))
                deleted += 1

            # secondary size cap: delete oldest unpinned until under budget
            max_bytes = int(self.config.max_total_gb * (1024**3))
            total = conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM clips").fetchone()[0]
            if total > max_bytes:
                victims = conn.execute(
                    "SELECT clip_id, path, bytes FROM clips WHERE saved = 0 ORDER BY ts ASC"
                ).fetchall()
                for row in victims:
                    if total <= max_bytes:
                        break
                    Path(row["path"]).unlink(missing_ok=True)
                    conn.execute("DELETE FROM clips WHERE clip_id = ?", (row["clip_id"],))
                    total -= row["bytes"] or 0
                    deleted += 1
        if deleted:
            logger.info("Purged %d expired/unpinned clip(s)", deleted)
        return deleted
