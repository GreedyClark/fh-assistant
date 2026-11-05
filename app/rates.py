import logging

import aiohttp

from app.db import Database

NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"

log = logging.getLogger(__name__)


class Rates:
    def __init__(self, session: aiohttp.ClientSession, db: Database):
        self._session = session
        self._db = db
        self._rates: dict[str, float] = {"UAH": 1.0}

    async def load(self) -> None:
        self._rates.update(await self._db.get_rates())
        if len(self._rates) == 1:
            await self.refresh()

    async def refresh(self) -> None:
        try:
            async with self._session.get(NBU_URL) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("NBU rates refresh failed: %s", exc)
            return

        rates = {row["cc"]: float(row["rate"]) for row in data if row.get("cc") and row.get("rate")}
        if rates:
            self._rates.update(rates)
            await self._db.save_rates(rates)
            log.info("Loaded %d exchange rates", len(rates))

    def to_uah(self, amount: float | None, currency: str | None) -> float | None:
        if amount is None or not currency:
            return None
        rate = self._rates.get(currency.upper())
        return amount * rate if rate else None
