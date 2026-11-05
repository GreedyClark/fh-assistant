import math
from dataclasses import dataclass

ROUND_TO = 50


@dataclass
class PriceOption:
    label: str
    price: int
    hourly_realistic: int
    hourly_pessimistic: int


@dataclass
class Estimate:
    optimistic_hours: float
    realistic_hours: float
    pessimistic_hours: float
    buffered_hours: float
    min_price: int
    options: list[PriceOption]
    budget_option: PriceOption | None
    budget_below_min: bool
    market_samples: int | None = None
    market_below_min: bool = False


def round_up(value: float) -> int:
    return int(math.ceil(value / ROUND_TO) * ROUND_TO)


def _option(label: str, price: float, realistic: float, pessimistic: float) -> PriceOption:
    return PriceOption(
        label=label,
        price=int(price),
        hourly_realistic=int(price / realistic) if realistic else 0,
        hourly_pessimistic=int(price / pessimistic) if pessimistic else 0,
    )


def estimate(
    analysis: dict,
    budget_uah: float | None,
    hourly_rate: int,
    buffer: float,
    market: tuple[int, int] | None = None,
) -> Estimate:
    overhead = float(analysis.get("overhead_hours") or 0)
    subtasks = analysis.get("subtasks") or []
    optimistic = sum(float(s.get("optimistic_hours") or 0) for s in subtasks) + overhead
    realistic = sum(float(s.get("realistic_hours") or 0) for s in subtasks) + overhead
    pessimistic = sum(float(s.get("pessimistic_hours") or 0) for s in subtasks) + overhead
    realistic = max(realistic, optimistic)
    pessimistic = max(pessimistic, realistic)
    buffered = realistic * buffer

    min_price = round_up(realistic * hourly_rate)
    comfort_price = round_up(max(buffered, pessimistic) * hourly_rate)
    options = [_option("мінімальна", min_price, realistic, pessimistic)]
    if market:
        options.append(_option("ринкова", round_up(market[0]), realistic, pessimistic))
    if comfort_price > min_price:
        options.append(_option("комфортна", comfort_price, realistic, pessimistic))

    budget_option = None
    if budget_uah:
        budget_option = _option("бюджет замовника", budget_uah, realistic, pessimistic)

    return Estimate(
        optimistic_hours=round(optimistic, 1),
        realistic_hours=round(realistic, 1),
        pessimistic_hours=round(pessimistic, 1),
        buffered_hours=round(buffered, 1),
        min_price=min_price,
        options=options,
        budget_option=budget_option,
        budget_below_min=bool(budget_uah) and budget_uah < min_price,
        market_samples=market[1] if market else None,
        market_below_min=bool(market) and market[0] < min_price,
    )
