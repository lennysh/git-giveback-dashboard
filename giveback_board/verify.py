"""Check submitted rows against the GitHub REST API.

The API is treated as the source of truth: a verified row gets its state,
title, role and (for commits) count corrected from what GitHub reports.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from . import __version__
from .records import Row, normalize_date

REVIEW_RANK = {"APPROVED": 3, "CHANGES_REQUESTED": 2, "COMMENTED": 1}
# GitHub buckets commit contributions by the author's local day, so look a bit
# beyond the UTC day when counting commits.
COMMIT_WINDOW_SLACK = timedelta(hours=14)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


class GitHubApi:
    def __init__(self, token: str | None, base: str = "https://api.github.com", max_wait: float = 90):
        self.token = token
        self.base = base
        self.max_wait = max_wait

    def get(self, path: str, params: dict | None = None):
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": f"giveback-board/{__version__}",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                wait = self._rate_limit_wait(err)
                if wait is not None and attempt < 2:
                    print(f"  rate limited; waiting {wait:.0f}s", file=sys.stderr)
                    time.sleep(wait)
                    continue
                try:
                    message = json.loads(err.read().decode("utf-8")).get("message", "")
                except (ValueError, AttributeError):
                    message = ""
                raise ApiError(err.code, message or err.reason) from None
            except urllib.error.URLError as err:
                raise ApiError(0, str(err.reason)) from None
        raise ApiError(0, "retries exhausted")

    def _rate_limit_wait(self, err: urllib.error.HTTPError) -> float | None:
        if err.code not in (403, 429):
            return None
        headers = err.headers or {}
        if str(headers.get("Retry-After", "")).isdigit():
            wait = float(headers["Retry-After"])
        elif headers.get("X-RateLimit-Remaining") == "0" and str(headers.get("X-RateLimit-Reset", "")).isdigit():
            wait = max(0.0, float(headers["X-RateLimit-Reset"]) - time.time()) + 1
        else:
            return None
        return wait if wait <= self.max_wait else None

    def get_all(self, path: str, params: dict | None = None, limit_pages: int = 10) -> list:
        items: list = []
        for page in range(1, limit_pages + 1):
            batch = self.get(path, {**(params or {}), "per_page": 100, "page": page})
            items += batch
            if len(batch) < 100:
                break
        return items


def _number(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


class Verifier:
    def __init__(self, api: GitHubApi):
        self.api = api

    def verify(self, row: Row) -> Row:
        if row.host != "github.com":
            return replace(row, status=f"pending: no verifier for {row.host}")
        try:
            return getattr(self, f"_{row.kind}")(row)
        except ApiError as err:
            if err.status in (404, 410):
                return replace(row, status="rejected: not found on GitHub")
            return replace(row, status=f"pending: {err}")

    def _is(self, login: str | None, row: Row) -> bool:
        return bool(login) and login.lower() == row.user.lower()

    def _pull_request(self, row: Row) -> Row:
        pr = self.api.get(f"/repos/{row.repo}/pulls/{_number(row.url)}")
        if not self._is((pr.get("user") or {}).get("login"), row):
            return replace(row, status="rejected: not the author of this pull request")
        if pr.get("merged_at"):
            state, date = "merged", normalize_date(pr["merged_at"])
        elif pr.get("state") == "open":
            state, date = ("draft" if pr.get("draft") else "open"), normalize_date(pr["created_at"])
        else:
            state, date = "closed", normalize_date(pr["created_at"])
        return replace(row, status="verified", state=state, date=date, title=pr.get("title", row.title))

    def _review(self, row: Row) -> Row:
        path = f"/repos/{row.repo}/pulls/{_number(row.url)}"
        pr = self.api.get(path)
        if self._is((pr.get("user") or {}).get("login"), row):
            return replace(row, status="rejected: reviews of your own pull request don't count")
        mine = [r for r in self.api.get_all(f"{path}/reviews")
                if self._is((r.get("user") or {}).get("login"), row) and r.get("state") in REVIEW_RANK]
        if not mine:
            return replace(row, status="rejected: no review by this user")
        best = max(mine, key=lambda r: REVIEW_RANK[r["state"]])
        latest = max(normalize_date(r["submitted_at"]) for r in mine if r.get("submitted_at"))
        return replace(row, status="verified", state=best["state"].lower().replace("_", " "),
                       count=len(mine), date=latest, title=pr.get("title", row.title))

    def _issue(self, row: Row) -> Row:
        issue = self.api.get(f"/repos/{row.repo}/issues/{_number(row.url)}")
        if "pull_request" in issue:
            return replace(row, status="rejected: this is a pull request, not an issue")
        roles = []
        if self._is((issue.get("user") or {}).get("login"), row):
            roles.append("authored")
        if issue.get("state") == "closed" and any(self._is(a.get("login"), row) for a in issue.get("assignees") or []):
            roles.append("assignee")
        if not roles:
            return replace(row, status="rejected: neither the author nor the assignee of this closed issue")
        date = normalize_date(issue["closed_at"]) if roles == ["assignee"] else normalize_date(issue["created_at"])
        return replace(row, status="verified", role=", ".join(roles), state=issue.get("state", row.state),
                       date=date, title=issue.get("title", row.title))

    def _commits(self, row: Row) -> Row:
        day = datetime.fromisoformat(row.day).replace(tzinfo=timezone.utc)
        commits = self.api.get_all(f"/repos/{row.repo}/commits", {
            "author": row.user,
            "since": (day - COMMIT_WINDOW_SLACK).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "until": (day + timedelta(days=1) + COMMIT_WINDOW_SLACK).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, limit_pages=3)
        if not commits:
            return replace(row, status="rejected: no commits by this user around that day")
        return replace(row, status="verified", count=min(row.count, len(commits)))
