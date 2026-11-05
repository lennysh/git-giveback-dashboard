"""The two operations: ``check`` (pull requests) and ``build`` (main branch)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from .points import Points, load_points
from .records import (SUBMISSIONS_DIR, Row, collect_submissions, login_for_path, merge_duplicates,
                      read_master, read_submission, write_master)
from .render import fmt_points, plural, render_leaderboard
from .scopes import load_scopes

MASTER_PATH = Path("data") / "contributions.csv"
LEADERBOARD_PATH = Path("LEADERBOARD.md")
RECHECK_STATES = {"open", "draft"}  # may still be merged later


def needs_verification(row: Row, cached: Row | None, reverify: bool) -> bool:
    if reverify or cached is None or cached.status.startswith("pending"):
        return True
    if cached.verified and cached.kind == "pull_request" and cached.state in RECHECK_STATES:
        return True
    return cached.kind == "commits" and row.count > cached.count  # a new claim for that day


def resolve(rows: list[Row], cache: dict[str, Row], verifier, reverify: bool, log=print) -> list[Row]:
    resolved = []
    for row in rows:
        cached = cache.get(row.key)
        if not needs_verification(row, cached, reverify):
            resolved.append(replace(cached, scope=row.scope, source=row.source))
            continue
        if verifier is None:
            resolved.append(replace(row, status="pending: verification disabled"))
            continue
        result = verifier.verify(row)
        log(f"  {result.status:<10.60}  {row.kind:<12} {row.ref or row.repo} ({row.user})")
        resolved.append(result)
    return resolved


@dataclass
class BuildResult:
    rows: list[Row]
    errors: list[str]
    leaderboard: str


def build(root: Path, verifier=None, reverify: bool = False, now: datetime | None = None, log=print) -> BuildResult:
    scopes = load_scopes(str(root / "scopes.toml"))
    points = load_points(root / "points.toml")
    rows, errors = collect_submissions(root, scopes)
    for error in errors:
        log(f"  skipped: {error}")
    rows = resolve(rows, read_master(root / MASTER_PATH), verifier, reverify, log)
    write_master(root / MASTER_PATH, rows)
    text = render_leaderboard(rows, points, [s.name for s in scopes], now or datetime.now(timezone.utc))
    (root / LEADERBOARD_PATH).write_text(text, encoding="utf-8")
    return BuildResult(rows, errors, text)


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    new: list[tuple[Row, float]] = field(default_factory=list)
    already_counted: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def check(data_root: Path, config_root: Path, changed: list[str], author: str | None,
          verifier=None, log=print) -> CheckResult:
    """Validate the files a pull request changed.

    ``config_root`` is the base branch checkout: scopes, points and the master
    file come from there, so a pull request cannot loosen the rules it is
    checked against. ``data_root`` is the pull request checkout.
    """
    result = CheckResult()
    scopes = load_scopes(str(config_root / "scopes.toml"))
    points: Points = load_points(config_root / "points.toml")
    cache = read_master(config_root / MASTER_PATH)

    rows: list[Row] = []
    for name in changed:
        path = data_root / name
        if not name.startswith(f"{SUBMISSIONS_DIR}/"):
            result.errors.append(f"{name}: submission pull requests may only change files under {SUBMISSIONS_DIR}/")
            continue
        if not path.exists():
            continue  # deleted file: its rows simply drop off the leaderboard
        login = login_for_path(path, data_root)
        if login and author and login.lower() != author.lower():
            result.errors.append(f"{name}: you (@{author}) can only submit under {SUBMISSIONS_DIR}/{author}/")
            continue
        found, problems = read_submission(path, data_root, scopes)
        result.errors += problems
        rows += found

    fresh = []
    for row in merge_duplicates(rows):
        cached = cache.get(row.key)
        if cached and not needs_verification(row, cached, False):
            result.already_counted += 1
        else:
            fresh.append(row)

    for row in resolve(fresh, cache, verifier, False, log):
        if row.status.startswith("rejected"):
            result.errors.append(f"{row.ref or row.repo} ({row.kind}): {row.status}")
        elif row.status.startswith("pending"):
            result.warnings.append(f"{row.ref or row.repo} ({row.kind}): {row.status}")
            result.new.append((row, 0))
        else:
            result.new.append((row, points.score(row)))
    return result


def check_summary(result: CheckResult) -> str:
    total = sum(score for _, score in result.new)
    lines = ["## Giveback submission check", "",
             f"{'✅ Looks good' if result.ok else '❌ Problems found'}: {plural(len(result.new), 'new contribution')} "
             f"(+{fmt_points(total)} points), {result.already_counted} already counted.", ""]
    if result.errors:
        lines += ["### Errors", ""] + [f"- {e}" for e in result.errors] + [""]
    if result.warnings:
        lines += ["### Warnings", ""] + [f"- {w}" for w in result.warnings] + [""]
    if result.new:
        lines += ["### New contributions", "", "| Date | Type | Contribution | State | Points |",
                  "|---|---|---|---|---:|"]
        for row, score in sorted(result.new, key=lambda rs: (rs[0].kind, rs[0].date)):
            item = row.repo if row.kind == "commits" else row.ref
            if row.kind == "commits":
                state = plural(row.count, "commit")
            else:
                state = row.role if row.kind == "issue" else row.state
            lines.append(f"| {row.day} | {row.kind} | [{item}]({row.url}) | {state} | {fmt_points(score)} |")
        lines.append("")
    return "\n".join(lines)
