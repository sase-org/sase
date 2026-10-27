"""Shared builders for stranded-bead wait_checks tests.

Split from ``tests.test_axe_chop_wait_checks_stranded_beads``. Not a
conftest so files opt in by importing the helpers directly. Names are
public so the split modules can share them without importing
``_``-prefixed names across files.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import sase.scripts._chop_wait_checks_run as wait_checks_run
import sase.scripts._chop_wait_checks_run_waiters as wait_checks_waiters
import sase.scripts._chop_wait_checks_stranded as stranded_cache
from sase.notifications.models import Notification
from sase.notifications.store import append_notification

from tests._axe_chop_wait_checks_helpers import make_waiting_agent
from tests._stranded_collector_helpers import wire_collector

__all__ = [
    "STRANDED_BEAD_ID",
    "STRANDED_PARENT_ID",
    "capture_collection_targets",
    "ensure_projects_dir",
    "make_waiters",
    "point_wait_bead_status",
    "seed_stranded_notification",
    "wire_targeted_collector",
]

STRANDED_BEAD_ID = "sase-1.2"
STRANDED_PARENT_ID = "sase-1"


def point_wait_bead_status(
    monkeypatch: pytest.MonkeyPatch,
    closed: set[str] | None = None,
) -> None:
    monkeypatch.setattr(
        wait_checks_waiters,
        "closed_bead_ids_for_waits",
        lambda *_args, **_kwargs: SimpleNamespace(closed_ids=frozenset(closed or ())),
    )


def wire_targeted_collector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    issues: list,
    records: list,
) -> Path:
    beads_dir = wire_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(
        stranded_cache,
        "canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    def statuses_for_project(_project: str, bead_ids: object) -> dict[str, str]:
        wanted = {str(bead_id) for bead_id in bead_ids}
        return {issue.id: issue.status.value for issue in issues if issue.id in wanted}

    monkeypatch.setattr(
        wait_checks_run,
        "bead_statuses_for_project",
        statuses_for_project,
    )
    return beads_dir


def seed_stranded_notification(project: str, bead_id: str) -> None:
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="wait_checks",
            notes=[f"Stranded bead: {bead_id}"],
            tags=["wait", "blocked", "stranded"],
            dedup_key=f"wait_checks:stranded-bead:{project}:{bead_id}",
        )
    )


def ensure_projects_dir(tmp_path: Path) -> None:
    (tmp_path / ".sase" / "projects" / "proj").mkdir(parents=True, exist_ok=True)


def capture_collection_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []
    real = wait_checks_run.collect_targeted_stranded_report

    def wrapped(
        project: str,
        bead_ids: set[str] | frozenset[str] | tuple[str, ...],
        *,
        now: float,
    ):
        calls.append((project, tuple(sorted(bead_ids))))
        return real(project, bead_ids, now=now)

    monkeypatch.setattr(wait_checks_run, "collect_targeted_stranded_report", wrapped)
    return calls


def make_waiters(tmp_path: Path, *suffixes: str) -> list[Path]:
    waiters = [
        make_waiting_agent(
            tmp_path,
            suffix=suffix,
            wait_for_beads=[STRANDED_BEAD_ID],
        )
        for suffix in suffixes
    ]
    for index, waiter_dir in enumerate(waiters, start=1):
        path = waiter_dir / "waiting.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cl_name"] = f"waiter-{index}"
        path.write_text(json.dumps(data), encoding="utf-8")
    return waiters
