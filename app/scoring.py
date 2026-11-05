import re
from dataclasses import dataclass, field
from datetime import datetime

from app import scoring_rules as rules
from app.models import Project
from app.textmatch import has_term

CONTACT_PATTERNS = [re.compile(p) for p in rules.CONTACT_REGEXES]


@dataclass
class Score:
    value: int
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)


def project_text(project: Project) -> str:
    return f"{project.name}\n{project.description}".lower()


def matched_groups(text: str) -> list[tuple[str, int]]:
    result = []
    for label, requirements, points in rules.KEYWORD_GROUPS:
        if all(has_term(text, terms) for terms in requirements):
            result.append((label, points))
    return result


def is_cross_category_match(project: Project) -> bool:
    text = project_text(project)
    return any(label in rules.CROSS_CATEGORY_GROUPS for label, _ in matched_groups(text))


def red_flags(project: Project, budget_uah: float | None) -> list[tuple[str, int]]:
    text = project_text(project)
    flags = []
    if has_term(text, rules.FREE_TEST_TERMS) and has_term(text, rules.FREE_TERMS):
        flags.append(("безкоштовне тестове", rules.RED_FLAG_PENALTY))
    if has_term(text, rules.PERCENT_TERMS):
        flags.append(("оплата відсотком або за результат", rules.RED_FLAG_PENALTY))
    if has_term(text, rules.REVIEW_PAY_TERMS):
        flags.append(("оплата відгуком", rules.RED_FLAG_PENALTY))
    if has_term(text, rules.OFF_PLATFORM_TERMS) or any(p.search(text) for p in CONTACT_PATTERNS):
        flags.append(("контакти або робота поза біржею", rules.RED_FLAG_PENALTY))
    if (
        budget_uah is not None
        and budget_uah < rules.URGENT_BUDGET_UAH
        and has_term(text, rules.URGENT_TERMS)
    ):
        flags.append(("терміново за малий бюджет", rules.URGENT_PENALTY))
    if len(project.description.strip()) < rules.SHORT_DESCRIPTION_CHARS:
        flags.append(("мало деталей у ТЗ", rules.SHORT_DESCRIPTION_PENALTY))
    return flags


def _bids_part(bid_count: int) -> tuple[int, str | None]:
    for limit, points, label in rules.BID_TIERS:
        if bid_count <= limit:
            return points, f"{label} ({bid_count})" if label else None
    return rules.BID_MAX_PENALTY, f"дуже багато ставок ({bid_count})"


def score_project(project: Project, budget_uah: float | None, now: datetime, cross_category: bool = False) -> Score:
    text = project_text(project)
    score = Score(rules.BASE_SCORE)

    def add(points: int, label: str | None) -> None:
        score.value += points
        if not label or points == 0:
            return
        (score.pros if points > 0 else score.cons).append(label)

    if cross_category:
        add(-5, None)
    elif project.skill_ids & rules.CORE_SKILL_IDS:
        add(10, "твоя категорія")
    else:
        add(3, None)

    groups = matched_groups(text)
    if not groups:
        add(-rules.NO_KEYWORDS_PENALTY, "у тексті немає твого стеку")
    keyword_points = 0
    for label, points in groups:
        if keyword_points >= rules.KEYWORD_CAP:
            break
        points = min(points, rules.KEYWORD_CAP - keyword_points)
        keyword_points += points
        add(points, label)

    unfamiliar = [t for t in rules.UNFAMILIAR_TERMS if has_term(text, (t,))]
    if unfamiliar:
        penalty = min(len(unfamiliar) * rules.UNFAMILIAR_PENALTY, rules.UNFAMILIAR_CAP)
        add(-penalty, f"незнайомий стек ({', '.join(unfamiliar[:2])})")

    add(*_bids_part(project.bid_count))

    age_hours = (now - project.published_at).total_seconds() / 3600
    if age_hours < 1:
        add(5, "свіжий")
    elif age_hours > 48:
        add(-10, "старий")
    elif age_hours > 24:
        add(-5, "вже не свіжий")

    if budget_uah is not None:
        if budget_uah >= rules.LARGE_BUDGET_UAH:
            add(-5, "великий проєкт")
        elif budget_uah <= rules.SMALL_BUDGET_UAH:
            add(5, "невеликий проєкт")

    if project.safe_type is None:
        add(-15, "без Сейфу")

    employer = project.employer
    if employer:
        if employer.negative_reviews:
            add(-10, f"негативні відгуки ({employer.negative_reviews})")
        elif employer.completed_projects >= 3 and employer.positive_reviews:
            add(5, "перевірений замовник")
        elif not employer.completed_projects and not employer.positive_reviews:
            add(-3, "новий замовник")

    for label, penalty in red_flags(project, budget_uah):
        add(-penalty, label)

    score.value = max(0, min(100, score.value))
    return score
