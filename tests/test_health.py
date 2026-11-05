from datetime import UTC, datetime, timedelta

import anthropic
import pytest

from app.health import Health
from app.llm import classify_api_error

from conftest import run

try:
    import httpx
except ImportError:
    import httpx2 as httpx

T0 = datetime(2026, 10, 29, 10, tzinfo=UTC)


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append(text)


class Resp:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Session:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return Resp()


@pytest.fixture
def health():
    return Health(Bot(), 42, Session(), "https://hc-ping.com/abc/", timedelta(hours=2))


def test_success_pings_healthchecks(health):
    run(health.poll_ok())
    assert health._session.urls == ["https://hc-ping.com/abc"] and health.last_ping_ok


def test_alert_after_two_hours_once_and_recovery(health):
    async def scenario():
        await health.poll_failed("Timeout <x>", now=T0)
        await health.poll_failed("Timeout <x>", now=T0 + timedelta(hours=1))
        assert health._bot.sent == []
        await health.poll_failed("Timeout <x>", now=T0 + timedelta(hours=2, minutes=5))
        await health.poll_failed("Timeout <x>", now=T0 + timedelta(hours=3))
        assert len(health._bot.sent) == 1 and "&lt;x&gt;" in health._bot.sent[0]
        assert health._session.urls[-1].endswith("/fail")
        await health.poll_ok()
        await health.poll_ok()
        assert len(health._bot.sent) == 2 and "знову працює" in health._bot.sent[1]

    run(scenario())


def test_auth_failure_alerts_immediately(health):
    run(health.poll_failed("HTTP 401", auth=True, now=T0))
    run(health.poll_failed("HTTP 401", auth=True, now=T0))
    assert len(health._bot.sent) == 1 and "токен" in health._bot.sent[0]


def test_no_ping_without_url():
    session = Session()
    health = Health(Bot(), 42, session, None)
    run(health.poll_ok())
    assert session.urls == [] and not health.ping_enabled


def test_anthropic_errors_get_readable_text():
    req = httpx.Request("POST", "https://api.anthropic.com")
    billing = anthropic.BadRequestError(
        "Your credit balance is too low", response=httpx.Response(400, request=req), body=None
    )
    auth = anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=req), body=None)
    assert classify_api_error(billing)[0] == "llm_billing"
    assert classify_api_error(auth)[0] == "llm_auth"
