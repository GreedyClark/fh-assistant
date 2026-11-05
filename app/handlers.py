import json
import logging
import re
from datetime import UTC, datetime
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.analysis import BidAnalyzer, DailyLimitReached
from app.config import KYIV, Settings
from app.db import Database
from app.health import Health
from app.llm import LLMError
from app.messages import (
    ProjectAction,
    SettingsAction,
    analysis_drafts,
    send_bid_keyboard,
    format_analysis,
    format_settings,
    format_top,
    settings_keyboard,
)
from app.models import parse_project
from app.notifier import Notifier
from app.poller import Poller
from app.prefs import PrefsStore
from app.pricing import estimate
from app.scoring import score_project
from app.stats import average_bids, calibration, funnel, hours_histogram, market_by_skill, market_price

TOP_LIMIT = 10
TOP_DEFAULT_HOURS = 24
TOP_MAX_HOURS = 168

QUIET_RE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})$")
MESSAGE_LIMIT = 4000
PROJECT_ID_RE = re.compile(r"(\d{5,})(?:\.html)?/?\s*$")

log = logging.getLogger(__name__)


def _fmt_time(dt: datetime | None) -> str:
    return dt.astimezone(KYIV).strftime("%d.%m %H:%M") if dt else "ще не було"


def _parse_words(text: str) -> list[str]:
    return [w.strip().lower() for w in text.split(",") if w.strip()]


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def reload_prefs(handler, event, data):
    prefs_store = data.get("prefs_store")
    if prefs_store is not None:
        await prefs_store.load()
    return await handler(event, data)


def build_router(allowed_user_id: int) -> Router:
    router = Router()
    router.message.filter(F.from_user.id == allowed_user_id)
    router.callback_query.filter(F.from_user.id == allowed_user_id)
    router.message.middleware(reload_prefs)
    router.callback_query.middleware(reload_prefs)

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Бот працює, нові проєкти надходитимуть автоматично.\n"
            "/top - найкращі проєкти за добу\n/settings - налаштування\n/status - стан бота"
        )

    @router.message(Command("status"))
    async def status(
        message: Message,
        db: Database,
        poller: Poller,
        prefs_store: PrefsStore,
        settings: Settings,
        analyzer: BidAnalyzer | None,
        health: Health | None = None,
    ) -> None:
        stats = await db.stats()
        prefs = prefs_store.prefs
        lines = [
            f"Останнє успішне опитування: {_fmt_time(poller.last_success_at)}",
            f"Проєктів у базі: {stats['total']}, підійшло: {stats['matched']}, надіслано: {stats['notified']}",
        ]
        if prefs.paused:
            lines.append("Сповіщення на паузі")
        elif prefs.in_quiet_hours(datetime.now(UTC)):
            lines.append(f"Тихі години, проєкти прийдуть о {prefs.quiet_end:02d}:00")
        if poller.paused_until and poller.paused_until > datetime.now(UTC):
            lines.append(f"Пауза через ліміт до {_fmt_time(poller.paused_until)}")
        if poller.last_error:
            lines.append(f"Остання помилка: {escape(poller.last_error)}")
        if analyzer is not None:
            today = await db.analyses_today()
            count, tokens_in, tokens_out = await db.analysis_usage(30)
            cost = (
                tokens_in * settings.llm_input_price_per_m + tokens_out * settings.llm_output_price_per_m
            ) / 1_000_000
            lines.append(f"Аналізів сьогодні: {today} з {settings.llm_daily_limit}")
            lines.append(f"Аналізів за 30 днів: {count}, приблизно ${cost:.3f}")
        else:
            lines.append("Аналіз ставки вимкнено: немає ANTHROPIC_API_KEY")
        if health is None or not health.ping_enabled:
            lines.append("Healthchecks: не налаштовано")
        elif health.last_ping_ok is None:
            lines.append("Healthchecks: ще не пінгував")
        else:
            lines.append("Healthchecks: " + ("працює" if health.last_ping_ok else "останній пінг не пройшов"))
        await message.answer("\n".join(lines))

    @router.message(Command("stats"))
    async def stats(message: Message, db: Database, settings: Settings) -> None:
        bids = await db.bids_all()
        f = funnel(bids)
        lines = ["<b>Мої ставки</b>"]
        if f["total"]:
            lines.append(f"Подано: {f['total']}, чекають відповіді: {f['waiting']}")
            lines.append(f"Виграно: {f['won']}, програно: {f['lost']}, без відповіді: {f['no_reply']}")
            if f["conversion"] is not None:
                lines.append(f"Конверсія: {f['conversion']}%")
            if f["avg_price"]:
                lines.append(f"Середня ціна ставки: {f['avg_price']:,} грн".replace(",", " "))
            cal = calibration(bids)
            if cal:
                lines.append(f"Реальні години / оцінка: x{cal['ratio']} (проєктів: {cal['count']})")
        else:
            lines.append("Ставок ще немає. Відмічай їх на картці проєкту в Mini App")

        lines += ["", "<b>Ринок за 30 днів</b>"]
        for item in market_by_skill(await db.market_rows(30), settings.skill_ids):
            if not item["count"]:
                continue
            line = f"{item['name']}: {item['count']} проєктів, з бюджетом {item['with_budget']}"
            if item["median"]:
                median, low, high = (f"{v:,}".replace(",", " ") for v in (item["median"], item["low"], item["high"]))
                line += f", медіана {median} грн ({low}-{high})"
            lines.append(line)
        matched = await db.matched_rows(30)
        hours = hours_histogram([published for published, _ in matched])
        if any(hours):
            top = [h for h in sorted(range(24), key=lambda h: hours[h], reverse=True)[:3] if hours[h]]
            lines.append("Найбільше твоїх проєктів о " + ", ".join(f"{h:02d}:00" for h in sorted(top)))
        avg = average_bids([bids_count for _, bids_count in matched])
        if avg is not None:
            lines.append(f"Ставок, коли бот знаходить проєкт: у середньому {avg}")
        await message.answer("\n".join(lines))

    @router.message(Command("settings"))
    async def settings(message: Message, prefs_store: PrefsStore) -> None:
        prefs = prefs_store.prefs
        await message.answer(format_settings(prefs), reply_markup=settings_keyboard(prefs))

    @router.callback_query(SettingsAction.filter())
    async def toggle(
        callback: CallbackQuery,
        callback_data: SettingsAction,
        prefs_store: PrefsStore,
        notifier: Notifier,
    ) -> None:
        prefs = prefs_store.prefs
        if callback_data.action == "pause":
            prefs.paused = not prefs.paused
        elif callback_data.action == "quiet":
            prefs.quiet_enabled = not prefs.quiet_enabled
        elif callback_data.action == "cross":
            prefs.cross_category = not prefs.cross_category
        await prefs_store.save()
        if isinstance(callback.message, Message):
            await callback.message.edit_text(format_settings(prefs), reply_markup=settings_keyboard(prefs))
        await callback.answer()
        await notifier.flush()

    @router.message(Command("pause"))
    async def pause(message: Message, prefs_store: PrefsStore) -> None:
        prefs_store.prefs.paused = True
        await prefs_store.save()
        await message.answer("Сповіщення на паузі. Проєкти й далі збираються. /resume - відновити")

    @router.message(Command("resume"))
    async def resume(message: Message, prefs_store: PrefsStore, notifier: Notifier) -> None:
        prefs_store.prefs.paused = False
        await prefs_store.save()
        await message.answer("Сповіщення відновлено")
        await notifier.flush()

    @router.message(Command("minbudget"))
    async def min_budget(message: Message, command: CommandObject, prefs_store: PrefsStore) -> None:
        arg = (command.args or "").strip().replace(" ", "")
        if not arg.isdigit():
            await message.answer(
                f"Зараз: {prefs_store.prefs.min_budget_uah} грн.\nПриклад: /minbudget 500"
            )
            return
        prefs_store.prefs.min_budget_uah = int(arg)
        await prefs_store.save()
        await message.answer(f"Мінімальний бюджет: {int(arg)} грн. Проєкти без бюджету показуються як і раніше")

    @router.message(Command("top"))
    async def top(message: Message, command: CommandObject, db: Database, prefs_store: PrefsStore) -> None:
        arg = (command.args or "").strip()
        hours = int(arg) if arg.isdigit() else TOP_DEFAULT_HOURS
        hours = max(1, min(hours, TOP_MAX_HOURS))
        entries = []
        for raw, budget_uah, first_seen_at, cross in await db.recent_matched(hours):
            project = parse_project(json.loads(raw))
            score = score_project(project, budget_uah, datetime.fromisoformat(first_seen_at), bool(cross))
            entries.append((project, score, bool(cross)))
        entries.sort(key=lambda e: e[1].value, reverse=True)
        await message.answer(format_top(entries[:TOP_LIMIT], hours, prefs_store.prefs.loud_threshold))

    @router.message(Command("threshold"))
    async def threshold(message: Message, command: CommandObject, prefs_store: PrefsStore) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit() or not 0 <= int(arg) <= 100:
            await message.answer(
                f"Зараз: зі звуком приходять проєкти з оцінкою від {prefs_store.prefs.loud_threshold}.\n"
                "Приклад: /threshold 70"
            )
            return
        prefs_store.prefs.loud_threshold = int(arg)
        await prefs_store.save()
        await message.answer(f"Зі звуком: оцінка від {int(arg)}. Решта приходитиме без звуку")

    @router.message(Command("quiet"))
    async def quiet(message: Message, command: CommandObject, prefs_store: PrefsStore, notifier: Notifier) -> None:
        prefs = prefs_store.prefs
        match = QUIET_RE.match((command.args or "").strip())
        if not match or not all(0 <= int(h) <= 23 for h in match.groups()):
            await message.answer(
                f"Зараз: {prefs.quiet_start:02d}:00-{prefs.quiet_end:02d}:00.\nПриклад: /quiet 23-8"
            )
            return
        prefs.quiet_start, prefs.quiet_end = (int(h) for h in match.groups())
        prefs.quiet_enabled = True
        await prefs_store.save()
        await message.answer(f"Тихі години: {prefs.quiet_start:02d}:00-{prefs.quiet_end:02d}:00")
        await notifier.flush()

    @router.message(Command("stop"))
    async def stop_words(message: Message, command: CommandObject, prefs_store: PrefsStore) -> None:
        prefs = prefs_store.prefs
        action, _, rest = (command.args or "").strip().partition(" ")
        words = _parse_words(rest)

        if action == "add" and words:
            added = [w for w in words if w not in prefs.stop_words]
            prefs.stop_words.extend(added)
            await prefs_store.save()
            await message.answer(f"Додано: {escape(', '.join(added)) or 'нічого нового'}")
        elif action == "del" and words:
            removed = [w for w in words if w in prefs.stop_words]
            prefs.stop_words = [w for w in prefs.stop_words if w not in removed]
            await prefs_store.save()
            await message.answer(f"Прибрано: {escape(', '.join(removed)) or 'таких слів немає'}")
        else:
            current = ", ".join(prefs.stop_words) or "порожньо"
            await message.answer(
                f"Стоп-слова: {escape(current)}\n\n/stop add слово, слово - додати\n/stop del слово - прибрати"
            )

    in_progress: set[int] = set()

    async def run_analysis(
        bot,
        chat_id: int,
        reply_to: int | None,
        project_id: int,
        db: Database,
        settings: Settings,
        analyzer: BidAnalyzer,
    ) -> None:
        row = await db.get_project(project_id)
        if row is None:
            await bot.send_message(chat_id, "Цього проєкту немає в базі бота", reply_to_message_id=reply_to)
            return
        if project_id in in_progress:
            await bot.send_message(chat_id, "Аналіз цього проєкту вже йде", reply_to_message_id=reply_to)
            return
        in_progress.add(project_id)
        waiting = await bot.send_message(
            chat_id, "Аналізую проєкт, це займе до хвилини...", reply_to_message_id=reply_to
        )
        try:
            project = parse_project(json.loads(row[0]))
            budget_uah = row[1]
            try:
                record = await analyzer.analyze(project, budget_uah)
            except DailyLimitReached:
                await waiting.edit_text(f"Денний ліміт аналізів вичерпано ({settings.llm_daily_limit})")
                return
            except LLMError as exc:
                log.warning("Analysis failed for %s: %s", project_id, exc)
                await waiting.edit_text(f"Не вдалося зробити аналіз: {escape(str(exc))[:300]}")
                return
            except Exception:
                log.exception("Unexpected analysis error for %s", project_id)
                await waiting.edit_text("Не вдалося зробити аналіз, деталі в логах бота")
                return
            market = market_price(await db.market_rows(30), project.skill_ids)
            est = estimate(record.data, budget_uah, settings.min_hourly_rate_uah, settings.time_buffer, market)
            text = format_analysis(project, record.data, est, settings.min_hourly_rate_uah, settings.time_buffer)
            drafts = analysis_drafts(record.data)
            if drafts:
                text += "\n\nНижче чернетки, кожна окремим повідомленням для зручного копіювання."
            if record.cached:
                text += "\n<i>Збережений аналіз, повторно не оплачувався</i>"
            markup = send_bid_keyboard(settings.miniapp_url, project_id) if settings.miniapp_url else None
            chunks = split_message(text)
            await waiting.edit_text(chunks[0], reply_markup=markup if len(chunks) == 1 and not drafts else None)
            for i, chunk in enumerate(chunks[1:], start=2):
                last = i == len(chunks) and not drafts
                await bot.send_message(chat_id, chunk, reply_markup=markup if last else None)
            for i, (label, draft) in enumerate(drafts, start=1):
                await bot.send_message(chat_id, f"<i>{label}:</i>")
                last = i == len(drafts)
                await bot.send_message(chat_id, escape(draft), reply_markup=markup if last else None)
        finally:
            in_progress.discard(project_id)

    @router.callback_query(ProjectAction.filter(F.action == "analyze"))
    async def analyze(
        callback: CallbackQuery,
        callback_data: ProjectAction,
        db: Database,
        settings: Settings,
        analyzer: BidAnalyzer | None,
    ) -> None:
        if analyzer is None:
            await callback.answer("Аналіз вимкнено: немає ключа Claude API", show_alert=True)
            return
        await callback.answer("Аналізую...")
        reply_to = callback.message.message_id if isinstance(callback.message, Message) else None
        await run_analysis(
            callback.bot, callback.from_user.id, reply_to, callback_data.project_id, db, settings, analyzer
        )

    @router.message(Command("analyze"))
    async def analyze_command(
        message: Message,
        command: CommandObject,
        db: Database,
        settings: Settings,
        analyzer: BidAnalyzer | None,
    ) -> None:
        if analyzer is None:
            await message.answer("Аналіз вимкнено: немає ANTHROPIC_API_KEY")
            return
        match = PROJECT_ID_RE.search(command.args or "")
        if not match:
            await message.answer("Приклад: /analyze 1661528 або /analyze посилання_на_проєкт")
            return
        await run_analysis(
            message.bot, message.chat.id, message.message_id, int(match.group(1)), db, settings, analyzer
        )

    @router.callback_query(ProjectAction.filter(F.action == "skip"))
    async def skip(callback: CallbackQuery, callback_data: ProjectAction, db: Database) -> None:
        await db.set_action(callback_data.project_id, "skip")
        if isinstance(callback.message, Message):
            await callback.message.edit_text(callback.message.html_text + "\n\n<i>Пропущено</i>")
        await callback.answer()

    @router.callback_query(ProjectAction.filter(F.action == "block"))
    async def block(callback: CallbackQuery, callback_data: ProjectAction, db: Database) -> None:
        employer = await db.project_employer(callback_data.project_id)
        if employer is None:
            await callback.answer("Замовника не знайдено", show_alert=True)
            return
        employer_id, login = employer
        await db.block_employer(employer_id, login)
        await db.set_action(callback_data.project_id, "block")
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                callback.message.html_text + f"\n\n<i>Замовника {escape(login)} заблоковано</i>"
            )
        await callback.answer("Заблоковано")

    return router
