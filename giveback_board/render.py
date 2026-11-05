"""LEADERBOARD.md rendering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .points import Points
from .records import Row

KIND_LABELS = {"pull_request": "Pull request", "review": "Review", "issue": "Issue", "commits": "Commits"}


@dataclass
class Totals:
    points: float = 0
    merged: int = 0
    reviews: int = 0
    issues: int = 0
    commits: int = 0
    rows: list = field(default_factory=list)

    def add(self, row: Row, points: float) -> None:
        self.points += points
        self.rows.append((row, points))
        if row.kind == "pull_request" and row.state == "merged":
            self.merged += 1
        elif row.kind == "review":
            self.reviews += 1
        elif row.kind == "issue":
            self.issues += 1
        elif row.kind == "commits":
            self.commits += row.count


def fmt_points(value: float) -> str:
    return f"{value:g}"


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def md(text: str) -> str:
    return text.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]").replace("<", "&lt;")


def tally(rows: list[Row], points: Points) -> dict[str, Totals]:
    totals: dict[str, Totals] = defaultdict(Totals)
    for row in rows:
        if row.verified and points.in_season(row):
            totals[row.user].add(row, points.score(row))
    return totals


def ranked(totals: dict[str, Totals]) -> list[tuple[int, str, Totals]]:
    order = sorted(totals.items(), key=lambda kv: (-kv[1].points, kv[0].lower()))
    result, rank, previous = [], 0, None
    for index, (user, total) in enumerate(order, 1):
        if total.points != previous:
            rank, previous = index, total.points
        result.append((rank, user, total))
    return result


def table(totals: dict[str, Totals]) -> list[str]:
    lines = ["| Rank | Contributor | Points | Merged PRs | Reviews | Issues | Commits |",
             "|---:|---|---:|---:|---:|---:|---:|"]
    for rank, user, t in ranked(totals):
        lines.append(f"| {rank} | [@{user}](https://github.com/{user}) | **{fmt_points(t.points)}** | "
                     f"{t.merged} | {t.reviews} | {t.issues} | {t.commits} |")
    return lines


def render_leaderboard(rows: list[Row], points: Points, scope_names: list[str], now: datetime) -> str:
    totals = tally(rows, points)
    verified = [r for r in rows if r.verified]
    pending = sum(1 for r in rows if r.status.startswith("pending"))
    rejected = sum(1 for r in rows if r.status.startswith("rejected"))

    season = ""
    if points.since or points.until:
        season = f" · season {points.since or '…'} to {points.until or '…'}"
    lines = [
        "# Giveback Leaderboard", "",
        f"_Updated {now:%Y-%m-%d %H:%M} UTC · {plural(len(verified), 'verified contribution')} from "
        f"{plural(len(totals), 'contributor')}{season}_", "",
        "Scoring rules: [`points.toml`](points.toml) · Counted repositories: [`scopes.toml`](scopes.toml) · "
        "How to submit: [README](README.md#submitting-your-contributions)", "",
    ]
    if not totals:
        lines += ["No verified contributions yet. Be the first to submit!", ""]
        return "\n".join(lines)

    lines += table(totals) + [""]

    if len(scope_names) > 1:
        lines += ["## By scope", ""]
        for name in scope_names:
            scoped = tally([r for r in rows if r.scope == name], points)
            if scoped:
                lines += [f"### {name}", ""] + table(scoped) + [""]

    lines += ["## Contributors", ""]
    for rank, user, total in ranked(totals):
        lines += [f"<details><summary><b>@{user}</b> — {fmt_points(total.points)} points</summary>", "",
                  "| Date | Type | Contribution | State | Points |", "|---|---|---|---|---:|"]
        for row, score in sorted(total.rows, key=lambda rp: rp[0].date, reverse=True):
            if row.kind == "commits":
                item = f"[{md(row.repo)}]({row.url}) ({plural(row.count, 'commit')})"
            else:
                item = f"[{md(row.ref or row.url)}]({row.url}) {md(row.title)}"
            state = row.role if row.kind == "issue" else row.state
            lines.append(f"| {row.day} | {KIND_LABELS[row.kind]} | {item} | {md(state)} | {fmt_points(score)} |")
        lines += ["", "</details>", ""]

    if pending or rejected:
        lines += ["---", "",
                  f"_{pending} contributions are awaiting verification and {rejected} were rejected; "
                  "see [`data/contributions.csv`](data/contributions.csv)._", ""]
    return "\n".join(lines)
