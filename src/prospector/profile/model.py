from pathlib import Path

import yaml
from pydantic import BaseModel

from prospector.models import Kind


class Project(BaseModel):
    name: str
    writeup: str
    tags: list[str] = []


class Targets(BaseModel):
    kinds: list[Kind]
    regions: list[str]


class MinPay(BaseModel):
    currency: str
    period: str
    amount: float


class Filters(BaseModel):
    exclude_unpaid: bool = True
    min_pay: list[MinPay] = []
    languages: list[str] = ["fr", "en", "ar"]
    blocked_keywords: list[str] = []
    blocked_companies: list[str] = []


class Profile(BaseModel):
    skills: dict[str, float]
    projects: list[Project]
    targets: Targets
    filters: Filters = Filters()
    boost_keywords: dict[str, float] = {}


def load_profile(path: Path) -> Profile:
    return Profile.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
