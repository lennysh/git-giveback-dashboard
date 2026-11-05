"""Scoring rules from points.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .records import Row
from .scopes import KINDS


class PointsError(Exception):
    pass


@dataclass
class Rule:
    kind: str
    points: float
    state: str | None = None
    role: str | None = None
    scope: str | None = None
    per_commit: bool = False
    label: str = ""

    def matches(self, row: Row) -> bool:
        return (row.kind == self.kind
                and (self.state is None or row.state == self.state)
                and (self.role is None or row.role == self.role)
                and (self.scope is None or row.scope == self.scope))


@dataclass
class Points:
    rules: list[Rule] = field(default_factory=list)
    since: date | None = None
    until: date | None = None

    def in_season(self, row: Row) -> bool:
        day = date.fromisoformat(row.day)
        return (self.since is None or day >= self.since) and (self.until is None or day <= self.until)

    def score(self, row: Row) -> float:
        if not row.verified or not self.in_season(row):
            return 0
        for rule in self.rules:
            if rule.matches(row):
                return rule.points * (row.count if rule.per_commit else 1)
        return 0


def _date(value, key: str) -> date | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError:
        raise PointsError(f"points.toml: {key} must be YYYY-MM-DD") from None


def parse_points(data: dict) -> Points:
    rules = []
    for index, entry in enumerate(data.get("rule", []), 1):
        unknown = set(entry) - {"kind", "points", "state", "role", "scope", "per_commit", "label"}
        if unknown:
            raise PointsError(f"points.toml rule #{index}: unknown keys {sorted(unknown)}")
        if entry.get("kind") not in KINDS or not isinstance(entry.get("points"), (int, float)):
            raise PointsError(f"points.toml rule #{index}: needs a valid kind and numeric points")
        rules.append(Rule(entry["kind"], float(entry["points"]), entry.get("state"), entry.get("role"),
                          entry.get("scope"), bool(entry.get("per_commit", False)), entry.get("label", "")))
    return Points(rules, _date(data.get("since"), "since"), _date(data.get("until"), "until"))


def load_points(path: Path) -> Points:
    try:
        return parse_points(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise PointsError(f"cannot load {path}: {err}") from None
