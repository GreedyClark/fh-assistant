import re

BID_SAFE_TYPES = {
    "employer": "Безпечна угода, комісію платить замовник",
    "split": "Безпечна угода, комісія навпіл",
    "developer": "Безпечна угода, комісію платиш ти",
    "employer_cashless": "Бізнес-угода",
}

MAX_COMMENT = 4000

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?<!\d)\+?\d[\d\s()-]{8,}\d(?!\d)")
HANDLE_RE = re.compile(r"(?<![\w/])@[A-Za-z][\w]{3,}")
MESSENGER_RE = re.compile(
    r"t\.me/|wa\.me/|telegram\.me/|viber|whatsapp|вайбер|ватсап|skype|скайп|instagram\.com|facebook\.com",
    re.IGNORECASE,
)
PRICE_RE = re.compile(
    r"\d[\d\s.,]*\s*(?:грн|гривень|гривні|₴|uah|\$|usd|доларів|долл|€|eur|руб)|[$€₴]\s*\d",
    re.IGNORECASE,
)


def check_comment(text: str) -> list[str]:
    problems = []
    if not text.strip():
        problems.append("Текст ставки порожній")
    if len(text) > MAX_COMMENT:
        problems.append(f"Текст довший за {MAX_COMMENT} символів")
    if EMAIL_RE.search(text) or PHONE_RE.search(text) or HANDLE_RE.search(text) or MESSENGER_RE.search(text):
        problems.append("У тексті є контакти (пошта, телефон, месенджер). Правила біржі це забороняють")
    if PRICE_RE.search(text):
        problems.append("У тексті є сума. Ціну вказуй тільки в полі ціни")
    return problems


def default_safe_type(project_safe_type: str | None) -> str:
    return project_safe_type if project_safe_type in BID_SAFE_TYPES else "employer"
