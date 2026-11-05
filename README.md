# git-giveback-dashboard

A community leaderboard for open source "giveback" work. Contributors submit a
CSV of their contributions (made with
[git-giveback](https://github.com/lennysh/git-giveback)) by pull request.
GitHub Actions checks every row against the GitHub API and rebuilds
**[LEADERBOARD.md](LEADERBOARD.md)**.

There is no server and no database: the repository *is* the dashboard.

## What counts

Only contributions in the repositories listed in **[`scopes.toml`](scopes.toml)**
count. The starting list is the one the original Red Hat CoP *Giveback Ninja*
program tracked:

| Scope | Repositories |
|---|---|
| Red Hat CoP | every repository in [github.com/redhat-cop](https://github.com/redhat-cop) |
| Red Hat SAP | the `sap-*` automation repositories in [github.com/redhat-sap](https://github.com/redhat-sap) |

Points come from **[`points.toml`](points.toml)**. They also match the
original program by default:

| Contribution | Points |
|---|---:|
| Pull request you authored that was merged | 1 |
| Pull request by someone else that you reviewed | 1 |
| Issue closed while assigned to you (not one you opened yourself) | 1 |
| Commits | shown, not scored |

## Submitting your contributions

1. **Generate your CSV** with git-giveback, passing this repo's `scopes.toml`
   so the file only contains repositories that count. Nothing private or
   unrelated leaves your machine.

   ```bash
   git clone https://github.com/lennysh/git-giveback.git
   ./git-giveback/git-giveback --since 2026-03-01 \
     --scopes https://raw.githubusercontent.com/lennysh/git-giveback-dashboard/main/scopes.toml \
     -f csv -o 2026-H1.csv
   ```

2. **Fork this repo** and add the file as
   `submissions/<your-github-login>/<any-name>.csv`, for example
   `submissions/octocat/2026-H1.csv`.

3. **Open a pull request.** The *Check submission* workflow validates your file
   and verifies each row on GitHub. The job summary shows what's new and how
   many points it adds. Once a maintainer merges it, the leaderboard updates
   automatically.

Notes:

* **Preview your score first.** Add
  `--points https://raw.githubusercontent.com/lennysh/git-giveback-dashboard/main/points.toml`
  to the command above (and drop `-f csv -o ...`) to see the Points section
  git-giveback calculates with this dashboard's rules.
* **Submit as often as you like, with overlapping date ranges.** Contributions
  are de-duplicated, so re-submitting the same PR never counts twice. A common
  pattern is one file per quarter, or a single file you regenerate and
  overwrite.
* **Only submit under your own login.** The check rejects files in someone
  else's folder.
* **Deleting your file** removes those contributions from the leaderboard.
* **Open PRs can still count later.** If you submit a PR while it's still open,
  it starts scoring once it merges. The weekly rebuild re-checks open PRs.

## How verification works

Your CSV is treated as a *claim*. GitHub's API is the source of truth:

| Type | Verified by | Corrected from GitHub |
|---|---|---|
| Pull request | you are the PR author | state (merged / open / closed), merge date, title |
| Review | you submitted a review, and it isn't your own PR | best verdict, number of reviews |
| Issue | you opened it, or it's closed and you are an assignee | role, dates, title |
| Commits | the commits API shows commits by you in that repo around that day | count (capped at what GitHub shows) |

Rows that fail verification fail the PR check. Only verified rows score
points. Results are cached in [`data/contributions.csv`](data/contributions.csv),
so each contribution is checked once. Open PRs are the exception and are
re-checked until they merge or close.

Rows outside `scopes.toml`, or with a URL that doesn't match their repository,
are rejected before any API call is made. The `points` column git-giveback
writes is ignored. Points are always recalculated from `points.toml`.

## For maintainers

### Layout

```
scopes.toml                 which repositories count
points.toml                 scoring rules (and an optional season date range)
submissions/<login>/*.csv   contributor submissions (raw git-giveback CSV)
data/contributions.csv      generated: de-duplicated, verified master data
LEADERBOARD.md              generated
giveback_board/             the Python code (standard library only, Python 3.11+)
```

### Workflows

* **Check submission** (`pull_request` on `submissions/**`) runs the checker
  and reads the rules from the **base branch**, and reads only the submission
  files from the PR. A PR can't edit the checker or widen the scopes to get
  itself approved. It uses the default read-only token, so it works for PRs
  from forks.
* **Build leaderboard** runs on pushes to `main`, weekly, and on demand. It
  regenerates `data/contributions.csv` and `LEADERBOARD.md` and commits them as
  `github-actions[bot]`. Run it manually with **reverify** after changing the
  verification logic.
* **Test** runs the unit tests when the code changes.

Repository settings to check:

* The build workflow asks for `contents: write` itself, so the repository's
  default token setting can stay read-only. Only an organization policy that
  forbids write tokens would block it.
* If `main` is protected by a ruleset or branch protection that requires pull
  requests, add a bypass for GitHub Actions. Otherwise the leaderboard commit
  is rejected.
* Require the *Check submission* status before merging.

### Changing the rules

* **Add a scope:** add a `[[scope]]` block to `scopes.toml`. The format is
  documented in that file. Existing submissions only include repos that were
  in scope when they were generated, so contributors need to regenerate and
  re-submit to pick up a new scope.
* **Change points:** edit `points.toml`. Rules can match on `kind`, `state`,
  `role` and `scope`, and commits can score `per_commit`. Set `since` /
  `until` to run a season, such as a fiscal year. Rows outside the season are
  kept but not scored.
* **Non-GitHub hosts:** rows can only be verified on github.com. A scope on
  another host would accept submissions, but they would stay "pending" and
  never score until a verifier is added in `giveback_board/verify.py`.

### Running locally

```bash
export GITHUB_TOKEN=$(gh auth token)       # optional, raises the API rate limit
python3 -m giveback_board build            # rebuild data/ and LEADERBOARD.md
python3 -m giveback_board check --author octocat submissions/octocat/2026-H1.csv
python3 -m unittest discover -s tests -t . # tests
```

## History

This replaces the Red Hat CoP *Giveback Ninja* points system
([ninja-points](https://github.com/redhat-cop/ninja-points) and
[ninja-board](https://github.com/redhat-cop/ninja-board)). That system scanned
organizations from a central server. Here, contributors bring their own data,
GitHub verifies it, and GitHub Actions does the rest.

## License

[MIT](LICENSE)
