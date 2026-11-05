from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KYIV = ZoneInfo("Europe/Kyiv")

DEFAULT_STOP_WORDS = [
    "wordpress", "woocommerce", "php", "laravel", "bitrix", "битрикс", "1с", "1c",
    "opencart", "shopify", "magento", "prestashop", "joomla", "drupal", "tilda",
    "react", "vue", "angular", "node.js", "nodejs", "flutter", "swift", "kotlin", "android",
    "c#", "c++", ".net", "golang", "mql", "seo", "smm", "логотип",
    "дипломн", "курсова робота", "курсовая работа",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    fh_token: SecretStr
    bot_token: SecretStr
    allowed_user_id: int

    skill_ids: list[int] = [22, 180, 169, 99, 86, 178]
    min_budget_uah: int = 300
    poll_interval_minutes: int = 7
    max_catchup_pages: int = 10
    notify_max_age_hours: int = 72

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-haiku-5-5"
    llm_max_tokens: int = 4000
    llm_daily_limit: int = 30
    llm_input_price_per_m: float = 0.10
    llm_output_price_per_m: float = 0.50
    min_hourly_rate_uah: int = 200
    time_buffer: float = 1.5
    profile_path: Path = Path("profile.yaml")
    miniapp_url: str | None = None
    healthcheck_url: str | None = None
    alert_after_hours: float = 2
    bid_daily_limit: int = 5

    db_path: Path = Path("data/fh.db")
    log_dir: Path = Path("logs")
