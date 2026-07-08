from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .storage import AppPaths, classify_file, copy_attachment


def parse_tags(tags: str) -> list[str]:
    normalized = tags.replace("，", ",").replace("、", ",")
    return [tag.strip() for tag in normalized.split(",") if tag.strip()]


@dataclass
class Entry:
    id: int
    title: str
    practice_type: str
    practice_date: str
    start_time: str
    end_time: str
    duration_minutes: int
    note: str
    tags: str
    created_at: str
    updated_at: str


@dataclass
class Attachment:
    id: int
    entry_id: int
    original_name: str
    stored_path: str
    kind: str
    size: int
    created_at: str
    position: int = 0


@dataclass
class TimeSegment:
    id: int
    entry_id: int
    start_time: str
    end_time: str
    duration_minutes: int
    position: int


class JournalRepository:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.paths.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.paths.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        with closing(self.connect()) as conn:
            with conn:
                yield conn

    def init_db(self) -> None:
        with self.session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    practice_type TEXT NOT NULL,
                    practice_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS time_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(practice_date DESC);
                CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(practice_type);
                CREATE INDEX IF NOT EXISTS idx_attachments_entry ON attachments(entry_id, position);
                CREATE INDEX IF NOT EXISTS idx_time_segments_entry ON time_segments(entry_id, position);
                """
            )
            self._ensure_column(conn, "attachments", "position", "INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE attachments SET position = id WHERE position = 0")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_entry(
        self,
        title: str,
        practice_type: str,
        practice_date: str,
        start_time: str,
        end_time: str,
        duration_minutes: int,
        note: str,
        tags: str,
        time_segments: list[tuple[str, str, int]] | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.session() as conn:
            cur = conn.execute(
                """
                INSERT INTO entries (
                    title, practice_type, practice_date, start_time, end_time,
                    duration_minutes, note, tags, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title.strip() or "未命名练习",
                    practice_type.strip() or "其他",
                    practice_date,
                    start_time,
                    end_time,
                    max(0, int(duration_minutes)),
                    note.strip(),
                    tags.strip(),
                    now,
                    now,
                ),
            )
            entry_id = int(cur.lastrowid)
            self._replace_time_segments(conn, entry_id, time_segments or [])
            return entry_id

    def update_entry(
        self,
        entry_id: int,
        title: str,
        practice_type: str,
        practice_date: str,
        start_time: str,
        end_time: str,
        duration_minutes: int,
        note: str,
        tags: str,
        time_segments: list[tuple[str, str, int]] | None = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.session() as conn:
            conn.execute(
                """
                UPDATE entries
                SET title = ?, practice_type = ?, practice_date = ?, start_time = ?,
                    end_time = ?, duration_minutes = ?, note = ?, tags = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    title.strip() or "未命名练习",
                    practice_type.strip() or "其他",
                    practice_date,
                    start_time,
                    end_time,
                    max(0, int(duration_minutes)),
                    note.strip(),
                    tags.strip(),
                    now,
                    entry_id,
                ),
            )
            if time_segments is not None:
                self._replace_time_segments(conn, entry_id, time_segments)

    def delete_entry(self, entry_id: int) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))

    def add_attachments(self, entry_id: int, files: Iterable[str | Path], entry_date: str) -> list[Attachment]:
        created: list[Attachment] = []
        now = datetime.now().isoformat(timespec="seconds")
        with self.session() as conn:
            next_position = int(
                conn.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 AS next_position FROM attachments WHERE entry_id = ?",
                    (entry_id,),
                ).fetchone()["next_position"]
            )
            for source in files:
                src = Path(source)
                stored = copy_attachment(src, self.paths, entry_date)
                kind = classify_file(stored)
                cur = conn.execute(
                    """
                    INSERT INTO attachments (
                        entry_id, original_name, stored_path, kind, size, created_at, position
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entry_id, src.name, str(stored), kind, stored.stat().st_size, now, next_position),
                )
                created.append(
                    Attachment(
                        id=int(cur.lastrowid),
                        entry_id=entry_id,
                        original_name=src.name,
                        stored_path=str(stored),
                        kind=kind,
                        size=stored.stat().st_size,
                        created_at=now,
                        position=next_position,
                    )
                )
                next_position += 1
        return created

    def list_entries(
        self,
        search: str = "",
        practice_type: str = "",
        date_text: str = "",
        tag_filter: str = "",
    ) -> list[Entry]:
        clauses: list[str] = []
        params: list[str] = []

        if search.strip():
            clauses.append("(title LIKE ? OR note LIKE ? OR tags LIKE ?)")
            like = f"%{search.strip()}%"
            params.extend([like, like, like])
        if practice_type.strip() and practice_type.strip() != "全部":
            clauses.append("practice_type = ?")
            params.append(practice_type.strip())
        if date_text.strip():
            clauses.append("practice_date = ?")
            params.append(date_text.strip())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.session() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM entries
                {where}
                ORDER BY practice_date DESC, start_time DESC, id DESC
                """,
                params,
            ).fetchall()
        entries = [Entry(**dict(row)) for row in rows]
        if tag_filter.strip() and tag_filter.strip() != "全部标签":
            selected_tag = tag_filter.strip()
            entries = [entry for entry in entries if selected_tag in parse_tags(entry.tags)]
        return entries

    def get_entry(self, entry_id: int) -> Entry | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return Entry(**dict(row)) if row else None

    def list_attachments(self, entry_id: int) -> list[Attachment]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE entry_id = ? ORDER BY position, id",
                (entry_id,),
            ).fetchall()
        return [Attachment(**dict(row)) for row in rows]

    def get_attachment(self, attachment_id: int) -> Attachment | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        return Attachment(**dict(row)) if row else None

    def rename_attachment(self, attachment_id: int, original_name: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE attachments SET original_name = ? WHERE id = ?",
                (original_name.strip() or "未命名附件", attachment_id),
            )

    def delete_attachment(self, attachment_id: int, delete_file: bool = True) -> Attachment | None:
        attachment = self.get_attachment(attachment_id)
        if not attachment:
            return None
        with self.session() as conn:
            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        if delete_file:
            try:
                Path(attachment.stored_path).unlink(missing_ok=True)
            except OSError:
                pass
        return attachment

    def set_attachment_order(self, entry_id: int, attachment_ids: list[int]) -> None:
        with self.session() as conn:
            for position, attachment_id in enumerate(attachment_ids, start=1):
                conn.execute(
                    "UPDATE attachments SET position = ? WHERE id = ? AND entry_id = ?",
                    (position, attachment_id, entry_id),
                )

    def list_time_segments(self, entry_id: int) -> list[TimeSegment]:
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM time_segments
                WHERE entry_id = ?
                ORDER BY position, id
                """,
                (entry_id,),
            ).fetchall()
        return [TimeSegment(**dict(row)) for row in rows]

    def replace_time_segments(self, entry_id: int, segments: list[tuple[str, str, int]]) -> None:
        with self.session() as conn:
            self._replace_time_segments(conn, entry_id, segments)

    def _replace_time_segments(
        self,
        conn: sqlite3.Connection,
        entry_id: int,
        segments: list[tuple[str, str, int]],
    ) -> None:
        conn.execute("DELETE FROM time_segments WHERE entry_id = ?", (entry_id,))
        for position, (start_time, end_time, duration_minutes) in enumerate(segments):
            conn.execute(
                """
                INSERT INTO time_segments (
                    entry_id, start_time, end_time, duration_minutes, position
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (entry_id, start_time, end_time, max(0, int(duration_minutes)), position),
            )

    def list_types(self) -> list[str]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT DISTINCT practice_type FROM entries ORDER BY practice_type"
            ).fetchall()
        return [str(row["practice_type"]) for row in rows if row["practice_type"]]

    def list_tags(self) -> list[str]:
        with self.session() as conn:
            rows = conn.execute("SELECT tags FROM entries WHERE tags != ''").fetchall()
        tags: set[str] = set()
        for row in rows:
            tags.update(parse_tags(str(row["tags"])))
        return sorted(tags)

    def stats(self) -> dict[str, object]:
        with self.session() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes FROM entries"
            ).fetchone()
            month = conn.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes
                FROM entries
                WHERE strftime('%Y-%m', practice_date) = strftime('%Y-%m', 'now', 'localtime')
                """
            ).fetchone()
            week = conn.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes
                FROM entries
                WHERE date(practice_date) >= date('now', 'localtime', '-6 days')
                """
            ).fetchone()
            by_type = conn.execute(
                """
                SELECT practice_type, COALESCE(SUM(duration_minutes), 0) AS minutes, COUNT(*) AS count
                FROM entries
                GROUP BY practice_type
                ORDER BY minutes DESC
                """
            ).fetchall()
            recent_days = conn.execute(
                "SELECT DISTINCT practice_date FROM entries ORDER BY practice_date DESC"
            ).fetchall()
            total_days = conn.execute(
                "SELECT COUNT(DISTINCT practice_date) AS count FROM entries"
            ).fetchone()

        return {
            "total": dict(total),
            "month": dict(month),
            "week": dict(week),
            "by_type": [dict(row) for row in by_type],
            "streak": _streak([row["practice_date"] for row in recent_days]),
            "total_days": int(total_days["count"]),
        }

    def calendar_month(self, year: int, month: int) -> dict[str, dict[str, object]]:
        month_text = f"{year:04d}-{month:02d}"
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT practice_date, practice_type,
                       COALESCE(SUM(duration_minutes), 0) AS minutes,
                       COUNT(*) AS count
                FROM entries
                WHERE strftime('%Y-%m', practice_date) = ?
                GROUP BY practice_date, practice_type
                ORDER BY practice_date ASC, minutes DESC, practice_type ASC
                """,
                (month_text,),
            ).fetchall()

        days: dict[str, dict[str, object]] = {}
        for row in rows:
            date_text = str(row["practice_date"])
            practice_type = str(row["practice_type"])
            minutes = int(row["minutes"])
            day = days.setdefault(
                date_text,
                {
                    "date": date_text,
                    "minutes": 0,
                    "count": 0,
                    "primary_type": practice_type,
                    "types": {},
                },
            )
            day["minutes"] = int(day["minutes"]) + minutes
            day["count"] = int(day["count"]) + int(row["count"])
            types = day["types"]
            if isinstance(types, dict):
                types[practice_type] = minutes
                primary = str(day["primary_type"])
                if minutes > int(types.get(primary, 0)):
                    day["primary_type"] = practice_type
        return days

    def practice_months(self) -> list[str]:
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT strftime('%Y-%m', practice_date) AS month
                FROM entries
                ORDER BY month ASC
                """
            ).fetchall()
        return [str(row["month"]) for row in rows if row["month"]]


def _streak(days: list[str]) -> int:
    if not days:
        return 0
    parsed = sorted({datetime.strptime(day, "%Y-%m-%d").date() for day in days}, reverse=True)
    current = datetime.now().date()
    if parsed[0] != current:
        return 0
    streak = 0
    for day in parsed:
        if day == current:
            streak += 1
            current = current.fromordinal(current.toordinal() - 1)
        else:
            break
    return streak
