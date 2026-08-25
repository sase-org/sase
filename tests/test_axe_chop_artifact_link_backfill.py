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
from sase.sdd.artifact_link_backfill import (
    ArtifactLinkBackfillReport,
    ArtifactLinkReconcileReport,
)


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
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
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _project(tmp_path: Path, *, name: str = "proj") -> SimpleNamespace:
    workspace_dir = tmp_path / "projects" / name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        is_project=True,
        workspace_dir=str(workspace_dir),
        project_name=name,
    )


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
            ArtifactLinkBackfillReport(scanned=3, persisted=2, remaining=1),
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
        lambda store: ArtifactLinkReconcileReport(repaired_renames=2),
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
        if cwd is not None and "broken" in str(cwd):
            raise RuntimeError("no project here")
        return object()

    monkeypatch.setattr(backfill_chop, "resolve_artifact_link_store", _resolve)
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store: ArtifactLinkReconcileReport(),
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
        store: object, *, already_swept: frozenset[str], batch_size: int
    ) -> tuple[ArtifactLinkBackfillReport, frozenset[str]]:
        seen_already_swept.append(already_swept)
        return ArtifactLinkBackfillReport(), already_swept | {"plan:202608/a.md"}

    monkeypatch.setattr(backfill_chop, "run_artifact_link_backfill_batch", _fake_batch)
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None: SimpleNamespace(drained=0, dropped=0),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store: ArtifactLinkReconcileReport(),
    )

    backfill_chop._run(_runtime(tmp_path))
    backfill_chop._run(_runtime(tmp_path))

    assert seen_already_swept == [frozenset(), frozenset({"plan:202608/a.md"})]
