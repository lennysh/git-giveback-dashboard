import unittest

from giveback_board.records import Row
from giveback_board.verify import ApiError, Verifier


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        value = self.responses.get(path)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise ApiError(404, "Not Found")
        return value

    def get_all(self, path, params=None, limit_pages=10):
        return self.get(path, params)


def make(kind, url, **kw):
    base = dict(user="alice", host="github.com", kind=kind, scope="CoP", repo="o/r", ref="o/r#1", title="t",
                url=url, date="2026-04-01T00:00:00Z", state="", role="", count=1)
    base.update(kw)
    return Row(**base)


PR_URL = "https://github.com/o/r/pull/1"


class VerifyTest(unittest.TestCase):
    def test_pull_request(self):
        api = FakeApi({"/repos/o/r/pulls/1": {"user": {"login": "Alice"}, "merged_at": "2026-04-03T00:00:00Z",
                                              "state": "closed", "title": "Real title", "created_at": "2026-04-01T00:00:00Z"}})
        result = Verifier(api).verify(make("pull_request", PR_URL, state="open"))
        self.assertEqual((result.status, result.state, result.title, result.date),
                         ("verified", "merged", "Real title", "2026-04-03T00:00:00Z"))
        api.responses["/repos/o/r/pulls/1"]["user"]["login"] = "bob"
        self.assertTrue(Verifier(api).verify(make("pull_request", PR_URL)).status.startswith("rejected"))

    def test_review(self):
        api = FakeApi({
            "/repos/o/r/pulls/1": {"user": {"login": "bob"}, "title": "PR"},
            "/repos/o/r/pulls/1/reviews": [
                {"user": {"login": "alice"}, "state": "COMMENTED", "submitted_at": "2026-04-01T00:00:00Z"},
                {"user": {"login": "alice"}, "state": "APPROVED", "submitted_at": "2026-04-02T00:00:00Z"},
                {"user": {"login": "carol"}, "state": "APPROVED", "submitted_at": "2026-04-05T00:00:00Z"},
            ]})
        result = Verifier(api).verify(make("review", PR_URL))
        self.assertEqual((result.status, result.state, result.count), ("verified", "approved", 2))
        api.responses["/repos/o/r/pulls/1"]["user"]["login"] = "alice"
        self.assertIn("own pull request", Verifier(api).verify(make("review", PR_URL)).status)

    def test_issue_roles(self):
        issue = {"user": {"login": "bob"}, "state": "closed", "assignees": [{"login": "alice"}],
                 "created_at": "2026-03-01T00:00:00Z", "closed_at": "2026-04-09T00:00:00Z", "title": "Bug"}
        api = FakeApi({"/repos/o/r/issues/1": issue})
        url = "https://github.com/o/r/issues/1"
        result = Verifier(api).verify(make("issue", url, role="authored"))
        self.assertEqual((result.status, result.role, result.date), ("verified", "assignee", "2026-04-09T00:00:00Z"))
        issue["user"]["login"] = "alice"
        self.assertEqual(Verifier(api).verify(make("issue", url)).role, "authored, assignee")
        issue.update(user={"login": "bob"}, state="open")
        self.assertTrue(Verifier(api).verify(make("issue", url)).status.startswith("rejected"))
        issue["pull_request"] = {}
        self.assertIn("pull request", Verifier(api).verify(make("issue", url)).status)

    def test_commits_capped_by_api(self):
        api = FakeApi({"/repos/o/r/commits": [{}, {}]})
        result = Verifier(api).verify(make("commits", "https://github.com/o/r/commits?author=alice", count=5))
        self.assertEqual((result.status, result.count), ("verified", 2))
        self.assertEqual(api.calls[0][1]["since"], "2026-03-31T10:00:00Z")
        api.responses["/repos/o/r/commits"] = []
        self.assertTrue(Verifier(api).verify(make("commits", "https://github.com/o/r/commits", count=1))
                        .status.startswith("rejected"))

    def test_errors(self):
        self.assertIn("not found", Verifier(FakeApi({})).verify(make("pull_request", PR_URL)).status)
        api = FakeApi({"/repos/o/r/pulls/1": ApiError(502, "Bad gateway")})
        self.assertTrue(Verifier(api).verify(make("pull_request", PR_URL)).status.startswith("pending"))
        self.assertTrue(Verifier(api).verify(make("pull_request", PR_URL, host="gitlab.com")).status.startswith("pending"))
