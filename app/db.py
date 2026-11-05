import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from app.config import KYIV
from app.models import Project

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    published_at TEXT NOT NULL,
    budget_amount REAL,
    budget_currency TEXT,
    budget_uah REAL,
    safe_type TEXT,
    skill_ids TEXT NOT NULL,
    bid_count INTEGER,
    employer_id INTEGER,
    employer_login TEXT,
    matched INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    notified_at TEXT,
    action TEXT,
    raw TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_pending ON projects (matched, notified_at);

CREATE TABLE IF NOT EXISTS blocked_employers (
    employer_id INTEGER PRIMARY KEY,
    login TEXT,
    blocked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rates (
    currency TEXT PRIMARY KEY,
    rate REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    project_id INTEGER PRIMARY KEY,
    result TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bids (
    project_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    price_uah REAL,
    days INTEGER,
    note TEXT,
    estimated_hours REAL,
    actual_hours REAL,
    source TEXT NOT NULL DEFAULT 'manual',
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MIGRATIONS = {
    "cross_category": "ALTER TABLE projects ADD COLUMN cross_category INTEGER NOT NULL DEFAULT 0",
    "score": "ALTER TABLE projects ADD COLUMN score INTEGER",
    "score_reasons": "ALTER TABLE projects ADD COLUMN score_reasons TEXT",
}


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


def _now() -> str:
    return _utc_iso(datetime.now(UTC))


class Database:
    def __init__(self, path: Path):
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.executescript(SCHEMA)
        async with self._conn.execute("PRAGMA table_info(projects)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        for column, statement in MIGRATIONS.items():
            if column not in columns:
                await self._conn.execute(statement)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def is_empty(self) -> bool:
        async with self._conn.execute("SELECT 1 FROM projects LIMIT 1") as cur:
            return await cur.fetchone() is None

    async def known_ids(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        placeholders = ",".join("?" * len(ids))
        async with self._conn.execute(f"SELECT id FROM projects WHERE id IN ({placeholders})", ids) as cur:
            return {row[0] for row in await cur.fetchall()}

    async def insert_project(
        self,
        p: Project,
        budget_uah: float | None,
        reject_reason: str | None,
        cross_category: bool = False,
    ) -> None:
        await self._conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                id, name, published_at, budget_amount, budget_currency, budget_uah, safe_type,
                skill_ids, bid_count, employer_id, employer_login, matched, reject_reason, raw, first_seen_at,
                cross_category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p.id,
                p.name,
                _utc_iso(p.published_at),
                p.budget_amount,
                p.budget_currency,
                budget_uah,
                p.safe_type,
                json.dumps(sorted(p.skill_ids)),
                p.bid_count,
                p.employer.id if p.employer else None,
                p.employer.login if p.employer else None,
                int(reject_reason is None),
                reject_reason,
                json.dumps(p.raw, ensure_ascii=False),
                _now(),
                int(cross_category),
            ),
        )
        await self._conn.commit()

    async def pending_notifications(
        self, max_age_hours: int, limit: int = 20
    ) -> list[tuple[str, float | None, str, int]]:
        cutoff = _utc_iso(datetime.now(UTC) - timedelta(hours=max_age_hours))
        async with self._conn.execute(
            """
            SELECT raw, budget_uah, first_seen_at, cross_category FROM projects
            WHERE matched = 1
              AND notified_at IS NULL
              AND published_at >= ?
              AND (employer_id IS NULL OR employer_id NOT IN (SELECT employer_id FROM blocked_employers))
            ORDER BY id
            LIMIT ?
            """,
            (cutoff, limit),
        ) as cur:
            return await cur.fetchall()

    async def mark_notified(self, project_id: int) -> None:
        await self._conn.execute("UPDATE projects SET notified_at = ? WHERE id = ?", (_now(), project_id))
        await self._conn.commit()

    async def recent_matched(self, hours: int) -> list[tuple[str, float | None, str, int]]:
        since = _utc_iso(datetime.now(UTC) - timedelta(hours=hours))
        async with self._conn.execute(
            """
            SELECT raw, budget_uah, first_seen_at, cross_category FROM projects
            WHERE matched = 1 AND first_seen_at >= ?
              AND (employer_id IS NULL OR employer_id NOT IN (SELECT employer_id FROM blocked_employers))
            """,
            (since,),
        ) as cur:
            return await cur.fetchall()

    async def get_project(self, project_id: int) -> tuple[str, float | None] | None:
        async with self._conn.execute("SELECT raw, budget_uah FROM projects WHERE id = ?", (project_id,)) as cur:
            return await cur.fetchone()

    async def get_analysis(self, project_id: int) -> dict | None:
        async with self._conn.execute("SELECT result FROM analyses WHERE project_id = ?", (project_id,)) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def save_analysis(
        self,
        project_id: int,
        result: dict,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
    ) -> None:
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO analyses
                (project_id, result, model, input_tokens, output_tokens, cache_read_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                json.dumps(result, ensure_ascii=False),
                model,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                _now(),
            ),
        )
        await self._conn.commit()

    async def analyses_today(self) -> int:
        start = datetime.now(KYIV).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._conn.execute(
            "SELECT COUNT(*) FROM analyses WHERE created_at >= ?", (_utc_iso(start),)
        ) as cur:
            return (await cur.fetchone())[0]

    async def analysis_usage(self, days: int) -> tuple[int, int, int]:
        since = _utc_iso(datetime.now(UTC) - timedelta(days=days))
        async with self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) "
            "FROM analyses WHERE created_at >= ?",
            (since,),
        ) as cur:
            return await cur.fetchone()

    async def set_score(self, project_id: int, score: int, reasons: dict) -> None:
        await self._conn.execute(
            "UPDATE projects SET score = ?, score_reasons = ? WHERE id = ?",
            (score, json.dumps(reasons, ensure_ascii=False), project_id),
        )
        await self._conn.commit()

    async def set_rejected(self, project_id: int, reason: str) -> None:
        await self._conn.execute(
            "UPDATE projects SET matched = 0, reject_reason = ? WHERE id = ?", (reason, project_id)
        )
        await self._conn.commit()

    async def get_setting(self, key: str):
        async with self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def set_setting(self, key: str, value) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        await self._conn.commit()

    async def set_action(self, project_id: int, action: str) -> None:
        await self._conn.execute("UPDATE projects SET action = ? WHERE id = ?", (action, project_id))
        await self._conn.commit()

    async def project_employer(self, project_id: int) -> tuple[int, str] | None:
        async with self._conn.execute(
            "SELECT employer_id, employer_login FROM projects WHERE id = ? AND employer_id IS NOT NULL",
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
        return (row[0], row[1] or "") if row else None

    async def block_employer(self, employer_id: int, login: str) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO blocked_employers (employer_id, login, blocked_at) VALUES (?, ?, ?)",
            (employer_id, login, _now()),
        )
        await self._conn.commit()

    async def blocked_employer_ids(self) -> set[int]:
        async with self._conn.execute("SELECT employer_id FROM blocked_employers") as cur:
            return {row[0] for row in await cur.fetchall()}

    async def get_rates(self) -> dict[str, float]:
        async with self._conn.execute("SELECT currency, rate FROM rates") as cur:
            return {row[0]: row[1] for row in await cur.fetchall()}

    async def save_rates(self, rates: dict[str, float]) -> None:
        now = _now()
        await self._conn.executemany(
            "INSERT OR REPLACE INTO rates (currency, rate, updated_at) VALUES (?, ?, ?)",
            [(currency, rate, now) for currency, rate in rates.items()],
        )
        await self._conn.commit()

    async def market_rows(self, days: int) -> list[tuple[str, float | None]]:
        since = _utc_iso(datetime.now(UTC) - timedelta(days=days))
        async with self._conn.execute(
            "SELECT skill_ids, budget_uah FROM projects WHERE first_seen_at >= ?", (since,)
        ) as cur:
            return await cur.fetchall()

    async def matched_rows(self, days: int) -> list[tuple[str, int | None]]:
        since = _utc_iso(datetime.now(UTC) - timedelta(days=days))
        async with self._conn.execute(
            "SELECT published_at, bid_count FROM projects WHERE matched = 1 AND first_seen_at >= ?", (since,)
        ) as cur:
            return await cur.fetchall()

    async def bids_all(self) -> list[tuple[str, float | None, float | None, float | None]]:
        async with self._conn.execute(
            "SELECT status, price_uah, estimated_hours, actual_hours FROM bids"
        ) as cur:
            return await cur.fetchall()

    async def stats(self) -> dict[str, int]:
        async with self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(matched), 0), COUNT(notified_at) FROM projects"
        ) as cur:
            total, matched, notified = await cur.fetchone()
        return {"total": total, "matched": matched, "notified": notified}
