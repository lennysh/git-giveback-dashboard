import csv
import tempfile
from pathlib import Path

from giveback_board.records import SUBMISSION_COLUMNS

SCOPES = '''
[[scope]]
name = "CoP"
host = "github.com"
owner = "redhat-cop"

[[scope]]
name = "SAP"
host = "github.com"
owner = "redhat-sap"
repos = "sap-(rhsm|monitoring)"
'''

POINTS = '''
[[rule]]
kind = "pull_request"
state = "merged"
points = 1

[[rule]]
kind = "review"
points = 1

[[rule]]
kind = "issue"
role = "assignee"
points = 1
'''


def row(kind="pull_request", repo="redhat-cop/a", number=1, user="alice", state="merged", date="2026-04-01T10:00:00Z",
        count=1, role="authored", url=None):
    if url is None:
        url = {"pull_request": f"https://github.com/{repo}/pull/{number}",
               "review": f"https://github.com/{repo}/pull/{number}",
               "issue": f"https://github.com/{repo}/issues/{number}",
               "commits": f"https://github.com/{repo}/commits?author={user}"}.get(kind, "https://github.com/x")
    return {"provider": "github", "host": "github.com", "user": user, "kind": kind, "repo": repo,
            "ref": f"{repo}#{number}", "title": f"Title {number}", "url": url, "date": date, "state": state,
            "role": role, "count": count}


class Board:
    """A throwaway dashboard checkout."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "scopes.toml").write_text(SCOPES)
        (self.root / "points.toml").write_text(POINTS)

    def submit(self, login, name, rows, columns=SUBMISSION_COLUMNS):
        path = self.root / "submissions" / login / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def cleanup(self):
        self._tmp.cleanup()


class FakeVerifier:
    """Verifies everything except URLs listed in ``reject``; records what it was asked."""

    def __init__(self, reject=(), state=None):
        self.reject = set(reject)
        self.state = state
        self.seen = []

    def verify(self, row):
        from dataclasses import replace
        self.seen.append(row.key)
        if row.url in self.reject:
            return replace(row, status="rejected: nope")
        return replace(row, status="verified", **({"state": self.state} if self.state else {}))
