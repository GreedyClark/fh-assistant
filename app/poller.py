import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db import Database
from app.fh_client import FHError, FreelancehuntClient, RateLimited
from app.health import Health
from app.filters import classify
from app.models import Project
from app.notifier import Notifier
from app.prefs import PrefsStore
from app.rates import Rates

BASE_BACKOFF = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=2)

log = logging.getLogger(__name__)


class Poller:
    def __init__(
        self,
        fh: FreelancehuntClient,
        db: Database,
        rates: Rates,
        notifier: Notifier,
        prefs_store: PrefsStore,
        settings: Settings,
        health: Health | None = None,
    ):
        self._fh = fh
        self._db = db
        self._rates = rates
        self._notifier = notifier
        self._prefs_store = prefs_store
        self._settings = settings
        self._health = health
        self._backoff = BASE_BACKOFF
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.paused_until: datetime | None = None

    async def run(self) -> None:
        now = datetime.now(UTC)
        if self.paused_until and now < self.paused_until:
            return
        await self._prefs_store.load()

        try:
            new_projects = await self._fetch_new()
        except RateLimited:
            self.paused_until = now + self._backoff
            self._backoff = min(self._backoff * 2, MAX_BACKOFF)
            self.last_error = "ліміт запитів (429)"
            log.warning("Freelancehunt returned 429, paused until %s", self.paused_until)
            await self._report_failure(now)
            return
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("Polling failed")
            auth = isinstance(exc, FHError) and exc.status in (401, 403)
            await self._report_failure(now, auth=auth)
            return

        self._backoff = BASE_BACKOFF
        self.paused_until = None
        self.last_error = None
        self.last_success_at = now

        if new_projects:
            blocked = await self._db.blocked_employer_ids()
            skill_ids = set(self._settings.skill_ids)
            prefs = self._prefs_store.prefs
            for project in sorted(new_projects, key=lambda p: p.id):
                budget_uah = self._rates.to_uah(project.budget_amount, project.budget_currency)
                reason, cross = classify(project, budget_uah, skill_ids, prefs, blocked)
                await self._db.insert_project(project, budget_uah, reason, cross)
            log.info("Saved %d new projects", len(new_projects))

        await self._notifier.flush()
        if self._health:
            await self._health.poll_ok()

    async def _report_failure(self, now: datetime, auth: bool = False) -> None:
        if self._health:
            await self._health.poll_failed(self.last_error or "", auth=auth, now=now)

    async def _fetch_new(self) -> list[Project]:
        max_pages = 1 if await self._db.is_empty() else self._settings.max_catchup_pages
        url = None
        result: list[Project] = []
        for _ in range(max_pages):
            projects, next_url = await self._fh.projects_page(url)
            if not projects:
                break
            known = await self._db.known_ids([p.id for p in projects])
            result.extend(p for p in projects if p.id not in known)
            if known or not next_url:
                break
            url = next_url
        return result
