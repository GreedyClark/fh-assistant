from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class Employer:
    id: int
    login: str
    rating: int | None
    positive_reviews: int
    negative_reviews: int
    completed_projects: int
    average_grade: float | None


@dataclass(slots=True)
class Project:
    id: int
    name: str
    description: str
    url: str
    status_id: int | None
    budget_amount: float | None
    budget_currency: str | None
    safe_type: str | None
    skills: list[tuple[int, str]]
    bid_count: int
    is_premium: bool
    published_at: datetime
    expired_at: datetime | None
    employer: Employer | None
    raw: dict = field(repr=False)

    @property
    def skill_ids(self) -> set[int]:
        return {skill_id for skill_id, _ in self.skills}


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def parse_employer(data: dict | None) -> Employer | None:
    if not data or "id" not in data:
        return None
    return Employer(
        id=data["id"],
        login=data.get("login") or "",
        rating=data.get("rating"),
        positive_reviews=data.get("positive_reviews") or 0,
        negative_reviews=data.get("negative_reviews") or 0,
        completed_projects=data.get("completed_projects") or 0,
        average_grade=data.get("average_grade"),
    )


def parse_project(item: dict) -> Project:
    attrs = item.get("attributes") or {}
    budget = attrs.get("budget") or {}
    links = (item.get("links") or {}).get("self") or {}
    return Project(
        id=item["id"],
        name=attrs.get("name") or "",
        description=attrs.get("description") or "",
        url=links.get("web") or "",
        status_id=(attrs.get("status") or {}).get("id"),
        budget_amount=budget.get("amount"),
        budget_currency=budget.get("currency"),
        safe_type=attrs.get("safe_type"),
        skills=[(s["id"], s.get("name") or "") for s in attrs.get("skills") or [] if "id" in s],
        bid_count=attrs.get("bid_count") or 0,
        is_premium=bool(attrs.get("is_premium")),
        published_at=_parse_dt(attrs.get("published_at")) or datetime.now(UTC),
        expired_at=_parse_dt(attrs.get("expired_at")),
        employer=parse_employer(attrs.get("employer")),
        raw=item,
    )
