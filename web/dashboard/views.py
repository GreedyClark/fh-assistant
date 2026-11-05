import logging
from datetime import UTC, datetime
from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from app.analysis import DailyLimitReached
from app.bid_rules import BID_SAFE_TYPES, check_comment, default_safe_type
from app.llm import LLMError
from app.messages import SAFE_TYPES, VERDICTS

from . import services
from .auth import make_token, require_token, user_from_init_data
from .models import Project

log = logging.getLogger(__name__)


def with_token(url: str, token: str, **params) -> str:
    query = urlencode({"t": token, **{k: v for k, v in params.items() if v is not None}})
    return f"{url}?{query}"


def safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return reverse("projects")


@require_GET
def entry(request):
    return render(request, "dashboard/entry.html", {"next": safe_next(request.GET.get("next"))})


@csrf_exempt
@require_POST
def auth(request):
    user_id = user_from_init_data(request.POST.get("init_data", ""))
    if user_id is None:
        return HttpResponseForbidden("Доступ лише для власника бота")
    return JsonResponse({"token": make_token(user_id)})


def _num(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _budget(project, budget_uah) -> str:
    if project.budget_amount is None:
        return "Бюджет не вказано"
    text = f"{_num(project.budget_amount)} {project.budget_currency or ''}".strip()
    if project.budget_currency != "UAH" and budget_uah:
        text += f" (~{_num(budget_uah)} грн)"
    return text


def plural(count: int, one: str, few: str, many: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = one
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = few
    else:
        word = many
    return f"{count} {word}"


def _bids(count: int) -> str:
    return plural(count, "ставка", "ставки", "ставок")


def _age(project) -> str:
    minutes = max(int((datetime.now(UTC) - project.published_at).total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} хв тому"
    if minutes < 24 * 60:
        return f"{minutes // 60} год тому"
    return f"{minutes // 1440} дн тому"


@require_GET
@require_token
def projects(request):
    token = request.token
    prefs = services.load_prefs()
    try:
        period = int(request.GET.get("period", 24))
    except ValueError:
        period = 24
    if period not in services.PERIODS:
        period = 24
    tier = request.GET.get("tier", "all")
    if tier not in ("all", *services.TIERS):
        tier = "all"

    items = services.recent_projects(period, prefs.loud_threshold)
    counts = {key: sum(1 for item in items if item["tier"] == key) for key in services.TIERS}
    shown = [item for item in items if tier == "all" or item["tier"] == tier]
    list_url = reverse("projects")

    filters = [{"label": f"Усі {len(items)}", "url": with_token(list_url, token, period=period), "active": tier == "all"}]
    for key in services.TIERS:
        filters.append({
            "label": f"{services.MARKERS[key]} {counts[key]}",
            "url": with_token(list_url, token, period=period, tier=key),
            "active": tier == key,
        })
    periods = [
        {"label": label, "url": with_token(list_url, token, period=hours, tier=tier), "active": hours == period}
        for hours, label in services.PERIODS.items()
    ]
    cards = [
        {
            "url": with_token(reverse("card", args=[item["project"].id]), token),
            "title": item["project"].name,
            "marker": item["marker"],
            "score": item["score"].value,
            "tier": item["tier"],
            "age": _age(item["project"]),
            "budget": _budget(item["project"], item["row"].budget_uah),
            "bids": _bids(item["project"].bid_count),
            "cross": bool(item["row"].cross_category),
        }
        for item in shown
    ]
    return render(request, "dashboard/projects.html", {
        "token": token,
        "total": len(items),
        "period_label": services.PERIODS[period],
        "periods": periods,
        "filters": filters,
        "cards": cards,
        "settings_url": with_token(reverse("settings"), token),
        "stats_url": with_token(reverse("stats"), token),
        "projects_url": with_token(list_url, token),
    })


def _card_context(request, project_id: int, error: str | None = None, send_form: dict | None = None) -> dict:
    row = Project.objects.filter(id=project_id).first()
    if row is None:
        raise Http404("Проєкт не знайдено")
    token = request.token
    prefs = services.load_prefs()
    project, score = services.scored(row)
    tier = services.tier_of(score.value, prefs.loud_threshold)
    employer = project.employer
    employer_text = "прихований"
    if employer:
        employer_text = (
            f"Рейтинг {employer.rating if employer.rating is not None else '?'} · "
            f"відгуки +{employer.positive_reviews} / −{employer.negative_reviews} · "
            f"{employer.completed_projects} проєктів"
        )

    analysis = services.get_analysis(project_id)
    est = None
    drafts = []
    prices = []
    budget_line = ""
    hours_total = ""
    if analysis:
        est = services.price_estimate(analysis, row.budget_uah, project.skill_ids)
        prices = [
            {
                "label": f"{option.label.capitalize()} ціна",
                "value": f"{_num(option.price)} ₴",
                "note": f"{_num(option.hourly_realistic)} ₴/год реально, {_num(option.hourly_pessimistic)} при перевитраті",
            }
            for option in est.options
        ]
        if est.budget_option:
            budget_line = (
                f"Бюджет замовника {_num(est.budget_option.price)} ₴: "
                f"{_num(est.budget_option.hourly_realistic)} ₴/год реально."
            )
            if est.budget_below_min:
                budget_line += " Це нижче за мінімальну ціну для твого часу."
        else:
            budget_line = "Бюджет замовника не вказано."
        if est.market_samples:
            budget_line += f" Ринкова ціна: медіана {est.market_samples} схожих проєктів за 30 днів."
            if est.market_below_min:
                budget_line += " Ринок платить менше за мінімальну ціну для твого часу."
        else:
            budget_line += " Ринкової ціни поки немає: замало проєктів з бюджетом."
        hours_total = f"{est.realistic_hours:g} год реально, {est.buffered_hours:g} із запасом"
        for key, label in (("draft_short", "Коротка чернетка"), ("draft_long", "Докладна чернетка")):
            text = (analysis.get(key) or "").strip()
            if text:
                drafts.append({"id": key, "label": label, "text": text})

    bid = services.get_bid(project_id)
    bid_view = None
    if bid:
        bid_view = {
            "status": bid.status,
            "status_label": services.stats.BID_STATUSES.get(bid.status, bid.status),
            "price": f"{_num(bid.price_uah)} ₴" if bid.price_uah else "не вказано",
            "days": bid.days,
            "note": bid.note,
            "actual_hours": bid.actual_hours,
            "submitted_at": datetime.fromisoformat(bid.submitted_at).astimezone(services.KYIV).strftime("%d.%m %H:%M"),
        }
    suggested_price = None
    if est:
        suggested_price = est.min_price

    send = None
    if bid is None:
        send = send_form or {
            "price": suggested_price or "",
            "days": "",
            "safe_type": default_safe_type(project.safe_type),
            "comment": drafts[0]["text"] if drafts else "",
        }
        send["safe_types"] = [
            {"value": value, "label": label, "selected": value == send["safe_type"]}
            for value, label in BID_SAFE_TYPES.items()
        ]
        send["left"] = max(settings.BOT.bid_daily_limit - services.api_bids_today(), 0)

    return {
        "token": token,
        "project": project,
        "bid": bid_view,
        "suggested_price": suggested_price,
        "bid_url": reverse("bid", args=[project_id]),
        "bid_status_url": reverse("bid_status", args=[project_id]),
        "send": send,
        "send_url": reverse("send_bid", args=[project_id]),
        "score": score,
        "tier": tier,
        "marker": services.MARKERS[tier],
        "age": _age(project),
        "facts": [
            {"k": "Бюджет", "v": _budget(project, row.budget_uah).replace("Бюджет не вказано", "не вказано")},
            {"k": "Ставок", "v": str(project.bid_count)},
            {"k": "Навички", "v": ", ".join(name for _, name in project.skills) or "—"},
            {"k": "Опубліковано", "v": _age(project)},
        ],
        "employer_text": employer_text,
        "safe_text": SAFE_TYPES.get(project.safe_type, f"невідомий тип ({project.safe_type})"),
        "cross": bool(row.cross_category),
        "analysis": analysis,
        "verdict": VERDICTS.get(analysis.get("verdict"), "") if analysis else "",
        "est": est,
        "prices": prices,
        "budget_line": budget_line,
        "hours_total": hours_total,
        "drafts": drafts,
        "hourly_rate": settings.BOT.min_hourly_rate_uah,
        "buffer": settings.BOT.time_buffer,
        "analysis_enabled": services.analysis_enabled(),
        "error": error,
        "back_url": with_token(reverse("projects"), token),
        "analyze_url": reverse("analyze", args=[project_id]),
        "skip_url": reverse("skip", args=[project_id]),
        "block_url": reverse("block", args=[project_id]),
    }


@require_GET
@require_token
def card(request, project_id: int):
    return render(request, "dashboard/card.html", _card_context(request, project_id))


@csrf_exempt
@require_POST
@require_token
def analyze(request, project_id: int):
    row = Project.objects.filter(id=project_id).first()
    if row is None:
        raise Http404("Проєкт не знайдено")
    if not services.analysis_enabled():
        return HttpResponseBadRequest("Аналіз вимкнено")
    error = None
    try:
        project, _ = services.scored(row)
        services.run_analysis(project, row.budget_uah, refresh=request.POST.get("refresh") == "1")
    except DailyLimitReached:
        error = "Денний ліміт аналізів вичерпано"
    except LLMError as exc:
        log.warning("Analysis failed for %s: %s", project_id, exc)
        error = f"Не вдалося зробити аналіз: {exc}"[:300]
    except Exception:
        log.exception("Unexpected analysis error for %s", project_id)
        error = "Не вдалося зробити аналіз, деталі в логах"
    if error:
        return render(request, "dashboard/card.html", _card_context(request, project_id, error))
    return redirect(with_token(reverse("card", args=[project_id]), request.token) + "#analysis")


@csrf_exempt
@require_POST
@require_token
def skip(request, project_id: int):
    services.skip_project(project_id)
    return redirect(with_token(reverse("projects"), request.token))


@csrf_exempt
@require_POST
@require_token
def block(request, project_id: int):
    services.block_employer(project_id)
    return redirect(with_token(reverse("projects"), request.token))


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


@csrf_exempt
@require_token
def settings_view(request):
    token = request.token
    prefs = services.load_prefs()
    saved = False
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "remove_word":
            word = request.POST.get("word", "")
            prefs.stop_words = [w for w in prefs.stop_words if w != word]
        elif action == "add_word":
            for word in request.POST.get("word", "").split(","):
                word = word.strip().lower()
                if word and word not in prefs.stop_words:
                    prefs.stop_words.append(word)
        else:
            prefs.paused = request.POST.get("paused") == "on"
            prefs.quiet_enabled = request.POST.get("quiet_enabled") == "on"
            prefs.cross_category = request.POST.get("cross_category") == "on"
            prefs.quiet_start = _int(request.POST.get("quiet_start"), prefs.quiet_start, 0, 23)
            prefs.quiet_end = _int(request.POST.get("quiet_end"), prefs.quiet_end, 0, 23)
            prefs.loud_threshold = _int(request.POST.get("loud_threshold"), prefs.loud_threshold, 0, 100)
            prefs.min_budget_uah = _int(request.POST.get("min_budget_uah"), prefs.min_budget_uah, 0, 1_000_000)
            saved = True
        services.save_prefs(prefs)

    return render(request, "dashboard/settings.html", {
        "token": token,
        "prefs": prefs,
        "hot_from": max(services.TOP_MARKER_SCORE, prefs.loud_threshold),
        "usage": services.analysis_usage(),
        "saved": saved,
        "settings_action": reverse("settings"),
        "projects_url": with_token(reverse("projects"), token),
        "settings_url": with_token(reverse("settings"), token),
        "stats_url": with_token(reverse("stats"), token),
    })


def _float(value: str | None, low: float, high: float) -> float | None:
    try:
        number = float((value or "").replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return number if low <= number <= high else None


@csrf_exempt
@require_POST
@require_token
def bid(request, project_id: int):
    row = Project.objects.filter(id=project_id).first()
    if row is None:
        raise Http404("Проєкт не знайдено")
    analysis = services.get_analysis(project_id)
    estimated = None
    if analysis:
        estimated = services.price_estimate(analysis, row.budget_uah).realistic_hours
    days = _float(request.POST.get("days"), 1, 365)
    services.save_bid(
        project_id,
        _float(request.POST.get("price"), 1, 10_000_000),
        int(days) if days else None,
        (request.POST.get("note") or "").strip()[:1000],
        estimated,
    )
    return redirect(with_token(reverse("card", args=[project_id]), request.token) + "#bid")


@csrf_exempt
@require_POST
@require_token
def send_bid(request, project_id: int):
    row = Project.objects.filter(id=project_id).first()
    if row is None:
        raise Http404("Проєкт не знайдено")
    comment = (request.POST.get("comment") or "").strip()
    price = _float(request.POST.get("price"), 1, 10_000_000)
    days = _float(request.POST.get("days"), 1, 365)
    safe_type = request.POST.get("safe_type")
    form = {
        "price": request.POST.get("price", ""),
        "days": request.POST.get("days", ""),
        "safe_type": safe_type,
        "comment": comment,
    }

    problems = []
    if services.get_bid(project_id):
        problems.append("Ставку на цей проєкт уже відмічено")
    if services.api_bids_today() >= settings.BOT.bid_daily_limit:
        problems.append(f"Ліміт {settings.BOT.bid_daily_limit} ставок через бота на сьогодні вичерпано")
    if price is None:
        problems.append("Вкажи ціну")
    if days is None:
        problems.append("Вкажи термін від 1 до 365 днів")
    if safe_type not in BID_SAFE_TYPES:
        problems.append("Обери тип угоди")
    problems += check_comment(comment)

    if not problems:
        try:
            services.send_bid(project_id, int(price), int(days), safe_type, comment)
        except services.BidSendError as exc:
            problems.append(str(exc))

    if problems:
        context = _card_context(request, project_id, "; ".join(problems), form)
        return render(request, "dashboard/card.html", context)

    analysis = services.get_analysis(project_id)
    estimated = services.price_estimate(analysis, row.budget_uah).realistic_hours if analysis else None
    services.save_bid(project_id, price, int(days), "", estimated, source="api")
    return redirect(with_token(reverse("card", args=[project_id]), request.token) + "#bid")


@csrf_exempt
@require_POST
@require_token
def bid_status(request, project_id: int):
    status = request.POST.get("status")
    if status not in services.stats.BID_STATUSES:
        return HttpResponseBadRequest("Невідомий статус")
    hours = _float(request.POST.get("actual_hours"), 0.1, 10_000) if status == "done" else None
    services.set_bid_status(project_id, status, hours)
    return redirect(with_token(reverse("card", args=[project_id]), request.token) + "#bid")


@require_GET
@require_token
def stats_view(request):
    token = request.token
    services.refresh_stale_bids()
    data = services.dashboard_stats()
    journal = services.bid_journal()
    for item in journal:
        item["url"] = with_token(reverse("card", args=[item["project_id"]]), token)
        item["price_text"] = f"{_num(item['price'])} ₴" if item["price"] else ""
        item["date"] = item["submitted_at"].strftime("%d.%m")
    funnel = data["funnel"]
    if funnel["avg_price"]:
        funnel["avg_price_text"] = f"{_num(funnel['avg_price'])} ₴"
    for m in data["market"]:
        m["count_text"] = plural(m["count"], "проєкт", "проєкти", "проєктів")
        if m["median"]:
            m["median_text"] = f"{_num(m['median'])} ₴"
            m["range_text"] = f"{_num(m['low'])}–{_num(m['high'])} ₴"
    calibration = data["calibration"]
    advice = None
    buffer_text = f"{settings.BOT.time_buffer:g}".replace(".", ",")
    if calibration:
        if calibration["ratio"] > settings.BOT.time_buffer:
            advice = f"Реальні години більші за запас x{buffer_text}. Варто збільшити запас."
        elif calibration["ratio"] < 1:
            advice = "Ти вкладаєшся швидше за оцінку. Запас можна залишити або трохи зменшити."
        else:
            advice = f"Запас x{buffer_text} покриває реальні години."
    return render(request, "dashboard/stats.html", {
        "token": token,
        "funnel": funnel,
        "calibration": calibration,
        "advice": advice,
        "market": data["market"],
        "hours": data["hours"],
        "avg_bids": data["avg_bids"],
        "matched_count": data["matched_count"],
        "journal": journal,
        "projects_url": with_token(reverse("projects"), token),
        "settings_url": with_token(reverse("settings"), token),
        "stats_url": with_token(reverse("stats"), token),
    })
