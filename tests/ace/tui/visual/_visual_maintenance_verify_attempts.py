"""Shared serial driver for screenshot verification recaptures."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
import time

from tests.ace.tui.visual._visual_capture import InventoryReport, load_inventory
from tests.ace.tui.visual._visual_maintenance_exec import (
    TIMEOUT_EXIT_CODE,
    run_pytest,
)
from tests.ace.tui.visual._visual_maintenance_manifest import posix_relative
from tests.ace.tui.visual._visual_maintenance_types import (
    AttemptRecord,
    MaintenanceHooks,
)


def _load_if_present(path: Path) -> InventoryReport | None:
    """Return the inventory at *path*, or None when missing or unreadable."""
    if not path.is_file():
        return None
    try:
        return load_inventory(path)
    except Exception:
        return None


def _run_one_verify_attempt(
    *,
    hooks: MaintenanceHooks,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    attempt_index: int,
    owners: Sequence[str],
    workers: int | None,
    timeout_seconds: float | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[AttemptRecord, Path, InventoryReport | None, bool]:
    """Run one targeted recapture into a fresh directory.

    Update-mode agreement and check-mode recapture share this pytest pass.
    Returns the attempt record, capture directory, inventory (when the
    child wrote one), and whether the recapture budget expired mid-batch:
    the child was stopped and its evidence must not cure the first pass.
    """
    dir_name = "verify" if attempt_index == 1 else f"verify-{attempt_index}"
    attempt_dir = run_dir / dir_name
    attempt_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{dir_name}.log"
    log_rel = posix_relative(log_path, repo_root)
    attempt_run_id = (
        f"{run_id}-verify" if attempt_index == 1 else f"{run_id}-verify-{attempt_index}"
    )
    child_exit = run_pytest(
        hooks,
        repo_root=repo_root,
        capture_dir=attempt_dir,
        run_id=attempt_run_id,
        scope="targeted",
        pytest_args=tuple(owners),
        log_path=log_path,
        workers=workers,
        timeout_seconds=timeout_seconds,
    )
    attempt = AttemptRecord(
        label=dir_name,
        run_id=attempt_run_id,
        capture_dir=posix_relative(attempt_dir, repo_root),
        log=log_rel,
        workers=workers,
        child_exit_code=child_exit,
    )
    timed_out = (
        deadline is not None and child_exit == TIMEOUT_EXIT_CODE and clock() >= deadline
    )
    return (
        attempt,
        attempt_dir,
        _load_if_present(attempt_dir / "inventory.json"),
        timed_out,
    )


@dataclass
class AttemptDriver:
    """Shared serial verify-attempt loop for update-mode and check-mode."""

    hooks: MaintenanceHooks
    repo_root: Path
    run_id: str
    run_dir: Path
    max_attempts: int
    workers_for_attempt: Callable[[int], int | None]
    deadline: float | None = None
    clock: Callable[[], float] = time.monotonic
    budget_exhausted: bool = False

    def run_while(
        self,
        owners_fn: Callable[[], Sequence[str]],
    ) -> Iterator[tuple[int, AttemptRecord, Path, InventoryReport | None]]:
        """Yield pytest recapture attempts until owners empty, max, or budget.

        The remaining wall-clock budget rides into each governed attempt so
        a quiet or hung child cannot block past the deadline; a stopped
        child marks the budget exhausted instead of yielding evidence.
        """
        for attempt_index in range(1, self.max_attempts + 1):
            owners = list(owners_fn())
            if not owners:
                return
            if self.deadline is not None and self.clock() >= self.deadline:
                self.budget_exhausted = True
                return
            timeout_seconds: float | None = None
            if self.deadline is not None:
                timeout_seconds = max(0.0, self.deadline - self.clock())
            workers = self.workers_for_attempt(attempt_index)
            attempt, attempt_dir, inventory, timed_out = _run_one_verify_attempt(
                hooks=self.hooks,
                repo_root=self.repo_root,
                run_id=self.run_id,
                run_dir=self.run_dir,
                attempt_index=attempt_index,
                owners=owners,
                workers=workers,
                timeout_seconds=timeout_seconds,
                deadline=self.deadline,
                clock=self.clock,
            )
            if timed_out:
                # A stopped child leaves no trustworthy inventory behind;
                # partial logs survive in the attempt log. Remaining nodes
                # keep their first-pass outcome below.
                self.budget_exhausted = True
                inventory = None
            yield attempt_index, attempt, attempt_dir, inventory
