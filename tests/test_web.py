import json
import os
import sqlite3
from pathlib import Path

import django
import pytest
import requests
from init_data_py import sign

from app.db import Database

from conftest import make_project, run

django.setup()

from django.test import Client  # noqa: E402

DB = Path(os.environ["DB_PATH"])
GOOD = "Зроблю бота на aiogram 3 за 5 днів. Приклад: https://github.com/GreedyClark/currency-bot. Яка у вас база?"


async def _seed():
    db = Database(DB)
    await db.connect()
    for pid in range(7001, 7007):
        await db.insert_project(make_project(pid, name=f"Telegram бот {pid}", desc="Telegram бот aiogram" + " опис" * 60), None, None)
    await db.close()


@pytest.fixture(scope="module")
def client():
    run(_seed())
    return Client(SERVER_NAME="example.ts.net")


@pytest.fixture(scope="module")
def token(client):
    init_data = sign({"user": json.dumps({"id": 42, "first_name": "A"})}, "123:TEST")
    return client.post("/auth/", {"init_data": init_data}).json()["token"]


@pytest.fixture
def conn():
    connection = sqlite3.connect(DB)
    yield connection
    connection.close()


def add_analysis(conn, pid, data):
    conn.execute(
        "INSERT OR REPLACE INTO analyses VALUES (?,?,?,?,?,?,?)",
        (pid, json.dumps(data, ensure_ascii=False), "m", 1, 1, 0, "2099-01-01T00:00:00+00:00"),
    )
    conn.commit()


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


@pytest.fixture
def fake_post(monkeypatch):
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        if "7003" in url:
            return Resp(422, {"error": {"status": 422, "title": "Unprocessable", "detail": "Проєкт закрито"}})
        return Resp(201, {"data": {}})

    monkeypatch.setattr(requests, "post", post)
    return calls


def test_foreign_init_data_rejected(client):
    init_data = sign({"user": json.dumps({"id": 1, "first_name": "B"})}, "123:TEST")
    assert client.post("/auth/", {"init_data": init_data}).status_code == 403
    assert client.post("/auth/", {"init_data": "user=x&hash=bad"}).status_code == 403


def test_pages_require_token(client, token):
    assert client.get("/projects/").status_code == 401
    for page in ("/projects/", "/stats/", "/settings/", "/p/7001/"):
        assert client.get(page, {"t": token}).status_code == 200


def test_send_form_without_analysis(client, token):
    html = client.get("/p/7006/", {"t": token}).content.decode()
    assert 'id="send"' in html and "Напиши текст ставки" in html


def test_send_bid_validates_and_posts(client, token, conn, sample_analysis, fake_post):
    add_analysis(conn, 7001, sample_analysis)
    html = client.get("/p/7001/", {"t": token}).content.decode()
    assert "Надіслати на Freelancehunt" in html and 'data-fill="draft-draft_long"' in html

    bad = {"t": token, "price": "1500", "days": "4", "safe_type": "employer", "comment": "пишіть @greedyklark, 1500 грн"}
    html = client.post("/p/7001/send/", bad).content.decode()
    assert "контакти" in html and "Ціну вказуй" in html and not fake_post

    ok = {"t": token, "price": "1500.00", "days": "4", "safe_type": "employer", "comment": GOOD}
    response = client.post("/p/7001/send/", ok)
    assert response.status_code == 302
    url, body, headers = fake_post[-1]
    assert url.endswith("/projects/7001/bids") and headers["Authorization"] == "Bearer fh-test-token"
    assert body == {"days": 4, "safe_type": "employer", "budget": {"amount": 1500, "currency": "UAH"}, "comment": GOOD}
    row = conn.execute("SELECT status, price_uah, days, source FROM bids WHERE project_id=7001").fetchone()
    assert row == ("submitted", 1500.0, 4, "api")

    html = client.post("/p/7001/send/", ok).content.decode()
    assert "уже відмічено" in html and len(fake_post) == 1


def test_send_bid_shows_api_error(client, token, conn, fake_post):
    ok = {"t": token, "price": "1500", "days": "4", "safe_type": "employer", "comment": GOOD}
    html = client.post("/p/7003/send/", ok).content.decode()
    assert "Проєкт закрито" in html
    assert conn.execute("SELECT count(*) FROM bids WHERE project_id=7003").fetchone()[0] == 0


def test_manual_bid_and_status_flow(client, token, conn):
    client.post("/p/7002/bid/", {"t": token, "price": "2 500", "days": "5", "note": "демо"})
    assert conn.execute("SELECT status, price_uah, days FROM bids WHERE project_id=7002").fetchone() == ("submitted", 2500.0, 5)
    assert client.post("/p/7002/bid/status/", {"t": token, "status": "evil"}).status_code == 400
    client.post("/p/7002/bid/status/", {"t": token, "status": "won"})
    client.post("/p/7002/bid/status/", {"t": token, "status": "done", "actual_hours": "13"})
    assert conn.execute("SELECT status, actual_hours FROM bids WHERE project_id=7002").fetchone() == ("done", 13.0)


def test_settings_saved_for_bot(client, token, conn):
    client.post("/settings/", {"t": token, "loud_threshold": "70", "min_budget_uah": "500", "quiet_start": "22", "quiet_end": "7"})
    prefs = json.loads(conn.execute("SELECT value FROM settings WHERE key='prefs'").fetchone()[0])
    assert prefs["loud_threshold"] == 70 and prefs["min_budget_uah"] == 500 and prefs["quiet_start"] == 22


def test_skip_verdict_still_shows_drafts(client, token, conn, sample_analysis):
    add_analysis(conn, 7004, {**sample_analysis, "verdict": "skip"})
    html = client.get("/p/7004/", {"t": token}).content.decode()
    assert "Коротка чернетка" in html and "Вердикт «пропустити»" in html and "Повторити аналіз" in html


def test_old_analysis_without_drafts_offers_refresh(client, token, conn, sample_analysis):
    add_analysis(conn, 7005, {**sample_analysis, "verdict": "skip", "draft_short": None, "draft_long": None})
    html = client.get("/p/7005/", {"t": token}).content.decode()
    assert "Написати чернетки" in html and 'name="refresh" value="1"' in html


def test_refresh_bypasses_cache(monkeypatch, client, token):
    from dashboard import services

    calls = []
    monkeypatch.setattr(services, "analysis_enabled", lambda: True)
    monkeypatch.setattr(services, "run_analysis", lambda project, budget, refresh=False: calls.append(refresh))
    client.post("/p/7005/analyze/", {"t": token, "refresh": "1"})
    client.post("/p/7005/analyze/", {"t": token})
    assert calls == [True, False]
