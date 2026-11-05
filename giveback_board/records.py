"""Reading, validating and de-duplicating submission CSVs, and the master data file.

A submission is the CSV written by ``git-giveback -f csv``, stored at
``submissions/<github-login>/<anything>.csv``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from .scopes import KINDS, Scope, scope_for

SUBMISSION_COLUMNS = ("provider", "host", "user", "kind", "repo", "ref", "title", "url", "date", "state", "role", "count")
MAX_ROWS_PER_FILE = 10_000
SUBMISSIONS_DIR = "submissions"
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


@dataclass
class Row:
    user: str
    host: str
    kind: str
    scope: str
    repo: str
    ref: str
    title: str
    url: str
    date: str  # UTC, "YYYY-MM-DDTHH:MM:SSZ"
    state: str
    role: str
    count: int
    status: str = "pending"  # verified | rejected: <why> | pending: <why>
    source: str = ""  # submission file(s) the row came from

    @property
    def key(self) -> str:
        if self.kind == "commits":
            return f"commits|{self.host}|{self.user.lower()}|{self.repo.lower()}|{self.date[:10]}"
        return f"{self.kind}|{self.host}|{self.user.lower()}|{self.url.lower()}"

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    @property
    def day(self) -> str:
        return self.date[:10]


MASTER_COLUMNS = tuple(f.name for f in fields(Row))


def _url_pattern(kind: str, host: str, repo: str) -> re.Pattern:
    base = f"https://{re.escape(host)}/{re.escape(repo)}"
    tail = {"pull_request": r"/pull/\d+", "review": r"/pull/\d+", "issue": r"/issues/\d+",
            "commits": r"/commits(\?.*)?"}[kind]
    return re.compile(f"^{base}{tail}$", re.IGNORECASE)


def normalize_date(value: str) -> str:
    moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def login_for_path(path: Path, root: Path) -> str | None:
    """Return the login folder for submissions/<login>/<file>.csv, else None."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return None
    if len(parts) != 3 or parts[0] != SUBMISSIONS_DIR or not parts[2].lower().endswith(".csv"):
        return None
    return parts[1] if LOGIN_RE.match(parts[1]) else None


def read_submission(path: Path, root: Path, scopes: list[Scope]) -> tuple[list[Row], list[str]]:
    """Parse and validate one submission file. Returns (rows, errors)."""
    rel = path.resolve().relative_to(root.resolve()).as_posix() if path.is_absolute() else path.as_posix()
    login = login_for_path(path, root)
    if login is None:
        return [], [f"{rel}: submissions must be named submissions/<github-login>/<name>.csv"]

    rows: list[Row] = []
    errors: list[str] = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in SUBMISSION_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                return [], [f"{rel}: missing columns {', '.join(missing)} (generate it with `git-giveback -f csv`)"]
            for line, record in enumerate(reader, start=2):
                if line - 1 > MAX_ROWS_PER_FILE:
                    errors.append(f"{rel}: more than {MAX_ROWS_PER_FILE} rows; split the file")
                    break
                row, problem = _parse_row(record, login, scopes, rel)
                if problem:
                    errors.append(f"{rel}:{line}: {problem}")
                elif row:
                    rows.append(row)
    except (OSError, UnicodeDecodeError, csv.Error) as err:
        return [], [f"{rel}: cannot read file: {err}"]
    return rows, errors


def _parse_row(record: dict, login: str, scopes: list[Scope], source: str) -> tuple[Row | None, str | None]:
    get = lambda k: (record.get(k) or "").strip()  # noqa: E731
    host, user, kind, repo, url = get("host").lower(), get("user"), get("kind"), get("repo"), get("url")
    if user.lower() != login.lower():
        return None, f"user '{user}' does not match the folder name '{login}'"
    if kind not in KINDS:
        return None, f"unknown kind '{kind}'"
    scope = scope_for(scopes, host, repo, kind)
    if scope is None:
        return None, f"{host}/{repo} ({kind}) is outside the dashboard's scopes; regenerate with --scopes"
    if not _url_pattern(kind, host, repo).match(url):
        return None, f"url '{url}' does not belong to {repo}"
    try:
        date = normalize_date(get("date"))
    except ValueError:
        return None, f"invalid date '{get('date')}'"
    try:
        count = int(get("count") or "1")
    except ValueError:
        return None, f"invalid count '{get('count')}'"
    if count < 1:
        return None, f"count must be at least 1"
    return Row(user=login, host=host, kind=kind, scope=scope.name, repo=repo, ref=get("ref"),
               title=get("title")[:300], url=url, date=date, state=get("state").lower(),
               role=get("role"), count=count, source=source), None


def merge_duplicates(rows: list[Row]) -> list[Row]:
    """Collapse rows with the same key. Commits keep the highest daily count."""
    merged: dict[str, Row] = {}
    for row in rows:
        existing = merged.get(row.key)
        if existing is None:
            merged[row.key] = row
            continue
        if row.source and row.source not in existing.source.split("; "):
            existing.source = f"{existing.source}; {row.source}" if existing.source else row.source
        if row.kind == "commits":
            existing.count = max(existing.count, row.count)
    return list(merged.values())


def collect_submissions(root: Path, scopes: list[Scope]) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    errors: list[str] = []
    for path in sorted((root / SUBMISSIONS_DIR).glob("*/*")):
        if path.is_file() and path.suffix.lower() == ".csv":
            found, problems = read_submission(path, root, scopes)
            rows += found
            errors += problems
    return merge_duplicates(rows), errors


def read_master(path: Path) -> dict[str, Row]:
    if not path.exists():
        return {}
    cache: dict[str, Row] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            try:
                row = Row(**{k: record.get(k, "") for k in MASTER_COLUMNS if k != "count"},
                          count=int(record.get("count") or 1))
            except (TypeError, ValueError):
                continue
            cache[row.key] = row
    return cache


def write_master(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r.user.lower(), r.kind, r.date, r.url))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(MASTER_COLUMNS)
        for row in ordered:
            writer.writerow([getattr(row, c) for c in MASTER_COLUMNS])
