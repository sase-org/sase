"""Post-integration live-marker reconciliation (sase-1bu publish-sync).

After the hidden host clone integrates (fetch + rebase), goal markers may
disagree with the event set: a concurrent settlement on another machine can
leave a stale ``live/<id>`` marker behind, or a reopen can leave a goal
unmarked. This module re-reduces the touched goals through
``goal_ledger_doctor`` scoped to those ids and commits any marker fix as
``chore(goals): reconcile live markers`` before pushing.

Reconciliation fails open: an error logs, records a diagnostic string the
caller can surface through ``doctor``, and lets bead publication continue.
A goal problem must never block beads.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from sase.goals.store import GoalLedger

logger = logging.getLogger(__name__)

RECONCILE_COMMIT_MESSAGE = "chore(goals): reconcile live markers"

_GOAL_PATH_ID = re.compile(r"goals/(?:items/([^/]+)/|live/([^/\s]+))")


def _touched_goal_ids_from_names(names: list[str]) -> list[str]:
    """Extract sorted goal ids from git path names under ``goals/``."""
    ids: set[str] = set()
    for name in names:
        match = _GOAL_PATH_ID.search(name)
        if not match:
            continue
        candidate = match.group(1) or match.group(2)
        if candidate and candidate not in ("STORE.json",):
            ids.add(candidate)
    return sorted(ids)


def _git_names(repo: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _collect_touched_goal_ids(repo: Path) -> list[str] | None:
    """List goal ids touched by the recent integration and unpushed range.

    Returns None when git cannot determine a range, signalling the caller
    to run an unscoped (full) doctor repair instead.
    """
    names: list[str] = []
    # The just-integrated range (may not exist on a fresh clone).
    names.extend(_git_names(repo, ["diff", "--name-only", "HEAD@{1}", "HEAD"]))
    # The local unpushed range.
    names.extend(_git_names(repo, ["diff", "--name-only", "@{upstream}", "HEAD"]))
    # Any dirty goals/ files left behind.
    names.extend(_git_names(repo, ["status", "--porcelain", "--", "goals"]))
    ids = _touched_goal_ids_from_names(names)
    if not ids:
        # Distinguish "git gave us nothing" (fall back to full scope) from
        # "git worked and nothing goal-related changed" (skip the repair).
        probed = _git_names(repo, ["rev-parse", "--is-inside-work-tree"])
        if not probed:
            return None
        return []
    return ids


def reconcile_goals_after_integration(
    ledger: GoalLedger,
    *,
    touched_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Reconcile live markers for goals touched by an integration.

    Commits marker fixes under ``goals/`` and returns
    ``{fixed, commit, touched, diagnostic}``. Never raises: failures are
    reported in ``diagnostic`` so bead publication can continue.
    """
    outcome: dict[str, Any] = {
        "fixed": False,
        "commit": None,
        "touched": [],
        "diagnostic": None,
    }
    if ledger.mode != "shared" or ledger.hidden_clone is None:
        return outcome
    repo = ledger.hidden_clone
    try:
        ids = (
            list(touched_ids)
            if touched_ids is not None
            else _collect_touched_goal_ids(repo)
        )
        if ids is None:
            ids = []
            scoped = False
        else:
            scoped = True
        outcome["touched"] = list(ids)
        if scoped and not ids:
            return outcome
        from sase.core.goal_ledger_facade import goal_ledger_doctor

        request: dict[str, Any] = {
            "repair": True,
            "projection_path": str(ledger.projection_path),
            "project": ledger.project,
            "mode": ledger.mode,
        }
        if scoped:
            request["ids"] = list(ids)
        report = goal_ledger_doctor(ledger.root, request)
        changed = [str(p) for p in report.get("changed_paths", [])]
        if not changed:
            return outcome
        # Commit only when goals/ actually changed.
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "goals"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or not status.stdout.strip():
            return outcome
        message = _tagged_message(RECONCILE_COMMIT_MESSAGE)
        committed = _commit_goal_paths(repo, message)
        outcome["fixed"] = committed
        outcome["commit"] = message if committed else None
        return outcome
    except Exception as exc:  # noqa: BLE001 - reconciliation fails open.
        logger.warning(
            "goals reconcile for %s failed (continuing): %s", ledger.project, exc
        )
        outcome["diagnostic"] = str(exc) or type(exc).__name__
        return outcome


def reconcile_goals_repo_path(repo: Path) -> dict[str, Any]:
    """Repair markers for a hidden-clone path without a resolved ledger.

    Used by the hidden-clone bead-link publisher, which owns the repo but
    not the project key. Fails open like the ledger variant.
    """
    outcome: dict[str, Any] = {
        "fixed": False,
        "commit": None,
        "touched": [],
        "diagnostic": None,
    }
    try:
        root = repo / "goals"
        if not (root / "STORE.json").is_file():
            return outcome
        ids = _collect_touched_goal_ids(repo)
        from sase.core.goal_ledger_facade import goal_ledger_doctor

        request: dict[str, Any] = {"repair": True}
        if ids:
            request["ids"] = list(ids)
        outcome["touched"] = list(ids or [])
        if ids is not None and not ids:
            return outcome
        goal_ledger_doctor(root, request)
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "goals"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or not status.stdout.strip():
            return outcome
        message = _tagged_message(RECONCILE_COMMIT_MESSAGE)
        committed = _commit_goal_paths(repo, message)
        outcome["fixed"] = committed
        outcome["commit"] = message if committed else None
        return outcome
    except Exception as exc:  # noqa: BLE001 - reconciliation fails open.
        logger.warning("goals repo reconcile for %s failed: %s", repo, exc)
        outcome["diagnostic"] = str(exc) or type(exc).__name__
        return outcome


def _tagged_message(message: str) -> str:
    try:
        from sase.workflows.commit.runtime_tags import (
            apply_auto_commit_tags_with_runtime,
        )

        return apply_auto_commit_tags_with_runtime(message, "goals")
    except Exception:  # noqa: BLE001 - tagging never blocks reconciliation.
        return message


def _commit_goal_paths(repo: Path, message: str) -> bool:
    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import run_sdd_git_write

    run_sdd_git_write(
        ["add", "-A", "--", "goals"],
        cwd=repo,
        check=True,
        capture_output=True,
        op="goals.reconcile_add",
    )
    diff = run_sdd_git(
        ["diff", "--cached", "--quiet", "--", "goals"],
        cwd=repo,
        capture_output=True,
        check=False,
        op="goals.reconcile_diff_cached",
    )
    if diff.returncode == 0:
        return False
    run_sdd_git_write(
        ["commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        op="goals.reconcile_commit",
    )
    return True
