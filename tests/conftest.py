import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data"
TMP = Path(tempfile.mkdtemp(prefix="fh-tests-"))

sys.path[:0] = [str(ROOT), str(ROOT / "web")]
os.environ.update(
    FH_TOKEN="fh-test-token",
    BOT_TOKEN="123:TEST",
    ALLOWED_USER_ID="42",
    ANTHROPIC_API_KEY="sk-test",
    DB_PATH=str(TMP / "web.db"),
    LOG_DIR=str(TMP / "logs"),
    MINIAPP_URL="https://example.ts.net",
    HEALTHCHECK_URL="",
    DJANGO_SETTINGS_MODULE="miniapp.settings",
)

from app.db import Database  # noqa: E402
from app.models import parse_project  # noqa: E402

LONG = " Детальний опис задачі з усіма вимогами та прикладами." * 5


def make_item(
    pid,
    skills=(22,),
    name="Проєкт",
    desc=LONG,
    budget=None,
    bids=1,
    safe="employer",
    employer=None,
    age_hours=0.2,
):
    published = datetime.now(UTC) - timedelta(hours=age_hours)
    return {
        "id": pid,
        "type": "project",
        "attributes": {
            "name": name,
            "description": desc,
            "budget": budget,
            "safe_type": safe,
            "skills": [{"id": s, "name": f"skill {s}"} for s in skills],
            "status": {"id": 11, "name": "Прийом ставок"},
            "bid_count": bids,
            "is_premium": False,
            "published_at": published.isoformat(),
            "expired_at": (published + timedelta(days=7)).isoformat(),
            "employer": employer
            if employer is not None
            else {"id": 77, "login": "employer", "positive_reviews": 0, "negative_reviews": 0, "completed_projects": 0},
        },
        "links": {"self": {"web": f"https://freelancehunt.com/project/test/{pid}.html"}},
    }


def make_project(pid=1, **kwargs):
    return parse_project(make_item(pid, **kwargs))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sample_analysis():
    return json.loads((DATA / "analysis.json").read_text(encoding="utf-8"))


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "fh.db"


@pytest.fixture
def with_db(db_path):
    async def wrapper(fn):
        db = Database(db_path)
        await db.connect()
        try:
            return await fn(db)
        finally:
            await db.close()

    return lambda fn: run(wrapper(fn))
