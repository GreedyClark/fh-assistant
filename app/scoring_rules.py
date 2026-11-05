CORE_SKILL_IDS = {22, 180, 169}

BASE_SCORE = 45

BOT_TERMS = ("бот", "bot", "чат-бот")
TELEGRAM_TERMS = ("telegram", "телеграм", "телеграмм", "тг-бот", "tg-бот", "aiogram")

KEYWORD_GROUPS = [
    ("Telegram-бот", (TELEGRAM_TERMS, BOT_TERMS), 15),
    ("парсинг", (("парс", "pars", "scrap", "скрап", "скрейп", "beautifulsoup", "bs4"),), 12),
    ("Django", (("django",),), 12),
    ("Python", (("python", "пайтон", "питон"),), 6),
    ("інтеграція з API", (("api", "інтеграц", "интеграц", "webhook", "вебхук"),), 6),
    ("автоматизація", (("автоматиз", "скрипт", "script"),), 5),
    ("бази даних", (("sql", "база даних", "бази даних", "базу даних", "база данных", "базы данных", "базу данных"),), 4),
]
KEYWORD_CAP = 25

CROSS_CATEGORY_GROUPS = {"Telegram-бот", "парсинг", "Django"}

UNFAMILIAR_TERMS = (
    "machine learning", "машинне навчання", "машинного навчання", "машинное обучение",
    "нейромереж", "нейросет", "computer vision", "mobile app",
    "мобільний додаток", "мобільного додатку", "мобільний застосунок", "мобільного застосунку",
    "мобильное приложение", "мобильного приложения",
    "blockchain", "блокчейн", "web3", "solidity", "смарт-контракт", "smart contract", "3d",
    "stablecoin", "crypto", "крипто", "криптовал", "defi", "nft", "evm", "rust",
)
UNFAMILIAR_PENALTY = 12
UNFAMILIAR_CAP = 24
NO_KEYWORDS_PENALTY = 8

BID_TIERS = [
    (2, 15, "мало ставок"),
    (5, 8, "небагато ставок"),
    (10, 0, None),
    (20, -10, "багато ставок"),
]
BID_MAX_PENALTY = -20

RED_FLAG_PENALTY = 15
FREE_TEST_TERMS = ("тестове завдання", "тестового завдання", "тестовое задание", "тестового задания", "test task")
FREE_TERMS = ("безкоштовн", "бесплатн", "без оплати", "без оплаты", "for free", "free of charge", "unpaid")
PERCENT_TERMS = (
    "відсот", "процент", "% від", "% от", "від продаж", "от продаж",
    "після результат", "после результат", "revenue share",
)
REVIEW_PAY_TERMS = ("за відгук", "за отзыв", "за хороший відгук", "за хороший отзыв")
OFF_PLATFORM_TERMS = (
    "whatsapp", "ватсап", "viber", "вайбер", "t.me/", "skype",
    "пишіть в телеграм", "пишите в телеграм", "напишіть в телеграм", "напишите в телеграм",
    "пишіть у телеграм", "напишіть у телеграм",
)
CONTACT_REGEXES = (
    r"(?<![\w.])@[a-z0-9_]{5,}",
    r"[\w.+-]+@[\w-]+\.[a-z]{2,}",
    r"\+?380\d{9}",
)
URGENT_TERMS = ("терміново", "срочно", "сьогодні", "сегодня", "до завтра", "за день", "за 1 день", "asap", "urgent")
URGENT_BUDGET_UAH = 1500
URGENT_PENALTY = 10
SHORT_DESCRIPTION_CHARS = 200
SHORT_DESCRIPTION_PENALTY = 10

SMALL_BUDGET_UAH = 5000
LARGE_BUDGET_UAH = 30000
