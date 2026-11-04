from datetime import date
from pathlib import Path
from typing import Literal

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


class SpokenLanguage(BaseModel):
    language: str = Field(min_length=1, max_length=40)
    level: Literal["native", "fluent", "professional", "basic"] = "professional"


class Education(BaseModel):
    school: str = Field(min_length=1, max_length=120)
    degree: str | None = None
    year: int | None = Field(None, ge=1950, le=2100)


class Availability(BaseModel):
    hours_per_week: int | None = Field(None, ge=1, le=80)
    earliest_start: date | None = None
    open_to: list[Literal["full_time", "part_time", "gigs", "internship"]] = []


class Links(BaseModel):
    github: str | None = None
    portfolio: str | None = None
    linkedin: str | None = None
    freelancer: str | None = None
    other: str | None = None


class About(BaseModel):
    """Who the owner is: what the assistant may say about them, and nothing more."""
    name: str | None = None
    headline: str | None = None
    bio: str | None = None
    location: str | None = None
    timezone: str | None = None
    languages: list[SpokenLanguage] = []
    years_experience: int | None = Field(None, ge=0, le=60)
    highlights: list[str] = []
    education: list[Education] = []
    availability: Availability = Availability()
    links: Links = Links()


class Interest(BaseModel):
    """A word or phrase that moves a lead up (positive weight) or down (negative)."""
    phrase: str = Field(min_length=1, max_length=80)
    weight: float = Field(ge=-1, le=1)
    where: Literal["title", "anywhere"] = "anywhere"

    @model_validator(mode="after")
    def _nonzero(self) -> "Interest":
        if self.weight == 0:
            raise ValueError("a weight of 0 does nothing; remove the interest instead")
        self.phrase = self.phrase.strip()
        if not self.phrase:
            raise ValueError("the phrase is empty")
        return self


class Profile(BaseModel):
    skills: dict[str, float]
    projects: list[Project]
    targets: Targets
    filters: Filters = Filters()
    interests: list[Interest] = []
    pricing: Pricing = Pricing()
    about: About = About()

    @model_validator(mode="before")
    @classmethod
    def _legacy_boost_keywords(cls, data):
        """Old profiles had boost_keywords {keyword: weight}, matched as substrings; they become interests."""
        if isinstance(data, dict) and "boost_keywords" in data:
            data = dict(data)
            legacy = data.pop("boost_keywords") or {}
            if "interests" not in data:
                data["interests"] = [{"phrase": k.strip(), "weight": v} for k, v in legacy.items()
                                     if k.strip() and v]
        return data


def load_profile(path: Path) -> Profile:
    return Profile.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
