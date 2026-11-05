from datetime import UTC, datetime
from html import escape
from urllib.parse import quote

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import KYIV
from app.models import Employer, Project
from app.prefs import Prefs
from app.pricing import Estimate, PriceOption
from app.scoring import Score

DESCRIPTION_LIMIT = 400
STALE_BIDS_MINUTES = 15
TOP_MARKER_SCORE = 80

SAFE_TYPES = {
    None: "пряма оплата",
    "employer": "Сейф, комісію платить замовник",
    "developer": "Сейф, комісію платить фрілансер",
    "split": "Сейф, комісія навпіл",
    "employer_cashless": "Бізнес Сейф",
    "person": "іноземний замовник, приватна особа",
    "company": "іноземний замовник, компанія",
}


class ProjectAction(CallbackData, prefix="p"):
    action: str
    project_id: int


class SettingsAction(CallbackData, prefix="s"):
    action: str


def _num(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def format_budget(project: Project, budget_uah: float | None) -> str:
    if project.budget_amount is None:
        return "не вказано"
    text = f"{_num(project.budget_amount)} {project.budget_currency or ''}".strip()
    if project.budget_currency != "UAH" and budget_uah is not None:
        text += f" (~{_num(budget_uah)} грн)"
    return text


def format_age(published_at: datetime) -> str:
    minutes = max(int((datetime.now(UTC) - published_at).total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} хв тому"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} год тому"
    return f"{hours // 24} дн тому"


def format_employer(employer: Employer | None) -> str:
    if employer is None:
        return "прихований"
    parts = [
        escape(employer.login),
        f"рейтинг {employer.rating if employer.rating is not None else '?'}",
        f"відгуки +{employer.positive_reviews}/-{employer.negative_reviews}",
        f"завершено проєктів {employer.completed_projects}",
    ]
    if employer.average_grade is not None:
        parts.append(f"оцінка {employer.average_grade}")
    return ", ".join(parts)


def format_bids(project: Project, seen_at: datetime | None, now: datetime) -> str:
    text = f"Ставок: {project.bid_count}"
    if seen_at and (now - seen_at).total_seconds() > STALE_BIDS_MINUTES * 60:
        text += f" (станом на {seen_at.astimezone(KYIV).strftime('%H:%M')})"
    return f"{text}, опубліковано {format_age(project.published_at)}"


def score_marker(value: int, loud_threshold: int) -> str:
    if value >= max(TOP_MARKER_SCORE, loud_threshold):
        return "🔥"
    if value >= loud_threshold:
        return "‼️"
    return "❌"


def format_project(
    project: Project,
    budget_uah: float | None,
    score: Score | None = None,
    cross_category: bool = False,
    seen_at: datetime | None = None,
    loud_threshold: int = 65,
) -> str:
    safe_type = SAFE_TYPES.get(project.safe_type, f"невідомий тип ({project.safe_type})")
    description = " ".join(project.description.split())
    if len(description) > DESCRIPTION_LIMIT:
        description = description[:DESCRIPTION_LIMIT].rsplit(" ", 1)[0] + "..."

    title = f"<b>{escape(project.name)}</b>"
    if score is not None:
        title = f"{score_marker(score.value, loud_threshold)} {title}"
    lines = [title, ""]
    if score is not None:
        lines.append(f"<b>Оцінка: {score.value}/100</b>")
        if score.pros:
            lines.append(f"Плюси: {escape(', '.join(score.pros))}")
        if score.cons:
            lines.append(f"Мінуси: {escape(', '.join(score.cons))}")
        lines.append("")
    if cross_category:
        lines.append("<i>Інша категорія, але текст схожий на твої задачі</i>")
    lines += [
        f"Бюджет: {escape(format_budget(project, budget_uah))}",
        f"Оплата: {escape(safe_type)}",
        f"Навички: {escape(', '.join(name for _, name in project.skills))}",
        format_bids(project, seen_at, datetime.now(UTC)),
        f"Замовник: {format_employer(project.employer)}",
    ]
    if project.is_premium:
        lines.append("Преміум-проєкт")
    lines += ["", escape(description)]
    return "\n".join(lines)


def miniapp_link(miniapp_url: str, path: str) -> str:
    return f"{miniapp_url.rstrip('/')}/?next={quote(path, safe='/')}"


def send_bid_keyboard(miniapp_url: str, project_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Подати ставку", web_app=WebAppInfo(url=miniapp_link(miniapp_url, f"/p/{project_id}/#send")))
    return builder.as_markup()


def project_keyboard(
    project: Project, analyze_enabled: bool = False, miniapp_url: str | None = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes = []
    if project.url:
        builder.button(text="Відкрити проєкт", url=project.url)
        sizes.append(1)
    if miniapp_url:
        builder.button(
            text="Відкрити в Mini App",
            web_app=WebAppInfo(url=miniapp_link(miniapp_url, f"/p/{project.id}/")),
        )
        sizes.append(1)
    if analyze_enabled:
        builder.button(text="Аналіз ставки", callback_data=ProjectAction(action="analyze", project_id=project.id))
        sizes.append(1)
    builder.button(text="Пропустити", callback_data=ProjectAction(action="skip", project_id=project.id))
    if project.employer:
        builder.button(
            text="Заблокувати замовника",
            callback_data=ProjectAction(action="block", project_id=project.id),
        )
    sizes.append(2)
    builder.adjust(*sizes)
    return builder.as_markup()


def format_settings(prefs: Prefs) -> str:
    quiet_state = "увімкнено" if prefs.quiet_enabled else "вимкнено"
    lines = [
        "<b>Налаштування</b>",
        "",
        f"Сповіщення: {'на паузі' if prefs.paused else 'працюють'}",
        f"Мінімальний бюджет: {_num(prefs.min_budget_uah)} грн",
        f"Тихі години: {prefs.quiet_start:02d}:00-{prefs.quiet_end:02d}:00 ({quiet_state})",
        f"Стоп-слів: {len(prefs.stop_words)}",
        f"Зі звуком: оцінка від {prefs.loud_threshold}",
        f"Схожі проєкти з інших категорій: {'показувати' if prefs.cross_category else 'не показувати'}",
        "",
        "/threshold 65 - поріг оцінки для сповіщень зі звуком",
        "/minbudget 500 - змінити поріг бюджету",
        "/quiet 23-8 - змінити тихі години",
        "/stop - список стоп-слів",
        "/stop add слово, слово - додати",
        "/stop del слово - прибрати",
    ]
    return "\n".join(lines)


def settings_keyboard(prefs: Prefs) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Зняти з паузи" if prefs.paused else "Поставити на паузу",
        callback_data=SettingsAction(action="pause"),
    )
    builder.button(
        text="Вимкнути тихі години" if prefs.quiet_enabled else "Увімкнути тихі години",
        callback_data=SettingsAction(action="quiet"),
    )
    builder.button(
        text="Не показувати інші категорії" if prefs.cross_category else "Показувати інші категорії",
        callback_data=SettingsAction(action="cross"),
    )
    builder.adjust(1)
    return builder.as_markup()


TOP_MESSAGE_LIMIT = 3800


def format_top(entries: list[tuple[Project, Score, bool]], hours: int, loud_threshold: int = 65) -> str:
    if not entries:
        return f"За останні {hours} год підходящих проєктів немає"
    lines = [f"<b>Топ проєктів за {hours} год</b>", ""]
    for project, score, cross in entries:
        name = escape(project.name[:70])
        title = f'<a href="{escape(project.url)}">{name}</a>' if project.url else name
        tag = " <i>(інша категорія)</i>" if cross else ""
        marker = score_marker(score.value, loud_threshold)
        block = [f"{marker} <b>{score.value}</b> · {title}{tag}"]
        if score.pros:
            block.append(f"+ {escape(', '.join(score.pros))}")
        if score.cons:
            block.append(f"- {escape(', '.join(score.cons))}")
        block.append("")
        if len("\n".join(lines + block)) > TOP_MESSAGE_LIMIT:
            lines.append("...")
            break
        lines += block
    return "\n".join(lines).rstrip()


VERDICTS = {
    "take": "Брати",
    "take_if": "Брати за умови",
    "skip": "Пропустити",
}


def _hours(value: float) -> str:
    return f"{value:g}"


def _bullets(items: list[str]) -> list[str]:
    return [f"- {escape(str(item))}" for item in items if item]


def _price_line(option: PriceOption) -> str:
    return (
        f"<b>{_num(option.price)} грн</b> ({option.label}): "
        f"{_num(option.hourly_realistic)} грн/год реально, "
        f"{_num(option.hourly_pessimistic)} грн/год при перевитраті часу"
    )


def format_analysis(project: Project, data: dict, est: Estimate, hourly_rate: int, buffer: float) -> str:
    verdict = VERDICTS.get(data.get("verdict"), str(data.get("verdict")))
    lines = [f"<b>Аналіз: {escape(project.name[:80])}</b>", ""]
    lines.append(f"<b>Вердикт: {verdict}</b>")
    if data.get("verdict_reason"):
        lines.append(escape(data["verdict_reason"]))
    lines += _bullets(data.get("conditions") or [])

    lines += ["", "<b>Що треба зробити</b>"] + _bullets(data.get("understanding") or [])
    if data.get("unclear"):
        lines += ["", "<b>Неясно в ТЗ</b>"] + _bullets(data["unclear"])

    lines += ["", "<b>Час</b>"]
    for sub in data.get("subtasks") or []:
        lines.append(
            f"- {escape(str(sub.get('name', '')))}: "
            f"{_hours(sub.get('optimistic_hours', 0))} / {_hours(sub.get('realistic_hours', 0))} / "
            f"{_hours(sub.get('pessimistic_hours', 0))} год"
        )
    if data.get("overhead_hours"):
        lines.append(f"- уточнення, тести, правки, розгортання: {_hours(data['overhead_hours'])} год")
    lines.append(
        f"Разом: {_hours(est.optimistic_hours)} / {_hours(est.realistic_hours)} / "
        f"{_hours(est.pessimistic_hours)} год"
    )
    if data.get("unfamiliar"):
        lines.append(f"Нове для тебе: {escape(', '.join(map(str, data['unfamiliar'])))}")

    lines += [
        "",
        f"<b>Ціна</b> ({hourly_rate} грн/год; мінімальна за реальними годинами, "
        f"комфортна із запасом x{buffer:g})",
    ]
    lines += [_price_line(option) for option in est.options]
    if est.budget_option:
        lines.append(_price_line(est.budget_option))
        if est.budget_below_min:
            lines.append("Бюджет замовника нижчий за мінімальну ціну для твого часу")
    else:
        lines.append("Бюджет замовника не вказано")
    if est.market_samples:
        lines.append(f"<i>Ринкова: медіана бюджетів {est.market_samples} схожих проєктів за 30 днів</i>")
        if est.market_below_min:
            lines.append("Ринок платить менше за мінімальну ціну для твого часу")
    else:
        lines.append("<i>Ринкової ціни поки немає: замало проєктів з бюджетом</i>")

    if data.get("risks"):
        lines += ["", "<b>Ризики</b>"] + _bullets(data["risks"])
    if data.get("questions"):
        lines += ["", "<b>Питання замовнику</b>"] + _bullets(data["questions"])
    if data.get("portfolio_ref"):
        lines += ["", f"Робота з портфоліо: {escape(str(data['portfolio_ref']))}"]
    return "\n".join(lines)


def analysis_drafts(data: dict) -> list[tuple[str, str]]:
    drafts = []
    for key, label in (("draft_short", "Коротка чернетка"), ("draft_long", "Докладна чернетка")):
        text = (data.get(key) or "").strip()
        if text:
            drafts.append((label, text))
    return drafts
