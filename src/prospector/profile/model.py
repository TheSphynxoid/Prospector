from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

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


class Pricing(BaseModel):
    """USD per hour; the assistant's bids are hours x rate (fair) and hours x floor (competitive)."""
    rate: float = Field(25, gt=0)
    floor: float = Field(15, gt=0)
    hours_per_day: int = Field(6, ge=1, le=12)

    @model_validator(mode="after")
    def _floor_below_rate(self) -> "Pricing":
        if self.floor > self.rate:
            raise ValueError("the floor can't be above the rate")
        return self


class Profile(BaseModel):
    skills: dict[str, float]
    projects: list[Project]
    targets: Targets
    filters: Filters = Filters()
    boost_keywords: dict[str, float] = {}
    pricing: Pricing = Pricing()


def load_profile(path: Path) -> Profile:
    return Profile.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
