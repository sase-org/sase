"""Generic primary-sidecar auto-sync chop tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase._sidecar_auto_sync import SidecarSyncResult
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="sidecar_auto_sync",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _project(
    tmp_path: Path,
    *,
    name: str = "proj",
) -> SimpleNamespace:
    workspace_dir = tmp_path / "projects" / name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    project_file = tmp_path / "projects" / f"{name}.project"
    project_file.write_text(
        "WORKSPACE_DIR=" + str(workspace_dir) + "\n", encoding="utf-8"
    )
    return SimpleNamespace(
        is_project=True,
        workspace_dir=str(workspace_dir),
        project_name=name,
        project_file=str(project_file),
    )


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    records: list[SimpleNamespace],
    roles_by_project: dict[str, tuple[str, ...]],
    hinted_by_project: dict[str, tuple[str, ...]] | None = None,
    live_bead_wait_projects: frozenset[str] = frozenset(),
    bead_refresh_mode: str = "background",
) -> None:
    monkeypatch.setattr(sidecar_sync_chop, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(
        sidecar_sync_chop, "list_project_records", lambda *_a, **_kw: records
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "auto_sync_roles",
        lambda primary: roles_by_project.get(Path(primary).name, ()),
    )
    hinted = hinted_by_project or {}
    monkeypatch.setattr(
        sidecar_sync_chop,
        "pending_sidecar_sync_roles",
        lambda project_key: hinted.get(project_key, ()),
    )
    monkeypatch.setattr(
        sidecar_sync_chop, "bead_refresh_mode", lambda: bead_refresh_mode
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "_projects_with_live_bead_waits",
        lambda _root: live_bead_wait_projects,
    )
    monkeypatch.setattr(sidecar_sync_chop, "mark_sidecar_sync_hint", MagicMock())


def test_no_auto_sync_roles_short_circuits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={},
    )

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    assert result.reason == "no_auto_sync_roles"
    assert result.counters["targets"] == 0


def test_hinted_role_refreshes_and_clears_its_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("plans",)},
        hinted_by_project={"proj": ("plans",)},
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "plans", "refreshed", "fast-forwarded")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    clear = MagicMock()
    monkeypatch.setattr(sidecar_sync_chop, "clear_sidecar_sync_hint", clear)

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    sync.assert_called_once()
    args, kwargs = sync.call_args
    assert args[0] == "proj"
    assert args[1] == "plans"
    clear.assert_called_once_with("proj", "plans")
    assert result.status == "ok"
    assert result.counters["refreshed"] == 1


def test_unhinted_role_backstops_then_skips_within_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("beads",)},
    )
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "beads", "up_to_date", "already fresh")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    runtime = _runtime(tmp_path)

    first = sidecar_sync_chop._run(runtime)
    second = sidecar_sync_chop._run(runtime)

    assert sync.call_count == 1
    assert first.counters["up_to_date"] == 1
    assert second.counters["backed_off"] == 1

    current_time[0] = now + timedelta(
        seconds=sidecar_sync_chop._BACKSTOP_INTERVAL_SECONDS + 1
    )
    third = sidecar_sync_chop._run(runtime)

    assert sync.call_count == 2
    assert third.counters["up_to_date"] == 1


def test_failure_like_status_backs_off_exponentially(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("research",)},
    )
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "research", "dirty", "local changes")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    runtime = _runtime(tmp_path)

    failed = sidecar_sync_chop._run(runtime)
    backed_off = sidecar_sync_chop._run(runtime)

    assert failed.counters["failed"] == 1
    assert failed.reason == "sync_failed"
    assert backed_off.counters["backed_off"] == 1
    assert sync.call_count == 1

    state_path = (
        Path(runtime.context.state_dir) / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    )
    stored = json.loads(state_path.read_text(encoding="utf-8"))
    assert stored["proj:research"]["failures"] == 1


def test_hinted_role_bypasses_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("beads",)},
        hinted_by_project={"proj": ()},
    )
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    outcomes = iter(
        [
            SidecarSyncResult("proj", "beads", "dirty", "local changes"),
            SidecarSyncResult("proj", "beads", "refreshed", "fast-forwarded"),
        ]
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        lambda *_a, **_kw: next(outcomes),
    )
    monkeypatch.setattr(sidecar_sync_chop, "clear_sidecar_sync_hint", MagicMock())
    runtime = _runtime(tmp_path)

    sidecar_sync_chop._run(runtime)

    # A hint arrives before the exponential backoff window would allow a
    # normal retry; the hinted attempt still runs immediately.
    monkeypatch.setattr(
        sidecar_sync_chop, "pending_sidecar_sync_roles", lambda _project_key: ("beads",)
    )
    hinted = sidecar_sync_chop._run(runtime)

    assert hinted.counters["refreshed"] == 1
    assert hinted.counters["backed_off"] == 0


def test_multiple_roles_in_one_project_are_all_attempted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("plans", "beads", "research", "custom_docs")},
    )
    seen: list[str] = []

    def sync(project: str, role: str, **_kwargs: object) -> SidecarSyncResult:
        seen.append(role)
        return SidecarSyncResult(project, role, "up_to_date", "already fresh")

    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    assert sorted(seen) == ["beads", "custom_docs", "plans", "research"]
    assert result.counters["targets"] == 4
    assert result.counters["up_to_date"] == 4


def test_stale_schedule_entries_are_pruned_for_deconfigured_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path, name="alive")],
        roles_by_project={"alive": ("plans",)},
    )
    runtime = _runtime(tmp_path)
    state_path = (
        Path(runtime.context.state_dir) / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "gone:beads": {
                    "failures": 3,
                    "next_attempt_at": "2099-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        lambda project, role, **_kw: SidecarSyncResult(
            project, role, "up_to_date", "already fresh"
        ),
    )

    result = sidecar_sync_chop._run(runtime)

    assert result.counters["up_to_date"] == 1
    assert "gone:beads" not in json.loads(state_path.read_text(encoding="utf-8"))


def test_exhausted_work_budget_defers_remaining_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path, name="one"), _project(tmp_path, name="two")],
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

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    assert sync.call_count == 1
    assert result.counters["up_to_date"] == 1
    assert result.counters["deferred"] == 1


def test_corrupt_schedule_state_is_treated_as_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("plans",)},
    )
    runtime = _runtime(tmp_path)
    state_path = (
        Path(runtime.context.state_dir) / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not-json", encoding="utf-8")
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "plans", "refreshed", "fast-forwarded")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(runtime)

    sync.assert_called_once()
    assert result.counters["refreshed"] == 1


def test_live_bead_wait_forces_a_beads_target_without_auto_sync_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={},
        live_bead_wait_projects=frozenset({"proj"}),
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "beads", "refreshed", "fast-forwarded")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    sync.assert_called_once()
    args, kwargs = sync.call_args
    assert args[0] == "proj"
    assert args[1] == "beads"
    assert kwargs["require_auto_sync_opt_in"] is False
    assert result.counters["targets"] == 1
    assert result.counters["refreshed"] == 1
    sidecar_sync_chop.mark_sidecar_sync_hint.assert_called_once_with("proj", "beads")


def test_live_bead_wait_does_not_duplicate_an_already_opted_in_beads_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={"proj": ("beads",)},
        live_bead_wait_projects=frozenset({"proj"}),
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "beads", "up_to_date", "already fresh")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    sync.assert_called_once()
    _args, kwargs = sync.call_args
    assert kwargs["require_auto_sync_opt_in"] is True
    assert result.counters["targets"] == 1


def test_bead_refresh_mode_off_skips_the_live_wait_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        records=[_project(tmp_path)],
        roles_by_project={},
        bead_refresh_mode="off",
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "_projects_with_live_bead_waits",
        lambda _root: pytest.fail("disabled bead refresh scanned artifacts"),
    )

    result = sidecar_sync_chop._run(_runtime(tmp_path))

    assert result.reason == "no_auto_sync_roles"
    sidecar_sync_chop.mark_sidecar_sync_hint.assert_not_called()


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
