from datetime import UTC, datetime

from app.config import DEFAULT_STOP_WORDS
from app.filters import classify, find_stop_word
from app.prefs import Prefs
from app.textmatch import find_term

from conftest import make_project


def prefs(**kwargs):
    return Prefs(stop_words=list(DEFAULT_STOP_WORDS), **kwargs)


def test_find_term_uses_left_word_boundary():
    assert find_term("шукаю роботу", ["бот"]) is None
    assert find_term("потрібен чат-бот", ["бот"]) == "бот"
    assert find_term("ботів у телеграм", ["бот"]) == "бот"
    assert find_term("проєкт на asp.net core", [".net"]) == ".net"
    assert find_term("сервіс на c#", ["c#"]) == "c#"


def test_stop_words():
    assert find_stop_word(make_project(name="Сайт на WordPress"), DEFAULT_STOP_WORDS) == "wordpress"
    assert find_stop_word(make_project(name="Знайти роботу"), DEFAULT_STOP_WORDS) is None


def test_my_skill_passes():
    assert classify(make_project(skills=[22]), None, {22}, prefs(), set()) == (None, False)


def test_other_category_with_my_kind_of_task_is_cross_match():
    parser = make_project(skills=[45], name="Парсер товарів з сайту в Google Sheets")
    assert classify(parser, None, {22, 180}, prefs(), set()) == (None, True)
    assert classify(parser, None, {22, 180}, prefs(cross_category=False), set()) == ("skills", False)


def test_other_category_without_my_tasks_is_rejected():
    project = make_project(skills=[45], name="Ілюстрація для роботи")
    assert classify(project, None, {22}, prefs(), set()) == ("skills", False)


def test_low_budget_rejected_and_missing_budget_kept():
    assert classify(make_project(), 200, {22}, prefs(min_budget_uah=300), set())[0] == "budget"
    assert classify(make_project(), None, {22}, prefs(min_budget_uah=300), set())[0] is None


def test_blocked_employer_and_stop_word():
    assert classify(make_project(), None, {22}, prefs(), {77})[0] is not None
    assert classify(make_project(name="Магазин на PHP"), None, {22}, prefs(), set())[0] is not None


def test_quiet_hours_cross_midnight():
    p = Prefs(quiet_enabled=True, quiet_start=23, quiet_end=8)
    assert p.in_quiet_hours(datetime(2026, 10, 29, 22, 30, tzinfo=UTC))  # 00:30 Kyiv
    assert not p.in_quiet_hours(datetime(2026, 10, 29, 10, 0, tzinfo=UTC))
    assert not Prefs(quiet_enabled=False).in_quiet_hours(datetime(2026, 10, 29, 22, 30, tzinfo=UTC))
