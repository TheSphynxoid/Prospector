"""Can the owner actually get this lead? Job level, region locks on remote roles, and gig competition.

Each check gives a factor that multiplies the stage-1 score and an optional tag shown on the lead. Nothing is
hidden: a wrong guess only moves a lead down the list.
"""
import re

from prospector.models import Kind, Lead, Remote
from prospector.profile.model import LEVELS, Profile

_W = r"(?<![\w-])"   # word start that also refuses "early-stage", "co-lead"
_E = r"(?![\w])"

# Checked against the title in this order: junior and intern words win ("Product Manager intern").
_TITLE = [
    ("intern", re.compile(_W + r"(intern(ship)?s?|stage|stagiaire|pfe|alternan(ce|t)|apprenti|apprentice(ship)?)" + _E
                          + r"(?!-)", re.I)),
    ("junior", re.compile(_W + r"(junior|jr|graduate|entry[- ]level|new[- ]grad|d[ée]butant)" + _E, re.I)),
    ("lead", re.compile(
        _W + r"(staff|principal|architect|head of|director|vp|cto|manager(?!\s+intern)|(tech|team)\s+lead)" + _E
        + r"|" + _W + r"lead\s+(\S+\s+)?(engineer|developer|dev|programmer|software|ing[ée]nieur)" + _E
        + r"|(engineer|developer|dev|programmer|ing[ée]nieur)\s+lead" + _E, re.I)),
    ("senior", re.compile(_W + r"(senior|sr|confirm[ée]e?|exp[ée]riment[ée]e?)" + _E, re.I)),
    ("mid", re.compile(_W + r"(mid|mid[- ]level|intermediate)" + _E, re.I)),
]
_YEARS = re.compile(
    r"(?:(?P<pre>minimum|at least|au moins)\s+(?:of\s+)?)?"
    r"(?P<n>\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*(?:years?|yrs|ans)\b(?P<post>.{0,30})", re.I | re.S)
_EXPERIENCE = re.compile(r"exp[ée]rience|professional", re.I)


def lead_level(lead: Lead) -> str | None:
    """The level a lead asks for, or None when neither its title nor the years it asks for say."""
    if lead.kind in (Kind.INTERNSHIP, Kind.PFE):
        return "intern"
    for level, pattern in _TITLE:
        if pattern.search(lead.title):
            return level
    years = [int(m["n"]) for m in _YEARS.finditer(lead.body or "")
             if int(m["n"]) < 30 and (m["pre"] or _EXPERIENCE.search(m["post"]))]
    if not years:
        return None
    n = max(years)
    return "senior" if n >= 5 else "mid" if n >= 3 else "junior"


_SPLIT = re.compile(r",|/|\||;|\bor\b|\band\b|&", re.I)
_OPEN = ("worldwide", "anywhere", "global")
_EUROPE = re.compile(r"\b(europe|eu|european union|cet|cest)\b", re.I)
_STATES = ("alabama alaska arizona arkansas california colorado connecticut delaware florida hawaii idaho illinois "
           "indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi "
           "missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont "
           "virginia washington wisconsin wyoming").split() + [
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "rhode island",
    "south carolina", "south dakota", "west virginia", "georgia"]
_STATE_CODES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                   "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
_CITIES = ("san francisco", "new york", "nyc", "seattle", "austin", "palo alto", "boston", "chicago", "toronto",
           "london", "bay area", "los angeles")
# Order matters: the more specific name first ("North America" before "America").
_LOCKS = [
    ("LATAM", re.compile(r"\b(latam|latin america|south america)\b", re.I)),
    ("North America", re.compile(r"\bnorth america\b", re.I)),
    ("US", re.compile(r"\b(us|usa|u\.s\.?(a\.?)?|united states|americas?|" + "|".join(_STATES) + r")(?![\w.])", re.I)),
    ("Canada", re.compile(r"\bcanad(a|ian)\b", re.I)),
    ("UK", re.compile(r"\b(uk|u\.k\.?|united kingdom|england|britain)(?![\w.])", re.I)),
    ("India", re.compile(r"\bindia\b", re.I)),
    ("Australia", re.compile(r"\baustralia\b", re.I)),
    ("APAC", re.compile(r"\bapac\b", re.I)),
]


def _city_or_state(part: str) -> bool:
    return part.strip() in _STATE_CODES or any(re.search(rf"\b{c}\b", part, re.I) for c in _CITIES)


def region_status(lead: Lead, work_from: list[str]) -> tuple[str, str | None]:
    """("ok" | "maybe" | "locked", label) for the region a remote lead is limited to."""
    region = (lead.remote_region or "").strip()
    if lead.remote is not Remote.YES or not region:
        return "ok", None
    parts = [p.strip() for p in _SPLIT.split(region) if p and p.strip()]
    allowed = [w for w in (*work_from, *_OPEN) if w]
    if any(re.search(rf"\b{re.escape(w)}\b", p, re.I) for p in parts for w in allowed):
        return "ok", None
    if any(_EUROPE.search(p) for p in parts):
        return "maybe", "Europe"
    for p in parts:
        if _city_or_state(p):
            return "locked", "US only"
        for name, pattern in _LOCKS:
            if pattern.search(p):
                return "locked", f"{name} only"
    return "ok", None


_LEVEL_TAG = {"stretch": (0.75, "Stretch"), "out": (0.35, "Too senior"), "below": (0.35, "Too junior")}


def _level_result(lead: Lead, levels: list[str]) -> tuple[float, str | None]:
    if lead.kind in (Kind.GIG, Kind.BOUNTY):
        return 1.0, None
    level = lead_level(lead)
    if level is None or level in levels:
        return 1.0, None
    idx, ranks = LEVELS.index(level), [LEVELS.index(lv) for lv in levels]
    if idx < min(ranks):
        return _LEVEL_TAG["below"]
    return _LEVEL_TAG["stretch"] if idx == max(ranks) + 1 else _LEVEL_TAG["out"]


def reach(lead: Lead, profile: Profile) -> tuple[float, str | None]:
    """The score factor and tag for a lead: the worse of its level and region results (level tag on a tie)."""
    level = _level_result(lead, profile.targets.levels)
    status, label = region_status(lead, profile.targets.work_from)
    region = {"ok": (1.0, None), "maybe": (0.75, label), "locked": (0.35, label)}[status]
    return region if region[0] < level[0] else level


def competition_factor(bids: int | None) -> float:
    if bids is None or bids <= 10:
        return 1.0
    return 0.9 if bids <= 30 else 0.8 if bids <= 50 else 0.65
