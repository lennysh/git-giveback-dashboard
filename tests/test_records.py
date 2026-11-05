import unittest

from giveback_board.records import collect_submissions, read_master, read_submission, write_master
from giveback_board.scopes import load_scopes
from tests.helpers import Board, row


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.board = Board()
        self.scopes = load_scopes(str(self.board.root / "scopes.toml"))

    def tearDown(self):
        self.board.cleanup()

    def read(self, rows, login="alice", name="a.csv"):
        return read_submission(self.board.submit(login, name, rows), self.board.root, self.scopes)

    def test_valid_rows_get_scope_and_utc_date(self):
        rows, errors = self.read([row(date="2026-04-01T06:00:00-05:00"), row(repo="redhat-sap/sap-rhsm", number=2)])
        self.assertEqual(errors, [])
        self.assertEqual([r.scope for r in rows], ["CoP", "SAP"])
        self.assertEqual(rows[0].date, "2026-04-01T11:00:00Z")

    def test_rejections(self):
        rows, errors = self.read([
            row(user="mallory"),                                    # wrong user for folder
            row(repo="someone/else"),                               # out of scope
            row(repo="redhat-sap/sap-other"),                       # out of scope (repo regex)
            row(url="https://github.com/redhat-cop/other/pull/1"),  # url doesn't match repo
            row(kind="issue", url="https://github.com/redhat-cop/a/pull/1"),  # wrong url type
            row(kind="bogus"),
            row(date="yesterday"),
            row(kind="commits", count=0),
        ])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 8, errors)
        self.assertIn("a.csv:2: user 'mallory'", errors[0])
        self.assertIn("outside the dashboard's scopes", errors[1])

    def test_bad_layout_and_columns(self):
        path = self.board.root / "submissions" / "alice.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")
        self.assertIn("must be named", read_submission(path, self.board.root, self.scopes)[1][0])
        _, errors = read_submission(self.board.submit("alice", "c.csv", [row()], columns=("user", "kind")),
                                    self.board.root, self.scopes)
        self.assertIn("missing columns", errors[0])

    def test_collect_dedups_across_files(self):
        self.board.submit("alice", "q1.csv", [row(), row(kind="commits", count=3)])
        self.board.submit("alice", "q2.csv", [row(), row(kind="commits", count=5, date="2026-04-01T00:00:00Z"),
                                              row(kind="commits", count=1, date="2026-04-02T00:00:00Z")])
        self.board.submit("bob", "all.csv", [row(user="bob", kind="review")])
        rows, errors = collect_submissions(self.board.root, self.scopes)
        self.assertEqual(errors, [])
        keys = sorted((r.user, r.kind, r.day, r.count) for r in rows)
        self.assertEqual(keys, [("alice", "commits", "2026-04-01", 5), ("alice", "commits", "2026-04-02", 1),
                                ("alice", "pull_request", "2026-04-01", 1), ("bob", "review", "2026-04-01", 1)])
        pr = next(r for r in rows if r.kind == "pull_request")
        self.assertEqual(pr.source, "submissions/alice/q1.csv; submissions/alice/q2.csv")

    def test_master_roundtrip(self):
        self.board.submit("alice", "q1.csv", [row(), row(kind="commits", count=3)])
        rows, _ = collect_submissions(self.board.root, self.scopes)
        path = self.board.root / "data" / "contributions.csv"
        write_master(path, rows)
        self.assertEqual(sorted(read_master(path).values(), key=lambda r: r.key), sorted(rows, key=lambda r: r.key))
