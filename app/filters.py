from app.models import Project
from app.prefs import Prefs
from app.scoring import is_cross_category_match
from app.textmatch import find_term

OPEN_STATUS = 11


def find_stop_word(project: Project, stop_words: list[str]) -> str | None:
    return find_term(f"{project.name}\n{project.description}", stop_words)


def preference_reason(project: Project, budget_uah: float | None, prefs: Prefs) -> str | None:
    if budget_uah is not None and budget_uah < prefs.min_budget_uah:
        return "budget"
    word = find_stop_word(project, prefs.stop_words)
    if word:
        return f"stopword:{word}"
    return None


def classify(
    project: Project,
    budget_uah: float | None,
    skill_ids: set[int],
    prefs: Prefs,
    blocked: set[int],
) -> tuple[str | None, bool]:
    if project.status_id != OPEN_STATUS:
        return "status", False
    cross = False
    if not project.skill_ids & skill_ids:
        if not (prefs.cross_category and is_cross_category_match(project)):
            return "skills", False
        cross = True
    if project.employer is None:
        return "plus_only", cross
    if project.employer.id in blocked:
        return "blocked", cross
    return preference_reason(project, budget_uah, prefs), cross
