import asyncio
import json
import logging

import requests
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db.models import Sum

from app.analysis import BidAnalyzer
from app.config import DEFAULT_STOP_WORDS, KYIV
from app.db import Database
from app.llm import AnthropicClient
from app.models import Project as ProjectData
from app.models import parse_project
from app.prefs import Prefs
from app.pricing import Estimate, estimate
from app.scoring import Score, score_project
from app import stats
from app.fh_client import BASE_URL

from .models import Analysis, Bid, BlockedEmployer, Project, Setting

PERIODS = {24: "24 год", 72: "3 дні", 168: "7 днів"}
TOP_MARKER_SCORE = 80
TIERS = ("hot", "good", "weak")
MARKERS = {"hot": "🔥", "good": "‼️", "weak": "❌"}

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


def load_prefs() -> Prefs:
    defaults = Prefs(min_budget_uah=settings.BOT.min_budget_uah, stop_words=list(DEFAULT_STOP_WORDS))
    row = Setting.objects.filter(key="prefs").first()
    if row is None:
        return defaults
    data = json.loads(row.value)
    known = {f.name for f in fields(Prefs)}
    return replace(defaults, **{k: v for k, v in data.items() if k in known})


def save_prefs(prefs: Prefs) -> None:
    Setting.objects.update_or_create(key="prefs", defaults={"value": json.dumps(asdict(prefs), ensure_ascii=False)})


def tier_of(score: int, threshold: int) -> str:
    if score >= max(TOP_MARKER_SCORE, threshold):
        return "hot"
    if score >= threshold:
        return "good"
    return "weak"


def scored(row: Project) -> tuple[ProjectData, Score]:
    project = parse_project(json.loads(row.raw))
    seen_at = datetime.fromisoformat(row.first_seen_at)
    return project, score_project(project, row.budget_uah, seen_at, bool(row.cross_category))


def recent_projects(hours: int, threshold: int) -> list[dict]:
    since = _utc_iso(datetime.now(UTC) - timedelta(hours=hours))
    blocked = BlockedEmployer.objects.values_list("employer_id", flat=True)
    rows = (
        Project.objects.filter(matched=1, first_seen_at__gte=since)
        .exclude(employer_id__in=blocked)
        .exclude(action__in=["skip", "block"])
    )
    items = []
    for row in rows:
        project, score = scored(row)
        tier = tier_of(score.value, threshold)
        items.append({"row": row, "project": project, "score": score, "tier": tier, "marker": MARKERS[tier]})
    items.sort(key=lambda item: item["score"].value, reverse=True)
    return items


def get_analysis(project_id: int) -> dict | None:
    row = Analysis.objects.filter(project_id=project_id).first()
    return json.loads(row.result) if row else None


def market_rows(days: int = 30) -> list[tuple[str, float | None]]:
    since = _utc_iso(datetime.now(UTC) - timedelta(days=days))
    return list(Project.objects.filter(first_seen_at__gte=since).values_list("skill_ids", "budget_uah"))


def price_estimate(analysis: dict, budget_uah: float | None, skill_ids: set[int] | None = None) -> Estimate:
    market = stats.market_price(market_rows(), skill_ids) if skill_ids else None
    return estimate(analysis, budget_uah, settings.BOT.min_hourly_rate_uah, settings.BOT.time_buffer, market)


def analysis_enabled() -> bool:
    key = settings.BOT.anthropic_api_key
    return bool(key and key.get_secret_value())


async def _analyze(project: ProjectData, budget_uah: float | None, refresh: bool = False) -> dict:
    bot = settings.BOT
    db = Database(settings.BOT_DB_PATH)
    await db.connect()
    try:
        llm = AnthropicClient(bot.anthropic_api_key.get_secret_value(), bot.llm_model, bot.llm_max_tokens)
        analyzer = BidAnalyzer(llm, db, settings.PROFILE_PATH, bot.llm_daily_limit)
        record = await analyzer.analyze(project, budget_uah, refresh)
        return record.data
    finally:
        await db.close()


def run_analysis(project: ProjectData, budget_uah: float | None, refresh: bool = False) -> dict:
    return asyncio.run(_analyze(project, budget_uah, refresh))


def analysis_usage() -> dict:
    bot = settings.BOT
    today_start = datetime.now(KYIV).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = datetime.now(UTC) - timedelta(days=30)
    today = Analysis.objects.filter(created_at__gte=_utc_iso(today_start)).count()
    totals = Analysis.objects.filter(created_at__gte=_utc_iso(month_start)).aggregate(
        tokens_in=Sum("input_tokens"), tokens_out=Sum("output_tokens")
    )
    cost = (
        (totals["tokens_in"] or 0) * bot.llm_input_price_per_m
        + (totals["tokens_out"] or 0) * bot.llm_output_price_per_m
    ) / 1_000_000
    return {"today": today, "limit": bot.llm_daily_limit, "cost": cost}


def skip_project(project_id: int) -> None:
    Project.objects.filter(id=project_id).update(action="skip")


def block_employer(project_id: int) -> str | None:
    row = Project.objects.filter(id=project_id, employer_id__isnull=False).first()
    if row is None:
        return None
    BlockedEmployer.objects.get_or_create(
        employer_id=row.employer_id,
        defaults={"login": row.employer_login, "blocked_at": _utc_iso(datetime.now(UTC))},
    )
    Project.objects.filter(id=project_id).update(action="block")
    return row.employer_login or ""


def get_bid(project_id: int) -> Bid | None:
    return Bid.objects.filter(project_id=project_id).first()


def save_bid(
    project_id: int,
    price: float | None,
    days: int | None,
    note: str,
    estimated_hours: float | None,
    source: str = "manual",
) -> None:
    now = _utc_iso(datetime.now(UTC))
    Bid.objects.update_or_create(
        project_id=project_id,
        defaults={
            "status": "submitted",
            "source": source,
            "price_uah": price,
            "days": days,
            "note": note or None,
            "estimated_hours": estimated_hours,
            "submitted_at": now,
            "updated_at": now,
        },
    )


def set_bid_status(project_id: int, status: str, actual_hours: float | None = None) -> None:
    fields = {"status": status, "updated_at": _utc_iso(datetime.now(UTC))}
    if actual_hours is not None:
        fields["actual_hours"] = actual_hours
    Bid.objects.filter(project_id=project_id).update(**fields)


def refresh_stale_bids() -> int:
    now = datetime.now(UTC)
    stale = []
    for bid in Bid.objects.filter(status="submitted"):
        row = Project.objects.filter(id=bid.project_id).only("raw").first()
        if row is None:
            continue
        expired = json.loads(row.raw).get("attributes", {}).get("expired_at")
        if expired and datetime.fromisoformat(expired) < now:
            stale.append(bid.project_id)
    if stale:
        Bid.objects.filter(project_id__in=stale).update(status="no_reply", updated_at=_utc_iso(now))
    return len(stale)


def bid_journal() -> list[dict]:
    bids = list(Bid.objects.order_by("-submitted_at"))
    names = dict(Project.objects.filter(id__in=[b.project_id for b in bids]).values_list("id", "name"))
    return [
        {
            "project_id": bid.project_id,
            "name": names.get(bid.project_id, f"Проєкт {bid.project_id}"),
            "status": bid.status,
            "status_label": stats.BID_STATUSES.get(bid.status, bid.status),
            "price": bid.price_uah,
            "submitted_at": datetime.fromisoformat(bid.submitted_at).astimezone(KYIV),
        }
        for bid in bids
    ]


def dashboard_stats(days: int = 30) -> dict:
    bids = list(Bid.objects.values_list("status", "price_uah", "estimated_hours", "actual_hours"))
    since = _utc_iso(datetime.now(UTC) - timedelta(days=days))
    matched = list(Project.objects.filter(matched=1, first_seen_at__gte=since).values_list("published_at", "bid_count"))
    hours = stats.hours_histogram([published for published, _ in matched])
    peak = max(hours) if any(hours) else 0
    return {
        "funnel": stats.funnel(bids),
        "calibration": stats.calibration(bids),
        "market": [m for m in stats.market_by_skill(market_rows(days), settings.BOT.skill_ids) if m["count"]],
        "hours": [
            {"hour": hour, "count": count, "height": round(count / peak * 100) if peak else 0}
            for hour, count in enumerate(hours)
        ],
        "avg_bids": stats.average_bids([b for _, b in matched]),
        "matched_count": len(matched),
    }


class BidSendError(Exception):
    pass


def api_bids_today() -> int:
    start = datetime.now(KYIV).replace(hour=0, minute=0, second=0, microsecond=0)
    return Bid.objects.filter(source="api", submitted_at__gte=_utc_iso(start)).count()


def _api_error(resp: requests.Response) -> str:
    try:
        error = resp.json().get("error") or {}
    except ValueError:
        error = {}
    text = error.get("detail") or error.get("title") or resp.text[:200]
    return f"Freelancehunt відповів {resp.status_code}: {text}"


def send_bid(project_id: int, price: int, days: int, safe_type: str, comment: str) -> None:
    payload = {
        "days": days,
        "safe_type": safe_type,
        "budget": {"amount": price, "currency": "UAH"},
        "comment": comment,
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/projects/{project_id}/bids",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.BOT.fh_token.get_secret_value()}",
                "Accept-Language": "uk",
                "Accept": "application/json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        log.warning("Bid request failed for %s: %s", project_id, exc)
        raise BidSendError("Не вдалося з'єднатися з Freelancehunt, спробуй ще раз") from exc
    if resp.status_code >= 400:
        message = _api_error(resp)
        log.warning("Bid rejected for %s: %s", project_id, message)
        raise BidSendError(message)
    log.info("Bid sent for project %s: %s UAH, %s days", project_id, price, days)
