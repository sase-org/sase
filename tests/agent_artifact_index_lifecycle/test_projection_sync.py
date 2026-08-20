from __future__ import annotations

import sqlite3
from pathlib import Path

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_artifact_index_lifecycle import (
    build_dismissed_agent_projection_inputs,
    read_agent_artifact_index_schema_status,
    refresh_agent_artifact_index_if_schema_stale,
    sync_dismissed_agent_artifact_index,
    sync_dismissed_agent_artifact_index_report,
)
from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AgentArtifactIndexUpdateWire,
)

from .helpers import (
    install_projection_meta_store,
    read_projection_meta,
    write_projection_meta,
)


def _write_index_schema_version(index: Path, version: int) -> None:
    with sqlite3.connect(index) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )


def test_sync_dismissed_agent_artifact_index_serializes_identities(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    install_projection_meta_store(monkeypatch)
    calls: list[tuple[Path, list[object]]] = []

    def fake_replace(index_path: Path, identities: list[object]) -> object:
        calls.append((index_path, identities))
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=len(identities),
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fake_replace,
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 0, 0, 0),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
        set,
    )

    assert sync_dismissed_agent_artifact_index(
        {(AgentType.RUNNING, "feature", "20260501010101")},
        index_path=index,
    )

    assert calls[0][0] == index
    assert calls[0][1][0].agent_type == "run"
    assert calls[0][1][0].cl_name == "feature"
    assert calls[0][1][0].raw_suffix == "20260501010101"


def test_build_dismissed_projection_inputs_reads_json_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 0),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_agents",
        lambda: {(AgentType.RUNNING, "json", "20260501010101")},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
        set,
    )

    projection = build_dismissed_agent_projection_inputs()

    assert [
        (row.agent_type, row.cl_name, row.raw_suffix) for row in projection.identities
    ] == [("run", "json", "20260501010101")]
    assert projection.dismissed_agents_signature == (10, 20)
    assert projection.dismissed_bundle_index_signature == (1, 30, 40, 0)


def test_build_dismissed_projection_inputs_reads_bundle_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 1),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
        lambda: {"ok": True},
    )
    monkeypatch.setattr("sase.ace.dismissed_agents.load_dismissed_agents", set)
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
        lambda: {("workflow", "bundle", "20260502020202")},
    )

    projection = build_dismissed_agent_projection_inputs()

    assert [
        (row.agent_type, row.cl_name, row.raw_suffix) for row in projection.identities
    ] == [("workflow", "bundle", "20260502020202")]


def test_build_dismissed_projection_inputs_combines_sources(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bundle_identities = {
        ("run", "unknown", "20260503030303"),
        ("run", "json", "20260501010101"),
    }
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 2),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_agents",
        lambda: {(AgentType.RUNNING, "json", "20260501010101")},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
        lambda: bundle_identities,
    )

    projection = build_dismissed_agent_projection_inputs()

    assert [
        (row.agent_type, row.cl_name, row.raw_suffix) for row in projection.identities
    ] == [
        ("run", "json", "20260501010101"),
        ("run", "unknown", "20260503030303"),
    ]


def test_sync_dismissed_projection_skips_when_metadata_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    meta_store = install_projection_meta_store(monkeypatch)
    write_projection_meta(
        meta_store,
        index,
        dismissed_agents_signature=[10, 20],
        dismissed_bundle_index_signature=[1, 30, 40, 2],
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 2),
    )

    def fail_replace(*args: object, **kwargs: object) -> object:
        raise AssertionError("projection should have been skipped")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fail_replace,
    )

    assert sync_dismissed_agent_artifact_index(index_path=index)


def test_active_tier_maintenance_marks_fast_path_report_changed(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    meta_store = install_projection_meta_store(monkeypatch)
    write_projection_meta(
        meta_store,
        index,
        dismissed_agents_signature=[10, 20],
        dismissed_bundle_index_signature=[1, 30, 40, 2],
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 2),
    )

    def fake_terminalize(
        index_path: Path,
        projects_root: Path,
        *,
        stale_after_seconds: int,
        max_rows: int | None,
        options: object,
    ) -> AgentArtifactIndexUpdateWire:
        del projects_root, stale_after_seconds, max_rows, options
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=3,
            hidden_terminal_rows_retained=4096,
            hidden_terminal_rows_pruned=12,
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "terminalize_stale_active_agent_artifact_index_rows",
        fake_terminalize,
    )

    report = sync_dismissed_agent_artifact_index_report(index_path=index)

    assert report.synced
    assert report.changed
    assert report.terminalized_active_rows == 3
    assert report.hidden_terminal_rows_retained == 4096
    assert report.hidden_terminal_rows_pruned == 12


def test_projection_sync_can_skip_active_tier_maintenance(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    install_projection_meta_store(monkeypatch)
    calls: list[tuple[Path, list[object]]] = []
    identity = (AgentType.RUNNING, "kept", "20260501010101")

    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 0),
    )

    def fake_replace(index_path: Path, identities: list[object]) -> object:
        calls.append((index_path, identities))
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=len(identities),
        )

    def fail_terminalize(*args: object, **kwargs: object) -> object:
        raise AssertionError("terminalizer should be skipped")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fake_replace,
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "terminalize_stale_active_agent_artifact_index_rows",
        fail_terminalize,
    )

    report = sync_dismissed_agent_artifact_index_report(
        {identity},
        added={identity},
        index_path=index,
        run_active_tier_maintenance=False,
    )

    assert report.synced
    assert report.changed
    assert report.terminalized_active_rows == 0
    assert calls[0][0] == index


def test_stale_schema_refresh_rebuilds_before_index_query(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_index_schema_version(index, AGENT_ARTIFACT_INDEX_SCHEMA_VERSION - 1)
    calls: list[tuple[Path, Path]] = []

    def fake_rebuild(
        index_path: Path,
        root: Path,
        options: object,
    ) -> AgentArtifactIndexUpdateWire:
        del options
        calls.append((Path(index_path), Path(root)))
        return AgentArtifactIndexUpdateWire(
            schema_version=AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
            index_path=str(index_path),
            projects_root=str(root),
            rows_indexed=7,
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_schema.rebuild_agent_artifact_index",
        fake_rebuild,
    )

    report = refresh_agent_artifact_index_if_schema_stale(
        index_path=index,
        projects_root=projects_root,
    )

    assert calls == [(index, projects_root)]
    assert report.checked
    assert report.refreshed
    assert report.stored_schema_version == AGENT_ARTIFACT_INDEX_SCHEMA_VERSION - 1
    assert report.rows_indexed == 7


def test_schema_status_reads_staleness_without_rebuilding(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    stored_version = AGENT_ARTIFACT_INDEX_SCHEMA_VERSION - 1
    _write_index_schema_version(index, stored_version)

    def fail_rebuild(*args: object, **kwargs: object) -> object:
        raise AssertionError("the metadata-only check must not rebuild")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_schema.rebuild_agent_artifact_index",
        fail_rebuild,
    )

    status = read_agent_artifact_index_schema_status(index_path=index)

    assert status.checked
    assert status.stale
    assert status.stored_schema_version == stored_version


def test_current_schema_refresh_skips_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    _write_index_schema_version(index, AGENT_ARTIFACT_INDEX_SCHEMA_VERSION)

    def fail_rebuild(*args: object, **kwargs: object) -> object:
        raise AssertionError("current schema should not rebuild")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_schema.rebuild_agent_artifact_index",
        fail_rebuild,
    )

    report = refresh_agent_artifact_index_if_schema_stale(index_path=index)

    assert report.checked
    assert not report.refreshed
    assert report.stored_schema_version == AGENT_ARTIFACT_INDEX_SCHEMA_VERSION


def test_authoritative_dismissed_sync_bypasses_matching_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    meta_store = install_projection_meta_store(monkeypatch)
    write_projection_meta(
        meta_store,
        index,
        dismissed_agents_signature=[10, 20],
        dismissed_bundle_index_signature=[1, 30, 40, 2],
    )
    calls: list[tuple[Path, list[object]]] = []

    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 2),
    )

    def fake_replace(index_path: Path, identities: list[object]) -> object:
        calls.append((index_path, identities))
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=len(identities),
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fake_replace,
    )

    assert sync_dismissed_agent_artifact_index(
        {(AgentType.RUNNING, "kept", "20260501010101")},
        added={(AgentType.RUNNING, "removed", "20260502020202")},
        index_path=index,
    )

    assert len(calls) == 1
    assert [(row.agent_type, row.cl_name, row.raw_suffix) for row in calls[0][1]] == [
        ("run", "kept", "20260501010101")
    ]
    metadata = read_projection_meta(meta_store, index)
    assert metadata["projected_identity_count"] == 1


def test_sync_dismissed_projection_writes_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    meta_store = install_projection_meta_store(monkeypatch)
    calls: list[tuple[Path, list[object]]] = []

    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 1),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
        lambda: {("workflow", "bundle", "20260502020202")},
    )

    def fake_replace(index_path: Path, identities: list[object]) -> object:
        calls.append((index_path, identities))
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=len(identities),
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fake_replace,
    )

    assert sync_dismissed_agent_artifact_index(
        {(AgentType.RUNNING, "json", "20260501010101")},
        index_path=index,
        force=True,
    )

    assert [(row.agent_type, row.cl_name, row.raw_suffix) for row in calls[0][1]] == [
        ("run", "json", "20260501010101"),
        ("workflow", "bundle", "20260502020202"),
    ]
    metadata = read_projection_meta(meta_store, index)
    assert metadata["dismissed_agents_signature"] == [10, 20]
    assert metadata["dismissed_bundle_index_signature"] == [1, 30, 40, 1]
    assert metadata["projected_identity_count"] == 2
