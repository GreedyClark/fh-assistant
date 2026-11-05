import re
from functools import lru_cache


def _term_pattern(term: str) -> str:
    escaped = re.escape(term.lower())
    if term[:1].isalnum() or term[:1] == "_":
        return rf"(?<!\w){escaped}"
    return escaped


@lru_cache(maxsize=256)
def compile_terms(terms: tuple[str, ...]) -> re.Pattern | None:
    if not terms:
        return None
    return re.compile("|".join(_term_pattern(t) for t in terms))


def find_term(text: str, terms: list[str] | tuple[str, ...]) -> str | None:
    pattern = compile_terms(tuple(terms))
    if pattern is None:
        return None
    match = pattern.search(text.lower())
    return match.group(0) if match else None


def has_term(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    return find_term(text, terms) is not None
