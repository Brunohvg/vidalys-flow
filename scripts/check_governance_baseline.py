#!/usr/bin/env python3
"""Validate Git ancestry and the governance-only baseline interval."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class BaselineError(Exception):
    """The Git baseline violates the approved governance contract."""


def path_is_allowed(path: str, allowed_paths: Sequence[str]) -> bool:
    for allowed in allowed_paths:
        if allowed.endswith("/") and path.startswith(allowed):
            return True
        if path == allowed:
            return True
    return False


class GovernanceBaselineGate:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()

    def _load_json(self, relative: str) -> dict:
        path = self.root / relative
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BaselineError(f"cannot load {relative}") from exc

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(self.root), *args),
            check=False,
            capture_output=True,
            text=True,
        )

    def _require_commit(self, revision: str, label: str) -> None:
        result = self._git("cat-file", "-e", f"{revision}^{{commit}}")
        if result.returncode != 0:
            raise BaselineError(f"{label} is not an available Git commit")

    def _require_ancestor(self, ancestor: str, descendant: str, label: str) -> None:
        result = self._git("merge-base", "--is-ancestor", ancestor, descendant)
        if result.returncode == 1:
            raise BaselineError(f"{label} is not an ancestor of {descendant}")
        if result.returncode != 0:
            raise BaselineError(f"could not validate ancestry for {label}")

    def validate(self, *, head: str = "HEAD", ref_name: str = "", baseline_ref: str | None = None) -> None:
        state = self._load_json("project/state.json")
        constraints = self._load_json("project/constraints.json")
        approved_phase_head = state.get("approved_phase_head")
        baseline_branch = state.get("baseline_branch")
        allowed_paths = constraints.get("governance_baseline_allowed_paths")

        if not isinstance(approved_phase_head, str) or not SHA_PATTERN.fullmatch(approved_phase_head):
            raise BaselineError("approved_phase_head is not a valid SHA")
        if not isinstance(baseline_branch, str) or not baseline_branch:
            raise BaselineError("baseline_branch is invalid")
        if not isinstance(allowed_paths, list) or not allowed_paths or any(
            not isinstance(path, str) or not path for path in allowed_paths
        ):
            raise BaselineError("governance baseline allowed paths are invalid")

        self._require_commit(approved_phase_head, "approved_phase_head")
        self._require_commit(head, "candidate HEAD")
        self._require_ancestor(approved_phase_head, head, "approved_phase_head")

        baseline_target = head
        if ref_name.startswith("phase/"):
            baseline_target = baseline_ref or f"origin/{baseline_branch}"
            self._require_commit(baseline_target, "baseline ref")
            self._require_ancestor(baseline_target, head, "baseline ref")
        self._require_ancestor(approved_phase_head, baseline_target, "approved_phase_head")

        changed = self._git("diff", "--name-only", f"{approved_phase_head}..{baseline_target}")
        if changed.returncode != 0:
            raise BaselineError("could not inspect the governance baseline interval")
        forbidden = sorted(
            path for path in changed.stdout.splitlines() if path and not path_is_allowed(path, allowed_paths)
        )
        if forbidden:
            raise BaselineError(f"unapproved product paths exist in baseline: {', '.join(forbidden)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--ref-name", default="")
    parser.add_argument("--baseline-ref")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        GovernanceBaselineGate().validate(
            head=args.head,
            ref_name=args.ref_name,
            baseline_ref=args.baseline_ref,
        )
    except BaselineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("OK: approved phase ancestry and governance-only baseline are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
