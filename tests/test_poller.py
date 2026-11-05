from datetime import UTC, datetime

from app.config import Settings
from app.fh_client import FHError, RateLimited
from app.poller import BASE_BACKOFF, Poller
from app.prefs import PrefsStore
from app.rates import Rates

from conftest import make_project


class FakeFH:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def projects_page(self, url=None):
        self.calls.append(url)
        result = self.pages[url]
        if isinstance(result, Exception):
            raise result
        return result


class FakeNotifier:
    flushed = 0

    async def flush(self):
        self.flushed += 1


class FakeHealth:
    def __init__(self):
        self.ok = 0
        self.failed = []

    async def poll_ok(self):
        self.ok += 1

    async def poll_failed(self, error, auth=False, now=None):
        self.failed.append(auth)


def make_poller(db, fh, health=None):
    settings = Settings(_env_file=None)
    store = PrefsStore(db, settings)
    return Poller(fh, db, Rates(None, db), FakeNotifier(), store, settings, health)


def ids(rows):
    return sorted(r[0] for r in rows)


async def saved_ids(db):
    async with db._conn.execute("SELECT id FROM projects") as cur:
        return ids(await cur.fetchall())


def test_first_run_reads_one_page_then_catches_up(with_db):
    async def scenario(db):
        fh = FakeFH({None: ([make_project(3), make_project(2)], "p2"), "p2": ([make_project(1)], None)})
        health = FakeHealth()
        poller = make_poller(db, fh, health)
        await poller.run()
        assert fh.calls == [None]
        assert await saved_ids(db) == [2, 3]

        fh.pages[None] = ([make_project(6), make_project(5)], "p2")
        fh.pages["p2"] = ([make_project(4), make_project(3)], "p3")
        await poller.run()
        assert fh.calls[1:] == [None, "p2"]
        assert await saved_ids(db) == [2, 3, 4, 5, 6]
        assert health.ok == 2 and poller.last_error is None

    with_db(scenario)


def test_duplicates_are_not_saved_twice(with_db):
    async def scenario(db):
        fh = FakeFH({None: ([make_project(1)], None)})
        poller = make_poller(db, fh)
        await poller.run()
        await poller.run()
        assert await saved_ids(db) == [1]

    with_db(scenario)


def test_rate_limit_pauses_with_growing_backoff(with_db):
    async def scenario(db):
        health = FakeHealth()
        poller = make_poller(db, FakeFH({None: RateLimited()}), health)
        before = datetime.now(UTC)
        await poller.run()
        first = poller.paused_until
        assert first >= before + BASE_BACKOFF and health.failed == [False]
        poller.paused_until = None
        await poller.run()
        assert poller.paused_until - datetime.now(UTC) > BASE_BACKOFF

    with_db(scenario)


def test_auth_error_is_reported(with_db):
    async def scenario(db):
        health = FakeHealth()
        poller = make_poller(db, FakeFH({None: FHError("HTTP 401", 401)}), health)
        await poller.run()
        assert health.failed == [True] and "401" in poller.last_error

    with_db(scenario)
