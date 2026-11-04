"""Profile <-> settings-page form. Rows are plain dicts of strings so a failed save re-renders what was typed."""
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from prospector.profile.model import (About, Availability, Education, Filters, Interest, Links, MinPay, Pricing,
                                      Profile, Project, SpokenLanguage, Targets)

_ROW = re.compile(r"^(\w+)\[(\d+)\]\[(\w+)\]$")
GROUPS = {"skills": ("name", "weight"), "projects": ("name", "writeup", "tags"),
          "min_pay": ("currency", "period", "amount"), "boost": ("keyword", "weight", "where"),
          "about_lang": ("language", "level"), "education": ("school", "degree", "year")}
_KEYS = {"skills": "name", "projects": "name", "min_pay": "currency", "boost": "keyword", "about_lang": "language",
         "education": "school"}
ABOUT_TEXT = ("name", "headline", "bio", "location", "timezone", "years_experience")
LINKS = tuple(Links.model_fields)
SKILL_STEPS = {1.0: "Core", 0.7: "Strong", 0.4: "Some"}


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _num(n: float) -> str:
    return f"{n:g}"


def _weight(s: str) -> float:
    w = float(s)
    if not 0 <= w <= 1:
        raise ValueError(f"weights are between 0 and 1, got {s}")
    return w


def _opt(s: str | None) -> str | None:
    return (s or "").strip() or None


def rows_from_profile(p: Profile) -> dict[str, Any]:
    f, a = p.filters, p.about
    return {
        "skills": [{"name": k, "weight": _num(v)} for k, v in p.skills.items()],
        "projects": [{"name": x.name, "writeup": x.writeup, "tags": ", ".join(x.tags)} for x in p.projects],
        "kinds": [k.value for k in p.targets.kinds],
        "regions": ", ".join(p.targets.regions),
        "levels": list(p.targets.levels),
        "work_from": ", ".join(p.targets.work_from),
        "exclude_unpaid": f.exclude_unpaid,
        "min_pay": [{"currency": m.currency, "period": m.period, "amount": _num(m.amount)} for m in f.min_pay],
        "languages": ", ".join(f.languages),
        "blocked_keywords": ", ".join(f.blocked_keywords),
        "blocked_companies": ", ".join(f.blocked_companies),
        "boost": [{"keyword": i.phrase, "weight": _num(i.weight), "where": i.where} for i in p.interests],
        "pricing": {k: _num(v) for k, v in p.pricing.model_dump().items()},
        "about": {**{k: "" if getattr(a, k) is None else str(getattr(a, k)) for k in ABOUT_TEXT},
                  "highlights": "\n".join(a.highlights)},
        "about_lang": [{"language": x.language, "level": x.level} for x in a.languages],
        "education": [{"school": e.school, "degree": e.degree or "", "year": "" if e.year is None else str(e.year)}
                      for e in a.education],
        "availability": {"hours_per_week": "" if a.availability.hours_per_week is None else str(a.availability.hours_per_week),
                         "earliest_start": a.availability.earliest_start.isoformat() if a.availability.earliest_start else "",
                         "open_to": list(a.availability.open_to)},
        "links": {k: getattr(a.links, k) or "" for k in LINKS},
        "has_about": True,
    }


def rows_from_form(form) -> dict[str, Any]:
    groups: dict[str, dict[int, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for key, value in form.multi_items():
        m = _ROW.match(key)
        if m and m[1] in GROUPS and m[3] in GROUPS[m[1]]:
            groups[m[1]][int(m[2])][m[3]] = str(value)
    rows: dict[str, Any] = {}
    for group, cols in GROUPS.items():
        rows[group] = [{c: r.get(c, "") for c in cols} for _, r in sorted(groups[group].items())]
    rows["kinds"] = [str(v) for v in form.getlist("kinds")]
    # None = this form had no level or work-from fields (keep the defaults), not "none picked".
    rows["levels"] = [str(v) for v in form.getlist("levels")] if form.get("levels_present") else None
    rows["work_from"] = str(form.get("work_from", "")) if "work_from" in form else None
    for name in ("regions", "languages", "blocked_keywords", "blocked_companies"):
        rows[name] = str(form.get(name, ""))
    rows["exclude_unpaid"] = bool(form.get("exclude_unpaid"))
    rows["pricing"] = {k: str(form.get(f"pricing[{k}]", "")).strip() for k in Pricing.model_fields}
    rows["has_pricing"] = any(rows["pricing"].values())
    rows["has_about"] = bool(form.get("about_present"))
    rows["about"] = {k: str(form.get(f"about[{k}]", "")) for k in (*ABOUT_TEXT, "highlights")}
    rows["availability"] = {"hours_per_week": str(form.get("availability[hours_per_week]", "")),
                            "earliest_start": str(form.get("availability[earliest_start]", "")),
                            "open_to": [str(v) for v in form.getlist("availability[open_to]")]}
    rows["links"] = {k: str(form.get(f"links[{k}]", "")) for k in LINKS}
    return rows


def _about(rows: dict[str, Any]) -> About:
    a, av = rows["about"], rows["availability"]
    years = a.get("years_experience", "").strip()
    hours = av.get("hours_per_week", "").strip()
    return About(
        **{k: _opt(a.get(k)) for k in ("name", "headline", "bio", "location", "timezone")},
        years_experience=int(years) if years else None,
        highlights=[x.strip() for x in a.get("highlights", "").splitlines() if x.strip()],
        languages=[SpokenLanguage(language=r["language"].strip(), level=r["level"] or "professional")
                   for r in rows["about_lang"] if r["language"].strip()],
        education=[Education(school=r["school"].strip(), degree=_opt(r["degree"]),
                             year=int(r["year"]) if r["year"].strip() else None)
                   for r in rows["education"] if r["school"].strip()],
        availability=Availability(hours_per_week=int(hours) if hours else None,
                                  earliest_start=av.get("earliest_start") or None, open_to=av.get("open_to", [])),
        links=Links(**{k: _opt(v) for k, v in rows["links"].items()}),
    )


def profile_from_rows(rows: dict[str, Any]) -> Profile:
    """Raises ValueError (bad number) or pydantic.ValidationError. Rows with an empty key column are dropped."""
    def keep(group):
        return [r for r in rows[group] if r[_KEYS[group]].strip()]

    return Profile(
        skills={r["name"].strip(): _weight(r["weight"]) for r in keep("skills")},
        projects=[Project(name=r["name"].strip(), writeup=r["writeup"].strip(), tags=_csv(r["tags"]))
                  for r in keep("projects")],
        targets=Targets(kinds=rows["kinds"], regions=_csv(rows["regions"]),
                        **({} if rows.get("levels") is None else {"levels": rows["levels"]}),
                        **({} if rows.get("work_from") is None else {"work_from": _csv(rows["work_from"])})),
        filters=Filters(
            exclude_unpaid=rows["exclude_unpaid"],
            min_pay=[MinPay(currency=r["currency"].strip().upper(), period=r["period"], amount=float(r["amount"]))
                     for r in keep("min_pay")],
            languages=_csv(rows["languages"]),
            blocked_keywords=_csv(rows["blocked_keywords"]),
            blocked_companies=_csv(rows["blocked_companies"]),
        ),
        interests=[Interest(phrase=r["keyword"].strip(), weight=float(r["weight"]), where=r.get("where") or "anywhere")
                   for r in keep("boost")],
        about=_about(rows) if rows.get("has_about") else About(),
        pricing=Pricing(**{k: float(v) for k, v in rows.get("pricing", {}).items() if v}),
    )


def save_profile(path: Path, p: Profile) -> None:
    path = Path(path)
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    data = p.model_dump(mode="json")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("# Edited from the Prospector settings page.\n"
                   + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    os.replace(tmp, path)
