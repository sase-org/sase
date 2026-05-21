from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_artifact_index_lifecycle import (
    _DISMISSED_PROJECTION_META_KEY,
    _projects_root_for_artifact_dir,
    build_dismissed_agent_projection_inputs,
    delete_agent_artifact_index_artifacts,
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
    upsert_agent_artifact_index_artifacts,
)
from sase.core.agent_scan_wire import AgentArtifactIndexUpdateWire


def test_projects_root_for_artifact_dir_derives_projects_root(tmp_path: Path) -> None:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "ts"
    )

    assert (
        _projects_root_for_artifact_dir(artifact_dir) == tmp_path / ".sase" / "projects"
    )


def test_sync_dismissed_agent_artifact_index_serializes_identities(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
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
        "sase.ace.dismissed_agents.load_dismissed_bundle_summaries",
        lambda *, limit=None: [],
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
        "sase.ace.dismissed_agents.load_dismissed_bundle_summaries",
        lambda *, limit=None: [],
    )

    projection = build_dismissed_agent_projection_inputs()

    assert [
        (row.agent_type, row.cl_name, row.raw_suffix) for row in projection.identities
    ] == [("run", "json", "20260501010101")]
    assert projection.dismissed_agents_signature == (10, 20)
    assert projection.dismissed_bundle_index_signature == (1, 30, 40, 0)


def test_build_dismissed_projection_inputs_reads_bundle_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    summary = SimpleNamespace(
        agent_type="workflow",
        cl_name="bundle",
        raw_suffix="20260502020202",
    )
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
        "sase.ace.dismissed_agents.load_dismissed_bundle_summaries",
        lambda *, limit=None: [summary],
    )

    projection = build_dismissed_agent_projection_inputs()

    assert [
        (row.agent_type, row.cl_name, row.raw_suffix) for row in projection.identities
    ] == [("workflow", "bundle", "20260502020202")]


def test_build_dismissed_projection_inputs_combines_sources(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    summaries = [
        SimpleNamespace(agent_type="run", cl_name="", raw_suffix="20260503030303"),
        SimpleNamespace(agent_type="run", cl_name="json", raw_suffix="20260501010101"),
    ]
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
        "sase.ace.dismissed_agents.load_dismissed_bundle_summaries",
        lambda *, limit=None: summaries,
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
    _write_projection_meta(
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


def test_sync_dismissed_projection_writes_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    summary = SimpleNamespace(
        agent_type="workflow",
        cl_name="bundle",
        raw_suffix="20260502020202",
    )
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
        "sase.ace.dismissed_agents.load_dismissed_bundle_summaries",
        lambda *, limit=None: [summary],
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
    metadata = _read_projection_meta(index)
    assert metadata["dismissed_agents_signature"] == [10, 20]
    assert metadata["dismissed_bundle_index_signature"] == [1, 30, 40, 1]
    assert metadata["projected_identity_count"] == 2


def test_delete_agent_artifact_index_artifacts_is_best_effort(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    deleted_paths: list[str] = []

    def fake_delete(index_path: Path, artifact_dir: Path) -> object:
        del index_path
        deleted_paths.append(str(artifact_dir))
        raise RuntimeError("stale index")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.delete_agent_artifact_index_row",
        fake_delete,
    )

    assert (
        delete_agent_artifact_index_artifacts(["/tmp/missing"], index_path=index) == 0
    )
    assert deleted_paths == ["/tmp/missing"]


def test_upsert_agent_artifact_index_artifacts_derives_root(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    artifact_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260501010101"
    )
    artifact_dir.mkdir(parents=True)
    calls: list[tuple[Path, Path, Path]] = []

    def fake_upsert(
        index_path: Path,
        projects_root: Path,
        upsert_dir: Path,
        options: object,
    ) -> object:
        del options
        calls.append((index_path, projects_root, upsert_dir))
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root=str(projects_root),
            rows_indexed=1,
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.upsert_agent_artifact_index_row",
        fake_upsert,
    )

    assert upsert_agent_artifact_index_artifacts([artifact_dir, artifact_dir]) == 1
    assert calls == [
        (
            Path.home() / ".sase" / "agent_artifact_index.sqlite",
            tmp_path / ".sase" / "projects",
            artifact_dir,
        )
    ]


def test_marker_mutation_helper_wraps_single_artifact_upsert(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[list[Path | str | None], Path | str | None]] = []

    def fake_upsert(
        artifact_dirs: list[Path | str | None],
        *,
        index_path: Path | str | None = None,
    ) -> int:
        calls.append((artifact_dirs, index_path))
        return 1

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "upsert_agent_artifact_index_artifacts",
        fake_upsert,
    )

    assert update_agent_artifact_index_for_marker_mutation(
        tmp_path,
        index_path=tmp_path / "index.sqlite",
    )
    assert calls == [([tmp_path], tmp_path / "index.sqlite")]


def _write_projection_meta(
    index: Path,
    *,
    dismissed_agents_signature: list[int] | None,
    dismissed_bundle_index_signature: list[int] | None,
) -> None:
    payload = {
        "version": 1,
        "dismissed_agents_signature": dismissed_agents_signature,
        "dismissed_bundle_index_signature": dismissed_bundle_index_signature,
        "projected_identity_count": 2,
    }
    with sqlite3.connect(index) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            (_DISMISSED_PROJECTION_META_KEY, json.dumps(payload)),
        )


def _read_projection_meta(index: Path) -> dict[str, object]:
    with sqlite3.connect(index) as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (_DISMISSED_PROJECTION_META_KEY,),
        ).fetchone()
    assert row is not None
    value = json.loads(row[0])
    assert isinstance(value, dict)
    return value
