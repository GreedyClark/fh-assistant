import json

import aiohttp
import pytest

from app.fh_client import FreelancehuntClient
from app.models import parse_project

from conftest import DATA, run


def page():
    return json.loads((DATA / "projects_page.json").read_text(encoding="utf-8"))


def test_parse_full_project():
    project = parse_project(page()["data"][0])
    assert project.id == 1662001
    assert project.skill_ids == {180, 22}
    assert project.budget_amount == 4000 and project.budget_currency == "UAH"
    assert project.employer.login == "salon_owner" and project.employer.positive_reviews == 3
    assert project.url.endswith("1662001.html")
    assert project.expired_at > project.published_at


def test_parse_project_without_employer_and_expiry():
    project = parse_project(page()["data"][1])
    assert project.employer is None
    assert project.expired_at is None
    assert project.safe_type == "person"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._body

    async def text(self):
        return json.dumps(self._body)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, headers=None):
        self.requests.append((url, headers))
        return FakeResponse(*self.responses.pop(0))


def test_client_skips_broken_items_and_returns_next_link():
    session = FakeSession([(200, page())])
    projects, next_url = run(FreelancehuntClient("tok", session).projects_page())
    assert [p.id for p in projects] == [1662001, 1662000]
    assert next_url.endswith("page%5Bnumber%5D=2")
    assert session.requests[0][1]["Authorization"] == "Bearer tok"


def test_client_raises_rate_limited():
    from app.fh_client import RateLimited

    with pytest.raises(RateLimited):
        run(FreelancehuntClient("tok", FakeSession([(429, {})])).projects_page())


def test_client_keeps_status_on_auth_error():
    from app.fh_client import FHError

    with pytest.raises(FHError) as info:
        run(FreelancehuntClient("tok", FakeSession([(401, {"error": {"title": "Unauthorized"}})])).projects_page())
    assert info.value.status == 401


def test_client_retries_server_errors(monkeypatch):
    monkeypatch.setattr(FreelancehuntClient._get.retry, "sleep", lambda _: _noop())
    session = FakeSession([(502, {}), (200, page())])
    projects, _ = run(FreelancehuntClient("tok", session).projects_page())
    assert len(projects) == 2 and len(session.requests) == 2


async def _noop():
    return None


assert aiohttp
