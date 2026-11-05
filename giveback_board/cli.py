"""Command line: ``python -m giveback_board {check,build}``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .board import build, check, check_summary
from .points import PointsError
from .scopes import ScopeError
from .verify import GitHubApi, Verifier


def make_verifier(enabled: bool):
    if not enabled:
        return None
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("warning: no GITHUB_TOKEN; using the unauthenticated API (60 requests/hour)", file=sys.stderr)
    return Verifier(GitHubApi(token))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="giveback_board", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="rebuild data/contributions.csv and LEADERBOARD.md")
    b.add_argument("--root", default=".", help="repository root (default: .)")
    b.add_argument("--no-verify", action="store_true", help="skip GitHub verification (nothing will be scored)")
    b.add_argument("--reverify", action="store_true", help="re-check every row, ignoring cached results")

    c = sub.add_parser("check", help="validate the submission files a pull request changed")
    c.add_argument("files", nargs="*", help="changed paths, relative to --root")
    c.add_argument("--root", default=".", help="pull request checkout (default: .)")
    c.add_argument("--config-root", help="base branch checkout with the trusted config (default: --root)")
    c.add_argument("--author", help="pull request author; submissions must be in submissions/<author>/")
    c.add_argument("--no-verify", action="store_true", help="skip GitHub verification")
    c.add_argument("--summary", metavar="FILE", help="append a markdown summary to FILE (e.g. $GITHUB_STEP_SUMMARY)")

    args = parser.parse_args(argv)
    log = lambda msg: print(msg, file=sys.stderr)  # noqa: E731
    try:
        if args.command == "build":
            result = build(Path(args.root), make_verifier(not args.no_verify), args.reverify, log=log)
            verified = sum(r.verified for r in result.rows)
            log(f"{len(result.rows)} contributions ({verified} verified), {len(result.errors)} skipped rows")
            return 0

        root = Path(args.root)
        result = check(root, Path(args.config_root) if args.config_root else root, args.files,
                       args.author, make_verifier(not args.no_verify), log=log)
        summary = check_summary(result)
        print(summary)
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as handle:
                handle.write(summary + "\n")
        return 0 if result.ok else 1
    except (ScopeError, PointsError) as err:
        parser.error(str(err))
