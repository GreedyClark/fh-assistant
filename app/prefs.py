from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime

from app.config import DEFAULT_STOP_WORDS, KYIV, Settings
from app.db import Database


@dataclass
class Prefs:
    paused: bool = False
    min_budget_uah: int = 300
    stop_words: list[str] = field(default_factory=list)
    quiet_enabled: bool = True
    quiet_start: int = 23
    quiet_end: int = 8
    loud_threshold: int = 65
    cross_category: bool = True

    def in_quiet_hours(self, now: datetime) -> bool:
        if not self.quiet_enabled or self.quiet_start == self.quiet_end:
            return False
        hour = now.astimezone(KYIV).hour
        if self.quiet_start < self.quiet_end:
            return self.quiet_start <= hour < self.quiet_end
        return hour >= self.quiet_start or hour < self.quiet_end


class PrefsStore:
    def __init__(self, db: Database, settings: Settings):
        self._db = db
        self._settings = settings
        self.prefs = Prefs()

    async def load(self) -> None:
        defaults = Prefs(min_budget_uah=self._settings.min_budget_uah, stop_words=list(DEFAULT_STOP_WORDS))
        data = await self._db.get_setting("prefs")
        if data is None:
            self.prefs = defaults
            await self.save()
            return
        known = {f.name for f in fields(Prefs)}
        self.prefs = replace(defaults, **{k: v for k, v in data.items() if k in known})

    async def save(self) -> None:
        await self._db.set_setting("prefs", asdict(self.prefs))
