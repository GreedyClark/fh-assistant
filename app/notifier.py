import asyncio
import json
import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.config import Settings
from app.db import Database
from app.filters import preference_reason
from app.messages import format_project, project_keyboard
from app.models import parse_project
from app.prefs import PrefsStore
from app.scoring import score_project

log = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        bot: Bot,
        db: Database,
        settings: Settings,
        prefs_store: PrefsStore,
        analyze_enabled: bool = False,
    ):
        self._bot = bot
        self._analyze_enabled = analyze_enabled
        self._db = db
        self._settings = settings
        self._prefs_store = prefs_store
        self._lock = asyncio.Lock()

    def is_holding(self) -> bool:
        prefs = self._prefs_store.prefs
        return prefs.paused or prefs.in_quiet_hours(datetime.now(UTC))

    async def flush(self) -> None:
        if self.is_holding():
            return
        async with self._lock:
            await self._send_pending()

    async def _send_pending(self) -> None:
        rows = await self._db.pending_notifications(self._settings.notify_max_age_hours)
        for raw, budget_uah, first_seen_at, cross_category in rows:
            if self.is_holding():
                return
            prefs = self._prefs_store.prefs
            project = parse_project(json.loads(raw))
            reason = preference_reason(project, budget_uah, prefs)
            if reason:
                await self._db.set_rejected(project.id, reason)
                continue

            now = datetime.now(UTC)
            cross = bool(cross_category)
            score = score_project(project, budget_uah, now, cross)
            await self._db.set_score(project.id, score.value, {"pros": score.pros, "cons": score.cons})
            silent = cross or score.value < prefs.loud_threshold
            try:
                await self._bot.send_message(
                    self._settings.allowed_user_id,
                    format_project(
                        project,
                        budget_uah,
                        score,
                        cross,
                        datetime.fromisoformat(first_seen_at),
                        prefs.loud_threshold,
                    ),
                    reply_markup=project_keyboard(project, self._analyze_enabled, self._settings.miniapp_url),
                    disable_notification=silent,
                )
            except TelegramRetryAfter as exc:
                log.warning("Telegram flood control, retry after %s s", exc.retry_after)
                await asyncio.sleep(exc.retry_after)
                return
            except TelegramAPIError:
                log.exception("Failed to send project %s", project.id)
                return
            await self._db.mark_notified(project.id)
            await asyncio.sleep(0.5)
