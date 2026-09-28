"""TTL single-flight background fetch for goal ledgers (sase-1bu publish-sync).

``python -m sase.goals.fetch_worker <project>`` integrates the hidden host
clone, reconciles live markers, and refreshes the projection. It bails when
another fetch holds the lock, so ``sase goal list`` can spawn it on every
stale read without piling up workers. ``--fresh`` runs the same integration
synchronously through :func:`run_goals_fetch`.
"""

from __future__ import annotations

import fcntl
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_goals_fetch(
    project_key: str,
    *,
    timeout_seconds: float | None = 60.0,
    force: bool = False,
) -> dict[str, Any]:
    """Integrate, reconcile, and refresh *project_key*'s ledger once."""
    outcome: dict[str, Any] = {
        "project": project_key,
        "integrated": False,
        "reconciled": False,
        "refreshed": False,
        "skipped": None,
        "error": None,
    }
    from sase.goals.config import goals_fetch_ttl_seconds
    from sase.goals.store import resolve_goal_ledger
    from sase.goals.sync_status import goals_fetch_lock_path

    ledger = resolve_goal_ledger(project_key)
    if ledger.mode == "local" or ledger.hidden_clone is None:
        outcome["skipped"] = "local only"
        return outcome
    if not force:
        ttl = goals_fetch_ttl_seconds()
        try:
            age = time.time() - ledger.watermark_path.stat().st_mtime
        except OSError:
            age = float("inf")
        if age < ttl:
            outcome["skipped"] = "fresh"
            return outcome
    lock_path = goals_fetch_lock_path(ledger)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                outcome["skipped"] = "another fetch is running"
                return outcome
            try:
                return _fetch_under_lock(ledger, outcome, timeout_seconds)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        outcome["error"] = str(exc) or type(exc).__name__
        return outcome


def _fetch_under_lock(
    ledger: Any, outcome: dict[str, Any], timeout_seconds: float | None
) -> dict[str, Any]:
    from sase.goals.reconcile import reconcile_goals_after_integration

    assert ledger.hidden_clone is not None
    repo = ledger.hidden_clone
    deadline = (
        time.monotonic() + max(0.0, timeout_seconds)
        if timeout_seconds is not None
        else None
    )
    try:
        from sase.sdd._git_contention import (
            handoff_store_git_write_lock,
            store_git_write_lock,
        )
        from sase.sdd._repository_transaction import integrate_sdd_repository

        beads_dir = repo / "beads"
        with store_git_write_lock(
            repo, op="goals.fetch", mutates_worktree=True
        ) as acquired:
            if not acquired:
                outcome["skipped"] = "store lock busy"
                return outcome
            integration = integrate_sdd_repository(
                repo,
                beads_dir=beads_dir if beads_dir.exists() else None,
                op_prefix="goals.fetch",
                lock_factory=handoff_store_git_write_lock,
            )
        outcome["integrated"] = bool(integration.integrated)
        if not integration.succeeded:
            outcome["error"] = integration.error or "integration failed"
            return outcome
    except Exception as exc:  # noqa: BLE001 - fetch fails open.
        logger.warning("goals fetch for %s failed: %s", ledger.project, exc)
        outcome["error"] = str(exc) or type(exc).__name__
        return outcome
    try:
        reconcile = reconcile_goals_after_integration(ledger)
        outcome["reconciled"] = bool(reconcile.get("fixed"))
        if reconcile.get("commit"):
            _push_after_reconcile(repo, deadline)
    except Exception as exc:  # noqa: BLE001 - reconcile fails open.
        logger.warning("goals fetch reconcile for %s failed: %s", ledger.project, exc)
    try:
        from sase.core.goal_ledger_facade import goal_projection_refresh
        from sase.goals.config import goals_fetch_ttl_seconds

        goal_projection_refresh(
            ledger.root,
            ledger.projection_path,
            ledger.project,
            ledger.mode,
            watermark_path=ledger.watermark_path,
            outbox_path=ledger.outbox_path,
            fetch_ttl_seconds=goals_fetch_ttl_seconds(),
        )
        outcome["refreshed"] = True
    except Exception as exc:  # noqa: BLE001 - projection refresh fails open.
        logger.warning(
            "goals projection refresh for %s failed: %s", ledger.project, exc
        )
        outcome["error"] = str(exc) or type(exc).__name__
    return outcome


def _push_after_reconcile(repo: Path, deadline: float | None) -> None:
    from sase.bead.sync import push_bead_work_launch

    remaining = max(0.0, deadline - time.monotonic()) if deadline is not None else 0.0
    try:
        push_bead_work_launch(repo, worker_lock_wait=0.0, deadline=deadline)
    except Exception as exc:  # noqa: BLE001 - follow-up push fails open.
        logger.warning("goals reconcile follow-up push failed: %s", exc)
    _ = remaining


def maybe_spawn_goals_fetch(project_key: str) -> bool:
    """Spawn a detached fetch worker when the watermark is stale.

    Returns True when a worker was spawned. Consumed by ``sase goal list``.
    """
    try:
        from sase.goals.config import goals_fetch_ttl_seconds
        from sase.goals.store import resolve_goal_ledger
        from sase.goals.sync_status import goals_fetch_lock_path

        ledger = resolve_goal_ledger(project_key)
        if ledger.mode == "local" or ledger.hidden_clone is None:
            return False
        try:
            age = time.time() - ledger.watermark_path.stat().st_mtime
        except OSError:
            age = float("inf")
        if age < goals_fetch_ttl_seconds():
            return False
        lock_path = goals_fetch_lock_path(ledger)
        import fcntl as _fcntl

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            probe = open(lock_path, "a+", encoding="utf-8")  # noqa: PTH123
            try:
                _fcntl.flock(probe.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                _fcntl.flock(probe.fileno(), _fcntl.LOCK_UN)
            except BlockingIOError:
                return False
            finally:
                probe.close()
        except OSError:
            return False
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "sase.goals.fetch_worker", project_key],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001 - spawn fails open.
        logger.warning("goals fetch spawn for %s failed: %s", project_key, exc)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m sase.goals.fetch_worker <project>", file=sys.stderr)
        return 2
    outcome = run_goals_fetch(args[0], force=True)
    if outcome.get("error"):
        print(f"goals fetch for {args[0]}: {outcome['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
