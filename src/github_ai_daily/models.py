from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Repository:
    full_name: str
    url: str
    description: str = ""
    language: str = ""
    stars: int = 0
    stars_today: int = 0
    forks: int = 0
    topics: list[str] = field(default_factory=list)
    updated_at: str = ""
    trending_rank: int = 0


@dataclass(slots=True)
class Selection:
    full_name: str
    is_ai: bool
    category: str
    summary_zh: str
    reason_zh: str


@dataclass(slots=True)
class ReportItem:
    repository: Repository
    selection: Selection

