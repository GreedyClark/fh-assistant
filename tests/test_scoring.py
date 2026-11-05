from datetime import UTC, datetime

from app.scoring import score_project

from conftest import make_project

NOW = datetime.now(UTC)


def test_good_bot_project_scores_high():
    project = make_project(
        skills=[180], name="Telegram-бот для запису клієнтів на aiogram", bids=1,
        budget={"amount": 3000, "currency": "UAH"},
    )
    score = score_project(project, 3000, NOW)
    assert score.value >= 80
    assert "Telegram-бот" in score.pros


def test_red_flags_drop_score():
    employer = {"id": 5, "login": "x", "negative_reviews": 2, "positive_reviews": 0, "completed_projects": 1}
    project = make_project(
        name="Python скрипт", desc="Треба тестове завдання безкоштовно, пишіть в телеграм @someuser123",
        bids=25, employer=employer,
    )
    score = score_project(project, None, NOW)
    assert score.value < 30
    assert any("тестове" in c for c in score.cons)
    assert any("поза біржею" in c for c in score.cons)


def test_unfamiliar_stack_is_penalised():
    score = score_project(make_project(name="Нейромережа для computer vision на Python", bids=8), None, NOW)
    assert any("незнайомий" in c for c in score.cons)


def test_old_project_without_safe():
    score = score_project(make_project(age_hours=50, safe=None, bids=4), None, NOW)
    assert "без Сейфу" in score.cons and "старий" in score.cons


def test_score_is_bounded():
    for bids in (0, 5, 100):
        value = score_project(make_project(bids=bids), None, NOW).value
        assert 0 <= value <= 100
