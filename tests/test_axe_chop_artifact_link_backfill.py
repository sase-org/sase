"""``artifact_link_backfill`` housekeeping chop tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts.sase_chop_artifact_link_backfill as backfill_chop
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.sdd.artifact_link_backfill import (
    _ArtifactLinkBackfillReport,
    _ArtifactLinkReconcileReport,
)


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return _runtime_with_logs(tmp_path)[0]


def _runtime_with_logs(
    tmp_path: Path,
) -> tuple[BuiltinChopRuntime, StringIO, StringIO]:
    stdout = StringIO()
    stderr = StringIO()
    runtime = BuiltinChopRuntime(
        name="artifact_link_backfill",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="housekeeping",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=stdout, stderr=stderr),
    )
    return runtime, stdout, stderr


def _project(tmp_path: Path, *, name: str = "proj") -> SimpleNamespace:
    workspace_dir = tmp_path / "projects" / name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        is_project=True,
        workspace_dir=str(workspace_dir),
        project_name=name,
    )


def _record(
    tmp_path: Path, *, project_name: str, display_name: str | None = None
) -> ProjectRecordWire:
    workspace_dir = tmp_path / "projects" / project_name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return ProjectRecordWire(
        schema_version=3,
        project_name=project_name,
        project_dir=str(tmp_path / ".sase" / project_name),
        project_file=str(tmp_path / ".sase" / project_name / f"{project_name}.sase"),
        archive_file=None,
        workspace_dir=str(workspace_dir),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
        is_project=True,
        vcs_kind="gh",
    )


def test_prefers_current_workspace_for_matching_project_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_workspace = tmp_path / "workspaces" / "sase_12"
    current_workspace.mkdir(parents=True)
    marker = SimpleNamespace(
        project_name="sase",
        project_key="sase-org/sase",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.find_marker_from_cwd",
        lambda _cwd: (str(current_workspace), marker),
    )
    sase = _record(tmp_path, project_name="gh_sase-org__sase", display_name="sase")
    other = _record(tmp_path, project_name="gh_example__other", display_name="other")

    records = backfill_chop._prefer_current_workspace_record(
        [sase, other], cwd=current_workspace
    )

    assert records[0].workspace_dir == str(current_workspace.resolve(strict=False))
    assert records[1].workspace_dir == other.workspace_dir


def test_prefers_workspace_hint_when_chop_child_cwd_is_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_workspace = tmp_path / "workspaces" / "sase_12"
    state_dir = tmp_path / ".sase" / "axe" / "lumberjacks" / "housekeeping"
    current_workspace.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    marker = SimpleNamespace(
        project_name="sase",
        project_key="sase-org/sase",
    )
    monkeypatch.setenv("SASE_GH_WORKSPACE_DIR", str(current_workspace))

    def find_marker(cwd: str):
        if Path(cwd) == current_workspace.resolve(strict=False):
            return (str(current_workspace), marker)
        return None

    monkeypatch.setattr("sase.workspace_provider.find_marker_from_cwd", find_marker)
    sase = _record(tmp_path, project_name="gh_sase-org__sase", display_name="sase")

    records = backfill_chop._prefer_current_workspace_record([sase], cwd=state_dir)

    assert records[0].workspace_dir == str(current_workspace.resolve(strict=False))


def test_no_enabled_projects_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: [])

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.reason == "no_enabled_projects"
    assert result.counters["projects"] == 0


def test_runs_every_job_and_aggregates_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop, "resolve_artifact_link_store", lambda cwd=None: object()
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (
            _ArtifactLinkBackfillReport(scanned=3, persisted=2, remaining=1),
            frozenset({"plan:202608/a.md"}),
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=4, dropped=1),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(repaired_renames=2),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.counters["projects"] == 1
    assert result.counters["sweep_scanned"] == 3
    assert result.counters["sweep_persisted"] == 2
    assert result.counters["sweep_remaining"] == 1
    assert result.counters["outbox_drained"] == 4
    assert result.counters["outbox_dropped"] == 1
    assert result.counters["reconciled"] == 1
    assert result.counters["repaired_renames"] == 2

    state = (tmp_path / "state" / backfill_chop._STATE_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "plan:202608/a.md" in state


def test_a_broken_project_is_recorded_and_does_not_stop_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="broken"), _project(tmp_path, name="ok")],
    )

    def _resolve(cwd: Path | None = None) -> object:
        if cwd is not None and Path(cwd).name == "broken":
            raise RuntimeError("no project here")
        return object()

    monkeypatch.setattr(backfill_chop, "resolve_artifact_link_store", _resolve)
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.counters["projects"] == 1
    assert result.counters["failed_projects"] == 1


def test_checkpoint_survives_across_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop, "resolve_artifact_link_store", lambda cwd=None: object()
    )
    seen_already_swept: list[frozenset[str]] = []

    def _fake_batch(
        store: object,
        *,
        already_swept: frozenset[str],
        batch_size: int,
        deadline: float | None = None,
    ) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
        assert deadline is not None
        seen_already_swept.append(already_swept)
        return _ArtifactLinkBackfillReport(), already_swept | {"plan:202608/a.md"}

    monkeypatch.setattr(backfill_chop, "run_artifact_link_backfill_batch", _fake_batch)
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    backfill_chop._run(_runtime(tmp_path))
    backfill_chop._run(_runtime(tmp_path))

    assert seen_already_swept == [frozenset(), frozenset({"plan:202608/a.md"})]


def test_later_jobs_defer_after_sweep_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop, "resolve_artifact_link_store", lambda cwd=None: object()
    )
    now = [0.0]
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: now[0])

    def _fake_batch(
        store: object,
        *,
        already_swept: frozenset[str],
        batch_size: int,
        deadline: float | None = None,
    ) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
        now[0] = 46.0  # the sweep alone consumes the whole sweep budget
        return (
            _ArtifactLinkBackfillReport(scanned=1, persisted=1, remaining=1),
            already_swept | {"plan:202608/a.md"},
        )

    monkeypatch.setattr(backfill_chop, "run_artifact_link_backfill_batch", _fake_batch)
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: pytest.fail("outbox should defer"),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: pytest.fail("reconcile should defer"),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.counters["projects"] == 1
    assert result.counters["sweep_scanned"] == 1
    assert result.counters["sweep_remaining"] == 1
    assert result.counters["outbox_drained"] == 0
    assert result.counters["deferred_projects"] == 0
    state = (tmp_path / "state" / backfill_chop._STATE_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "plan:202608/a.md" in state


def test_chop_stops_starting_projects_past_the_chop_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = [_project(tmp_path, name=name) for name in ("p1", "p2", "p3")]
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: projects)
    monkeypatch.setattr(
        backfill_chop, "resolve_artifact_link_store", lambda cwd=None: object()
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    now = [0.0]
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: now[0])

    def _reconcile(store: object, **_kwargs: object) -> _ArtifactLinkReconcileReport:
        # p1's own reconcile job is what blows through the whole-chop budget.
        now[0] = backfill_chop._CHOP_WORK_BUDGET_SECONDS + 1.0
        return _ArtifactLinkReconcileReport()

    monkeypatch.setattr(
        backfill_chop, "reconcile_and_repair_artifact_links", _reconcile
    )

    runtime, stdout, stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    assert result.counters["projects"] == 1
    assert result.counters["deferred_projects"] == 2
    assert result.reason is None
    warnings = stderr.getvalue()
    assert "p2" in warnings
    assert "p3" in warnings


def test_per_project_progress_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="proj")],
    )
    monkeypatch.setattr(
        backfill_chop, "resolve_artifact_link_store", lambda cwd=None: object()
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    runtime, stdout, _stderr = _runtime_with_logs(tmp_path)
    backfill_chop._run(runtime)

    log_output = stdout.getvalue()
    assert "proj: starting" in log_output
    assert "proj: done" in log_output


def test_chop_passes_budget_through_and_warns_on_deferred_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="proj")],
    )
    monkeypatch.setattr(
        backfill_chop, "resolve_artifact_link_store", lambda cwd=None: object()
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    now = [0.0]
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: now[0])
    captured: list[dict[str, object]] = []

    def _reconcile(store: object, **kwargs: object) -> _ArtifactLinkReconcileReport:
        captured.append(kwargs)
        return _ArtifactLinkReconcileReport(deferred_refs=4)

    monkeypatch.setattr(
        backfill_chop, "reconcile_and_repair_artifact_links", _reconcile
    )

    runtime, _stdout, stderr = _runtime_with_logs(tmp_path)
    backfill_chop._run(runtime)

    assert captured == [{"deadline": backfill_chop._CHOP_WORK_BUDGET_SECONDS}]
    warning = stderr.getvalue()
    assert "proj" in warning
    assert "deferred 4" in warning
