import unittest

from giveback_board.board import MASTER_PATH, build, check, check_summary
from giveback_board.records import read_master
from tests.helpers import Board, FakeVerifier, row

quiet = lambda *a: None  # noqa: E731


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.board = Board()

    def tearDown(self):
        self.board.cleanup()

    def test_build_scores_and_caches(self):
        self.board.submit("alice", "q1.csv", [row(), row(kind="review", number=2),
                                              row(number=3, state="open")])
        self.board.submit("bob", "q1.csv", [row(user="bob", number=4)])
        verifier = FakeVerifier(reject={"https://github.com/redhat-cop/a/pull/4"})
        result = build(self.board.root, verifier, log=quiet)
        self.assertEqual(len(verifier.seen), 4)
        self.assertIn("| 1 | [@alice](https://github.com/alice) | **2** |", result.leaderboard)
        self.assertNotIn("[@bob]", result.leaderboard)
        self.assertTrue((self.board.root / "LEADERBOARD.md").exists())

        # Second build: only the open PR is re-checked (it might have been merged since).
        again = FakeVerifier()
        build(self.board.root, again, log=quiet)
        self.assertEqual(len(again.seen), 1)
        self.assertIn("pull/3", again.seen[0])

        # Removing a submission removes its rows.
        (self.board.root / "submissions" / "bob" / "q1.csv").unlink()
        build(self.board.root, FakeVerifier(), log=quiet)
        self.assertEqual({r.user for r in read_master(self.board.root / MASTER_PATH).values()}, {"alice"})

    def test_build_without_verifier_scores_nothing(self):
        self.board.submit("alice", "q1.csv", [row()])
        result = build(self.board.root, None, log=quiet)
        self.assertIn("No verified contributions yet", result.leaderboard)
        self.assertTrue(result.rows[0].status.startswith("pending"))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.board = Board()

    def tearDown(self):
        self.board.cleanup()

    def test_new_and_already_counted(self):
        self.board.submit("alice", "q1.csv", [row()])
        build(self.board.root, FakeVerifier(), log=quiet)
        self.board.submit("alice", "q2.csv", [row(), row(kind="review", number=2), row(number=3)])
        verifier = FakeVerifier(reject={"https://github.com/redhat-cop/a/pull/3"})
        result = check(self.board.root, self.board.root, ["submissions/alice/q2.csv"], "alice", verifier, log=quiet)
        self.assertEqual(result.already_counted, 1)
        self.assertEqual(len(result.new), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("rejected", result.errors[0])
        self.assertIn("+1 points", check_summary(result))

    def test_policy_errors(self):
        self.board.submit("bob", "q1.csv", [row(user="bob")])
        (self.board.root / "points.toml").write_text((self.board.root / "points.toml").read_text())
        result = check(self.board.root, self.board.root,
                       ["submissions/bob/q1.csv", "points.toml", "submissions/alice/deleted.csv"],
                       "alice", None, log=quiet)
        self.assertEqual(len(result.errors), 2)
        self.assertIn("only submit under submissions/alice/", result.errors[0])
        self.assertIn("may only change files under submissions/", result.errors[1])

    def test_config_comes_from_base_checkout(self):
        pr = Board()
        try:
            (pr.root / "scopes.toml").write_text('[[scope]]\nname="X"\nhost="github.com"\nowner="anything"\n')
            pr.submit("alice", "q.csv", [row(repo="anything/repo")])
            result = check(pr.root, self.board.root, ["submissions/alice/q.csv"], "alice", None, log=quiet)
            self.assertIn("outside the dashboard's scopes", result.errors[0])
        finally:
            pr.cleanup()
