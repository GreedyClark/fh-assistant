import json
from collections import Counter
from datetime import datetime
from statistics import mean, median

from app.config import KYIV

MIN_MARKET_SAMPLES = 10

SKILL_NAMES = {
    22: "Python",
    180: "Розробка ботів",
    169: "Парсинг даних",
    99: "Веб-програмування",
    86: "Бази даних і SQL",
    178: "Обробка даних",
}

BID_STATUSES = {
    "submitted": "Подав",
    "won": "Виграв",
    "lost": "Програв",
    "no_reply": "Без відповіді",
    "done": "Завершив",
}


def _skills(raw: str) -> set[int]:
    try:
        return set(json.loads(raw))
    except (TypeError, ValueError):
        return set()


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def market_price(rows: list[tuple[str, float | None]], skill_ids: set[int]) -> tuple[int, int] | None:
    values = [budget for skills, budget in rows if budget and _skills(skills) & skill_ids]
    if len(values) < MIN_MARKET_SAMPLES:
        return None
    return int(median(values)), len(values)


def market_by_skill(rows: list[tuple[str, float | None]], skill_ids: list[int]) -> list[dict]:
    result = []
    for skill_id in skill_ids:
        with_skill = [budget for skills, budget in rows if skill_id in _skills(skills)]
        budgets = [b for b in with_skill if b]
        item = {
            "skill_id": skill_id,
            "name": SKILL_NAMES.get(skill_id, f"навичка {skill_id}"),
            "count": len(with_skill),
            "with_budget": len(budgets),
            "median": None,
            "low": None,
            "high": None,
        }
        if budgets:
            item["median"] = int(median(budgets))
            item["low"] = int(quantile(budgets, 0.25))
            item["high"] = int(quantile(budgets, 0.75))
        result.append(item)
    return sorted(result, key=lambda x: x["count"], reverse=True)


def hours_histogram(published: list[str]) -> list[int]:
    counts = Counter()
    for value in published:
        try:
            counts[datetime.fromisoformat(value).astimezone(KYIV).hour] += 1
        except (TypeError, ValueError):
            continue
    return [counts.get(hour, 0) for hour in range(24)]


def average_bids(bid_counts: list[int | None]) -> float | None:
    values = [b for b in bid_counts if b is not None]
    return round(mean(values), 1) if values else None


def funnel(bids: list[tuple[str, float | None, float | None, float | None]]) -> dict:
    counts = Counter(status for status, *_ in bids)
    total = len(bids)
    won = counts["won"] + counts["done"]
    decided = won + counts["lost"] + counts["no_reply"]
    prices = [price for _, price, _, _ in bids if price]
    return {
        "total": total,
        "waiting": counts["submitted"],
        "won": won,
        "lost": counts["lost"],
        "no_reply": counts["no_reply"],
        "done": counts["done"],
        "conversion": round(won / decided * 100) if decided else None,
        "avg_price": int(mean(prices)) if prices else None,
    }


def calibration(bids: list[tuple[str, float | None, float | None, float | None]]) -> dict | None:
    pairs = [(est, act) for _, _, est, act in bids if est and act]
    if not pairs:
        return None
    ratio = sum(act for _, act in pairs) / sum(est for est, _ in pairs)
    return {"ratio": round(ratio, 2), "count": len(pairs)}
