import pytest

from app.bid_rules import check_comment, default_safe_type

GOOD = "Зроблю бота на aiogram 3 за 5 днів. Приклад: https://github.com/GreedyClark/currency-bot. Яка у вас база?"


def test_clean_comment_passes():
    assert check_comment(GOOD) == []


@pytest.mark.parametrize("text", [
    "Пишіть у телеграм @greedyklark",
    "мій номер +380 67 123 45 67",
    "a@b.com",
    "t.me/someone",
    "Viber є",
])
def test_contacts_blocked(text):
    assert any("контакти" in p for p in check_comment(text))


@pytest.mark.parametrize("text", ["зроблю за 2000 грн", "всього $50", "ціна 100 USD"])
def test_prices_blocked(text):
    assert any("Ціну" in p for p in check_comment(text))


def test_empty_and_long():
    assert check_comment("   ")
    assert check_comment("а" * 5000)


def test_default_safe_type():
    assert default_safe_type("split") == "split"
    assert default_safe_type("person") == "employer"
    assert default_safe_type(None) == "employer"
