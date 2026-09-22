"""Project selection tests for the ``artifact_link_backfill`` chop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts.sase_chop_artifact_link_backfill as backfill_chop
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.sdd.artifact_link_backfill import (
    _ArtifactLinkBackfillReport,
    _ArtifactLinkReconcileReport,
)

from tests._axe_chop_artifact_link_backfill_helpers import (
    _default_no_publication_retry,  # noqa: F401 (registers the autouse fixture)
    _project,
    _record,
    _runtime,
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


def test_project_cursor_starts_after_last_started_project() -> None:
    records = [
        ProjectRecordWire(
            schema_version=3,
            project_name=name,
            project_dir=f"/tmp/{name}",
            project_file=f"/tmp/{name}/{name}.sase",
            archive_file=None,
            workspace_dir=f"/tmp/work/{name}",
            state="enabled",
            state_explicit=False,
            system_managed=False,
            active_claim_count=0,
            launchable=True,
            aliases=[],
            warnings=[],
            parse_warnings=[],
            display_name=None,
            is_project=True,
            vcs_kind="gh",
        )
        for name in ("p1", "p2", "p3")
    ]

    rotated = backfill_chop._rotate_records(records, "p2")

    assert [record.project_name for record in rotated] == ["p2", "p3", "p1"]
    assert backfill_chop._next_cursor_after(rotated, "p2") == "p3"


def test_resolves_the_machine_store_with_the_project_key_and_primary_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, name="widget")
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: [project])
    calls: list[tuple[str, Path]] = []

    def _resolve(project_key: str, primary_checkout: Path, **kwargs: object) -> object:
        assert kwargs["deadline"] is not None
        calls.append((project_key, primary_checkout))
        return object()

    monkeypatch.setattr(backfill_chop, "resolve_machine_artifact_link_store", _resolve)
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=0, dropped=0, deferred=False
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    backfill_chop._run(_runtime(tmp_path))

    assert calls == [("widget", Path(project.workspace_dir))]


def test_a_broken_project_is_recorded_and_does_not_stop_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="broken"), _project(tmp_path, name="ok")],
    )

    def _resolve(project_key: str, primary_checkout: Path, **_kwargs: object) -> object:
        if Path(primary_checkout).name == "broken":
            raise RuntimeError("no project here")
        return object()

    monkeypatch.setattr(backfill_chop, "resolve_machine_artifact_link_store", _resolve)
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=0, dropped=0, deferred=False
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.counters["projects"] == 1
    assert result.counters["failed_projects"] == 1
