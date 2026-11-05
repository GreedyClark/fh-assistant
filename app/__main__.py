import asyncio
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.analysis import BidAnalyzer
from app.config import KYIV, Settings
from app.db import Database
from app.fh_client import FreelancehuntClient
from app.handlers import build_router
from app.health import Health
from app.llm import AnthropicClient
from app.notifier import Notifier
from app.poller import Poller
from app.prefs import PrefsStore
from app.rates import Rates

BOT_COMMANDS = [
    BotCommand(command="top", description="Найкращі проєкти за добу"),
    BotCommand(command="analyze", description="Аналіз ставки за номером чи посиланням"),
    BotCommand(command="stats", description="Статистика ставок і ринку"),
    BotCommand(command="settings", description="Налаштування"),
    BotCommand(command="status", description="Стан опитування"),
    BotCommand(command="pause", description="Поставити сповіщення на паузу"),
    BotCommand(command="resume", description="Відновити сповіщення"),
    BotCommand(command="threshold", description="Поріг оцінки для звуку"),
    BotCommand(command="stop", description="Стоп-слова"),
    BotCommand(command="minbudget", description="Мінімальний бюджет"),
    BotCommand(command="quiet", description="Тихі години"),
]


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(log_dir / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console])
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_dir)

    db = Database(settings.db_path)
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    scheduler = AsyncIOScheduler(timezone=KYIV)

    try:
        await db.connect()
        prefs_store = PrefsStore(db, settings)
        await prefs_store.load()
        await bot.set_my_commands(BOT_COMMANDS)
        if settings.miniapp_url:
            try:
                await bot.set_chat_menu_button(
                    chat_id=settings.allowed_user_id,
                    menu_button=MenuButtonWebApp(text="Проєкти", web_app=WebAppInfo(url=settings.miniapp_url)),
                )
            except TelegramAPIError as exc:
                logging.getLogger(__name__).warning("Cannot set Mini App menu button: %s", exc)

        fh = FreelancehuntClient(settings.fh_token.get_secret_value(), session)
        rates = Rates(session, db)
        await rates.load()
        analyzer = None
        api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
        if api_key:
            llm = AnthropicClient(api_key, settings.llm_model, settings.llm_max_tokens)
            analyzer = BidAnalyzer(llm, db, settings.profile_path, settings.llm_daily_limit)
            logging.getLogger(__name__).info("Bid analysis enabled, model %s", settings.llm_model)
        notifier = Notifier(bot, db, settings, prefs_store, analyzer is not None)
        health = Health(
            bot,
            settings.allowed_user_id,
            session,
            settings.healthcheck_url,
            timedelta(hours=settings.alert_after_hours),
        )
        poller = Poller(fh, db, rates, notifier, prefs_store, settings, health)

        scheduler.add_job(
            poller.run,
            IntervalTrigger(minutes=settings.poll_interval_minutes, jitter=60),
            next_run_time=datetime.now(KYIV),
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(rates.refresh, CronTrigger(hour=9, minute=7))
        scheduler.start()

        dp = Dispatcher()
        dp.include_router(build_router(settings.allowed_user_id))
        await dp.start_polling(
            bot,
            db=db,
            poller=poller,
            prefs_store=prefs_store,
            notifier=notifier,
            settings=settings,
            analyzer=analyzer,
            health=health,
        )
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        await session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
