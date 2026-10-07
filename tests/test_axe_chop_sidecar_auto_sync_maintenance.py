"""Maintenance legs and live-wait scan tests for the sidecar auto-sync chop."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase._sidecar_auto_sync import SidecarSyncResult
from tests._agent_names_fixtures import DEAD_PID
from tests._axe_chop_sidecar_auto_sync_support import (
    configure_sidecar_sync,
    make_project,
    make_runtime,
)


def test_successful_sync_runs_sidecar_maintenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    clone_dir = Path(project.workspace_dir) / "sase" / "repos" / "beads"
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[project],
        roles_by_project={"proj": ("beads",)},
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        MagicMock(
            return_value=SidecarSyncResult(
                "proj",
                "beads",
                "up_to_date",
                "already fresh",
                str(clone_dir),
            )
        ),
    )
    maintained: list[tuple[Path, Path]] = []

    def record_maintenance(clone: Path, primary: Path) -> bool:
        maintained.append((clone, primary))
        return True

    monkeypatch.setattr(sidecar_sync_chop, "maybe_gc_sidecar_clone", record_maintenance)

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.counters["up_to_date"] == 1
    assert maintained == [(clone_dir, Path(project.workspace_dir))]


class TestProjectsWithLiveBeadWaits:
    """Unit coverage for the shared-walk live bead-wait scan."""

    def _record(
        self,
        tmp_path: Path,
        *,
        project_name: str = "proj",
        suffix: str = "waiter",
        wait_for_beads: list[str] | None = None,
        ready: bool = False,
        meta: dict | None = None,
        raw_waiting: str | None = None,
    ) -> Path:
        artifact_dir = tmp_path / project_name / "artifacts" / "ace-run" / suffix
        artifact_dir.mkdir(parents=True)
        if raw_waiting is not None:
            (artifact_dir / "waiting.json").write_text(raw_waiting, encoding="utf-8")
        else:
            (artifact_dir / "waiting.json").write_text(
                json.dumps(
                    {
                        "waiting_for": [],
                        "cl_name": "waiter",
                        "wait_for_beads": (
                            ["sase-1"] if wait_for_beads is None else wait_for_beads
                        ),
                    }
                ),
                encoding="utf-8",
            )
        if meta is not None:
            (artifact_dir / "agent_meta.json").write_text(
                json.dumps(meta), encoding="utf-8"
            )
        if ready:
            (artifact_dir / "ready.json").write_text("{}\n", encoding="utf-8")
        return artifact_dir

    def test_live_bead_wait_is_reported(self, tmp_path: Path) -> None:
        self._record(tmp_path)

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == {"proj"}

    def test_multiple_waiters_in_one_project_are_deduplicated(
        self, tmp_path: Path
    ) -> None:
        self._record(tmp_path, suffix="one")
        self._record(tmp_path, suffix="two")

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == {"proj"}

    def test_ready_bead_wait_is_excluded(self, tmp_path: Path) -> None:
        self._record(tmp_path, ready=True)

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == frozenset()

    def test_non_bead_wait_is_excluded(self, tmp_path: Path) -> None:
        self._record(tmp_path, wait_for_beads=[])

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == frozenset()

    def test_malformed_bead_wait_is_excluded(self, tmp_path: Path) -> None:
        self._record(tmp_path, raw_waiting="not json\n")

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == frozenset()

    def test_dead_waiter_is_dropped_but_uncertain_liveness_fails_open(
        self, tmp_path: Path
    ) -> None:
        self._record(
            tmp_path,
            project_name="dead",
            meta={"name": "dead-waiter", "pid": DEAD_PID},
        )
        # No agent_meta.json: liveness is unknown, so the waiter counts.
        self._record(tmp_path, project_name="uncertain")

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == {
            "uncertain"
        }


def test_run_visits_hidden_clones_for_each_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[
            make_project(tmp_path, name="one"),
            make_project(tmp_path, name="two"),
        ],
        roles_by_project={"one": ("plans",), "two": ("plans",)},
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        MagicMock(
            side_effect=lambda project, role, **_k: SidecarSyncResult(
                project, role, "up_to_date", "already fresh"
            )
        ),
    )
    visited: list[tuple[str, str]] = []

    def record_leg(runtime: object, records: list[object], work_deadline: float) -> int:
        visited.extend(
            (record.project_name, record.workspace_dir)
            for record in records  # type: ignore[union-attr]
        )
        return len(records)

    # Override the hermetic stub from configure_sidecar_sync with a recording leg.
    monkeypatch.setattr(
        sidecar_sync_chop, "_maintain_hidden_sidecar_clones", record_leg
    )

    sidecar_sync_chop._run(make_runtime(tmp_path))

    assert sorted(key for key, _ in visited) == ["one", "two"]


def test_run_skips_maintenance_legs_when_budget_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[
            make_project(tmp_path, name="one"),
            make_project(tmp_path, name="two"),
        ],
        roles_by_project={"one": ("plans",), "two": ("plans",)},
    )
    clock = iter([0.0, 0.0, sidecar_sync_chop._WORK_BUDGET_SECONDS + 1.0])
    monkeypatch.setattr(
        sidecar_sync_chop,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock)),
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("one", "plans", "up_to_date", "already fresh")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    monkeypatch.setattr(
        sidecar_sync_chop,
        "maintain_hidden_sidecar_clones",
        lambda *_a, **_k: pytest.fail("budget-exhausted hidden gc ran"),
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "_maintain_hidden_sidecar_clones",
        lambda *_a, **_k: pytest.fail("budget-exhausted hidden leg ran"),
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "_prune_bead_push_logs",
        lambda *_a, **_k: pytest.fail("budget-exhausted push-log prune ran"),
    )

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.counters["deferred"] == 1


def test_prune_leg_delegates_to_sync_log_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Grab the real leg before configure_sidecar_sync installs the hermetic stub.
    real_prune_leg = sidecar_sync_chop._prune_bead_push_logs
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
    )
    pruned: list[bool] = []
    monkeypatch.setattr(
        "sase.bead._sync_logs.prune_old_bead_sync_logs",
        lambda **_k: pruned.append(True) or 3,
    )

    assert real_prune_leg(make_runtime(tmp_path)) == 3
    assert pruned == [True]
