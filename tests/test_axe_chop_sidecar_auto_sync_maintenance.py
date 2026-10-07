"""Maintenance legs and live-wait scan tests for the sidecar auto-sync chop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase._sidecar_auto_sync import SidecarSyncResult
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
    """Unit coverage for the scan folded in from the retired waiter-refresh chop."""

    def _record(
        self,
        tmp_path: Path,
        *,
        project_name: str = "proj",
        suffix: str = "waiter",
        wait_for_beads: list[str] | None = None,
        ready: bool = False,
    ) -> SimpleNamespace:
        artifact_dir = tmp_path / project_name / suffix
        artifact_dir.mkdir(parents=True)
        if ready:
            (artifact_dir / "ready.json").write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(
            project_name=project_name,
            artifact_dir=str(artifact_dir),
            waiting=SimpleNamespace(
                wait_for_beads=(
                    ["sase-1"] if wait_for_beads is None else wait_for_beads
                )
            ),
            agent_meta=SimpleNamespace(pid=123, stopped_at=None),
        )

    def _scan(
        self,
        monkeypatch: pytest.MonkeyPatch,
        records: list[SimpleNamespace],
    ) -> None:
        monkeypatch.setattr(
            sidecar_sync_chop,
            "scan_agent_artifacts",
            lambda _root, _options: SimpleNamespace(records=records),
        )
        monkeypatch.setattr(
            sidecar_sync_chop, "is_process_alive", lambda _meta, _p: True
        )

    def test_live_bead_wait_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._scan(monkeypatch, [self._record(tmp_path)])

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == {"proj"}

    def test_multiple_waiters_in_one_project_are_deduplicated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._scan(
            monkeypatch,
            [
                self._record(tmp_path, suffix="one"),
                self._record(tmp_path, suffix="two"),
            ],
        )

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == {"proj"}

    def test_ready_bead_wait_is_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._scan(monkeypatch, [self._record(tmp_path, ready=True)])

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == frozenset()

    def test_non_bead_wait_is_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._scan(monkeypatch, [self._record(tmp_path, wait_for_beads=[])])

        assert sidecar_sync_chop._projects_with_live_bead_waits(tmp_path) == frozenset()

    def test_dead_waiter_is_dropped_but_uncertain_liveness_fails_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dead = self._record(tmp_path, project_name="dead")
        uncertain = self._record(tmp_path, project_name="uncertain")
        self._scan(monkeypatch, [dead, uncertain])

        def liveness(_meta: dict[str, object], artifact_dir: Path) -> bool:
            if artifact_dir == Path(dead.artifact_dir):
                return False
            raise PermissionError("liveness unavailable")

        monkeypatch.setattr(sidecar_sync_chop, "is_process_alive", liveness)

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
