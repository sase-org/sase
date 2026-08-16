"""Shared record builders for the selection-health tests.

Every selection-health test runs against a synthetic store under ``tmp_path``
with an injected ancestry oracle, so these helpers cover the two things such a
test needs: a manifest to record, and a way to say which commit descends from
which.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    allocate_record_path,
    full_run_record,
    record_selection,
    write_record,
)


NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
#: The default workspace both record kinds claim, so correlation is on unless
#: a test deliberately turns it off.
WORKSPACE = "/workspaces/sase_11"
CHANGED = ("src/sase/alpha.py",)


def git_init(root: Path, *, remote: str | None) -> None:
    """Initialize a git repo at ``root``, optionally with an ``origin``."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    if remote is not None:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)


def manifest(
    *,
    head: str,
    selected: tuple[str, ...] = (),
    escalated: bool = False,
    rules: tuple[str, ...] = ("contract-set-always",),
    duration: float | None = 80.0,
    outcome: str = "passed",
    contexts: dict[str, object] | None = None,
    changed_files: tuple[str, ...] | None = CHANGED,
    gear: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a scoped-run manifest of the shape ``record_selection`` expects."""
    payload: dict[str, object] = {
        "schema": 2,
        "escalated": escalated,
        "rules_fired": list(rules),
        "selected": list(selected),
        "selected_count": len(selected),
        "universe_count": 2400,
        "baseline": {"head": head, "environment": "digest", "tree_dirty": False},
    }
    if changed_files is not None:
        payload["changed_files"] = list(changed_files)
    if duration is not None:
        payload["duration"] = duration
    payload["outcome"] = outcome
    if contexts is not None:
        payload["contexts"] = contexts
    if gear is not None:
        payload["gear"] = gear
    return payload


def granted_gear(worker_count: int) -> dict[str, object]:
    """The `gear` block a run the middle gear leased workers for records."""
    return {
        "granted": True,
        "worker_count": worker_count,
        "ceiling": 4,
        "floor": 2,
        "reason": None,
    }


def refused_gear(reason: str = "tokens-unavailable") -> dict[str, object]:
    return {
        "granted": False,
        "worker_count": None,
        "ceiling": 4,
        "floor": 2,
        "reason": reason,
    }


def write_selection(
    store: Path,
    selection_manifest: dict[str, object],
    *,
    minute: int = 0,
    workspace: str | None = WORKSPACE,
) -> Path:
    """Record ``selection_manifest`` ``minute`` minutes after ``NOW``."""
    return record_selection(
        store,
        selection_manifest,
        workspace=workspace,
        pid=1000 + minute,
        now=NOW + timedelta(minutes=minute),
    )


def write_full_run(
    store: Path,
    *,
    head: str,
    failures: tuple[str, ...],
    minute: int = 30,
    workspace: str | None = WORKSPACE,
    changed_files: tuple[str, ...] | None = CHANGED,
    tree_dirty: bool | None = None,
) -> Path:
    """Record a failing full-suite run ``minute`` minutes after ``NOW``."""
    when = NOW + timedelta(minutes=minute)
    path = allocate_record_path(
        store, KIND_FULL_RUN, head=head, pid=2000 + minute, now=when
    )
    write_record(
        path,
        full_run_record(
            head=head,
            mode="fast",
            failures=failures,
            exit_status=1,
            workspace=workspace,
            changed_files=changed_files,
            tree_dirty=tree_dirty,
            now=when,
        ),
    )
    return path


def linear_ancestry(*commits: str) -> Callable[[str, str], bool]:
    """Every commit is an ancestor of the ones listed after it."""
    order = {commit: index for index, commit in enumerate(commits)}

    def _is_ancestor(ancestor: str, descendant: str) -> bool:
        if ancestor not in order or descendant not in order:
            return False
        return order[ancestor] <= order[descendant]

    return _is_ancestor
