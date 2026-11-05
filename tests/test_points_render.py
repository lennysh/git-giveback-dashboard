import unittest
from dataclasses import replace
from datetime import datetime, timezone

from giveback_board.points import PointsError, parse_points
from giveback_board.records import Row
from giveback_board.render import render_leaderboard

BASE = Row(user="alice", host="github.com", kind="pull_request", scope="CoP", repo="redhat-cop/a", ref="redhat-cop/a#1",
           title="Fix | pipes", url="https://github.com/redhat-cop/a/pull/1", date="2026-04-01T00:00:00Z",
           state="merged", role="authored", count=1, status="verified")


class PointsTest(unittest.TestCase):
    def test_rules(self):
        points = parse_points({"since": "2026-03-01", "rule": [
            {"kind": "pull_request", "state": "merged", "points": 2},
            {"kind": "issue", "role": "assignee", "points": 1},
            {"kind": "commits", "points": 0.5, "per_commit": True, "scope": "CoP"},
        ]})
        self.assertEqual(points.score(BASE), 2)
        self.assertEqual(points.score(replace(BASE, state="open")), 0)
        self.assertEqual(points.score(replace(BASE, status="pending: x")), 0)  # unverified never scores
        self.assertEqual(points.score(replace(BASE, date="2026-02-01T00:00:00Z")), 0)  # before season
        self.assertEqual(points.score(replace(BASE, kind="issue", role="assignee")), 1)
        self.assertEqual(points.score(replace(BASE, kind="issue", role="authored, assignee")), 0)  # self-assigned
        self.assertEqual(points.score(replace(BASE, kind="commits", count=6)), 3)
        self.assertEqual(points.score(replace(BASE, kind="commits", count=6, scope="SAP")), 0)

    def test_invalid(self):
        for bad in ({"rule": [{"kind": "x", "points": 1}]}, {"rule": [{"kind": "review"}]},
                    {"rule": [{"kind": "review", "points": 1, "typo": 1}]}, {"since": "soon"}):
            with self.assertRaises(PointsError):
                parse_points(bad)


class RenderTest(unittest.TestCase):
    def test_leaderboard(self):
        points = parse_points({"rule": [{"kind": "pull_request", "state": "merged", "points": 1},
                                        {"kind": "review", "points": 1}]})
        rows = [
            BASE,
            replace(BASE, user="bob", kind="review", url="https://github.com/redhat-cop/a/pull/9"),
            replace(BASE, user="bob", url="https://github.com/redhat-cop/a/pull/8", scope="SAP"),
            replace(BASE, user="carol", url="https://github.com/redhat-cop/a/pull/7"),
            replace(BASE, user="dave", url="https://github.com/redhat-cop/a/pull/6", status="rejected: nope"),
        ]
        text = render_leaderboard(rows, points, ["CoP", "SAP"], datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertIn("4 verified contributions from 3 contributors", text)
        self.assertIn("| 1 | [@bob](https://github.com/bob) | **2** | 1 | 1 | 0 | 0 |", text)
        self.assertIn("| 2 | [@alice]", text)
        self.assertIn("| 2 | [@carol]", text)  # tie shares the rank
        self.assertNotIn("@dave", text)
        self.assertIn("### SAP", text)
        self.assertIn("Fix \\| pipes", text)
        self.assertIn("1 were rejected", text)

    def test_empty(self):
        text = render_leaderboard([], parse_points({}), ["CoP"], datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertIn("No verified contributions yet", text)
