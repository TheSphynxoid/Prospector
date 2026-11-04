"""Profile <-> settings-page form. Rows are plain dicts of strings so a failed save re-renders what was typed."""
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from prospector.profile.model import About, Filters, Interest, MinPay, Pricing, Profile, Project, Targets

_ROW = re.compile(r"^(\w+)\[(\d+)\]\[(\w+)\]$")
GROUPS = {"skills": ("name", "weight"), "projects": ("name", "writeup", "tags"),
          "min_pay": ("currency", "period", "amount"), "boost": ("keyword", "weight", "where")}
_KEYS = {"skills": "name", "projects": "name", "min_pay": "currency", "boost": "keyword"}


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _num(n: float) -> str:
    return f"{n:g}"


def _weight(s: str) -> float:
    w = float(s)
    if not 0 <= w <= 1:
        raise ValueError(f"weights are between 0 and 1, got {s}")
    return w


def rows_from_profile(p: Profile) -> dict[str, Any]:
    f = p.filters
    return {
        "skills": [{"name": k, "weight": _num(v)} for k, v in p.skills.items()],
        "projects": [{"name": x.name, "writeup": x.writeup, "tags": ", ".join(x.tags)} for x in p.projects],
        "kinds": [k.value for k in p.targets.kinds],
        "regions": ", ".join(p.targets.regions),
        "exclude_unpaid": f.exclude_unpaid,
        "min_pay": [{"currency": m.currency, "period": m.period, "amount": _num(m.amount)} for m in f.min_pay],
        "languages": ", ".join(f.languages),
        "blocked_keywords": ", ".join(f.blocked_keywords),
        "blocked_companies": ", ".join(f.blocked_companies),
        "boost": [{"keyword": i.phrase, "weight": _num(i.weight), "where": i.where} for i in p.interests],
        "pricing": {k: _num(v) for k, v in p.pricing.model_dump().items()},
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
    for name in ("regions", "languages", "blocked_keywords", "blocked_companies"):
        rows[name] = str(form.get(name, ""))
    rows["exclude_unpaid"] = bool(form.get("exclude_unpaid"))
    rows["pricing"] = {k: str(form.get(f"pricing[{k}]", "")).strip() for k in Pricing.model_fields}
    rows["has_pricing"] = any(rows["pricing"].values())
    return rows


def profile_from_rows(rows: dict[str, Any]) -> Profile:
    """Raises ValueError (bad number) or pydantic.ValidationError. Rows with an empty key column are dropped."""
    def keep(group):
        return [r for r in rows[group] if r[_KEYS[group]].strip()]

    return Profile(
        skills={r["name"].strip(): _weight(r["weight"]) for r in keep("skills")},
        projects=[Project(name=r["name"].strip(), writeup=r["writeup"].strip(), tags=_csv(r["tags"]))
                  for r in keep("projects")],
        targets=Targets(kinds=rows["kinds"], regions=_csv(rows["regions"])),
        filters=Filters(
            exclude_unpaid=rows["exclude_unpaid"],
            min_pay=[MinPay(currency=r["currency"].strip().upper(), period=r["period"], amount=float(r["amount"]))
                     for r in keep("min_pay")],
            languages=_csv(rows["languages"]),
            blocked_keywords=_csv(rows["blocked_keywords"]),
            blocked_companies=_csv(rows["blocked_companies"]),
        ),
        # Keywords keep their spaces: " go " deliberately matches the word, not "google".
        interests=[Interest(phrase=r["keyword"].strip(), weight=float(r["weight"]), where=r.get("where") or "anywhere")
                   for r in keep("boost")],
        about=rows.get("about") or About(),
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
