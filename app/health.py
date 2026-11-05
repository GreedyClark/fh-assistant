"""Сповіщення про проблеми бота і пінг на healthchecks.io."""

import logging
from html import escape
from datetime import UTC, datetime, timedelta

import aiohttp
from aiogram import Bot

log = logging.getLogger(__name__)

PING_TIMEOUT = aiohttp.ClientTimeout(total=10)


class Health:
    """Стежить за опитуванням і пише в Telegram, коли щось зламалось і коли полагодилось."""

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        session: aiohttp.ClientSession,
        ping_url: str | None,
        alert_after: timedelta = timedelta(hours=2),
    ):
        self._bot = bot
        self._chat_id = chat_id
        self._session = session
        self._ping_url = ping_url.rstrip("/") if ping_url else None
        self._alert_after = alert_after
        self._failing_since: datetime | None = None
        self._alerted: set[str] = set()
        self.last_ping_ok: bool | None = None

    @property
    def ping_enabled(self) -> bool:
        return self._ping_url is not None

    async def poll_ok(self) -> None:
        if self._alerted & {"auth", "polling"}:
            await self._send("✅ Опитування Freelancehunt знову працює")
        self._alerted -= {"auth", "polling"}
        self._failing_since = None
        await self._ping("")

    async def poll_failed(self, error: str, *, auth: bool = False, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        if self._failing_since is None:
            self._failing_since = now
        if auth and "auth" not in self._alerted:
            self._alerted.add("auth")
            await self._send(
                "⚠️ Freelancehunt не приймає токен. Проєкти не надходять.\n"
                "Перевір FH_TOKEN у .env (можливо, токен перевипущено) і перезапусти бота."
            )
            await self._ping("/fail")
            return
        if now - self._failing_since >= self._alert_after and "polling" not in self._alerted:
            self._alerted.add("polling")
            hours = int((now - self._failing_since).total_seconds() // 3600)
            await self._send(
                f"⚠️ Опитування Freelancehunt не працює вже {hours} год.\n"
                f"Остання помилка: {escape(error[:300])}\n"
                "Бот пробує далі сам, напишу, коли запрацює."
            )
            await self._ping("/fail")

    async def _send(self, text: str) -> None:
        try:
            await self._bot.send_message(self._chat_id, text)
        except Exception:
            log.exception("Cannot send health alert")

    async def _ping(self, suffix: str) -> None:
        if not self._ping_url:
            return
        try:
            async with self._session.get(self._ping_url + suffix, timeout=PING_TIMEOUT) as resp:
                self.last_ping_ok = resp.status < 400
        except Exception as exc:
            self.last_ping_ok = False
            log.warning("Healthcheck ping failed: %s", exc)
