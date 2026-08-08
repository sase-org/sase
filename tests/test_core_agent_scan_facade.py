from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_facade import (
    agent_artifact_index_status,
    delete_agent_artifact_index_row_bounded,
    query_related_agent_artifact_dirs,
    read_agent_artifact_index_meta,
    scan_agent_artifact_dirs,
    scan_agent_artifacts,
    verify_agent_artifact_index,
    write_agent_artifact_index_meta,
)
from sase.core.agent_scan_wire import AGENT_SCAN_WIRE_SCHEMA_VERSION
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agents_from_snapshot,
)

from ._rust_extension_module_helpers import (
    evict_rust_extension,
    install_fake_rust_extension,
)
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    install_fake_scan_module,
    minimal_record,
    minimal_snapshot,
)


def test_verify_agent_artifact_index_reports_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    record = minimal_record(projects_root, "20260504121212", "active")

    def fake_scan(projects_root_arg: str, options: dict[str, Any]) -> dict[str, Any]:
        return minimal_snapshot(projects_root_arg, [record])

    fake = install_fake_scan_module(monkeypatch, fake_scan)
    fake.query_agent_artifact_index = (  # type: ignore[attr-defined]
        lambda index_arg, root_arg, query, options: minimal_snapshot(root_arg, [record])
    )

    result = verify_agent_artifact_index(index_path, projects_root)

    assert result.ok is True
    assert result.indexed_rows == 1
    assert result.source_rows == 1
    assert result.missing_rows == 0
    assert result.stale_rows == 0


def test_verify_agent_artifact_index_reports_stale_and_missing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    source_record = minimal_record(projects_root, "20260504121212", "new-name")
    indexed_record = minimal_record(projects_root, "20260504121212", "old-name")
    missing_record = minimal_record(projects_root, "20260504131313", "missing")

    def fake_scan(projects_root_arg: str, options: dict[str, Any]) -> dict[str, Any]:
        return minimal_snapshot(projects_root_arg, [source_record, missing_record])

    fake = install_fake_scan_module(monkeypatch, fake_scan)
    fake.query_agent_artifact_index = (  # type: ignore[attr-defined]
        lambda index_arg, root_arg, query, options: minimal_snapshot(
            root_arg, [indexed_record]
        )
    )

    result = verify_agent_artifact_index(index_path, projects_root)

    assert result.ok is False
    assert result.indexed_rows == 1
    assert result.source_rows == 2
    assert result.stale_rows == 1
    assert result.missing_rows == 1


def test_verify_agent_artifact_index_reports_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    record = minimal_record(projects_root, "20260504121212", "active")

    def fake_scan(projects_root_arg: str, options: dict[str, Any]) -> dict[str, Any]:
        return minimal_snapshot(projects_root_arg, [record])

    install_fake_scan_module(monkeypatch, fake_scan)

    result = verify_agent_artifact_index(
        tmp_path / "missing.sqlite",
        projects_root,
    )

    assert result.ok is False
    assert result.schema_version == 0
    assert result.indexed_rows == 0
    assert result.missing_rows == 1


def test_scan_agent_artifacts_calls_rust_binding(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The facade calls ``sase_core_rs.scan_agent_artifacts`` directly.

    Phase 8D removed the Python walker fallback; the facade now always
    delegates to the Rust binding through
    ``sase.core.rust.require_rust_binding``. The fake binding records the
    arguments it receives and returns a synthetic empty snapshot so we can assert
    on the dict shape the facade hands the Rust side.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_scan(projects_root: str, options: dict[str, Any]) -> dict[str, Any]:
        calls.append((projects_root, options))
        return {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": projects_root,
            "options": options,
            "stats": {
                "projects_visited": 0,
                "artifact_dirs_visited": 0,
                "marker_files_parsed": 0,
                "json_decode_errors": 0,
                "os_errors": 0,
                "prompt_step_markers_parsed": 0,
            },
            "records": [],
        }

    install_fake_scan_module(monkeypatch, fake_scan)

    snapshot = scan_agent_artifacts(fixture_root)
    assert snapshot.records == []
    assert len(calls) == 1
    assert calls[0][0] == str(fixture_root)
    # The facade always populates the options dict so the Rust side never
    # has to guess defaults; keys match the wire schema.
    options_dict = calls[0][1]
    assert options_dict["include_prompt_step_markers"] is True
    assert options_dict["include_raw_prompt_snippets"] is True
    assert options_dict["only_workflow_dirs"] == []
    assert options_dict["max_records"] is None
    assert options_dict["newest_first"] is False
    assert options_dict["not_before_timestamp"] is None
    assert options_dict["include_done_markers"] is True
    assert options_dict["include_workflow_state"] is True
    assert options_dict["include_waiting"] is True
    assert options_dict["only_projects"] == []
    assert options_dict["include_project_states"] == []


def test_scan_agent_artifact_dirs_calls_rust_binding(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, list[str], dict[str, Any]]] = []
    artifact_dir = fixture_root / "myproj" / "artifacts" / "ace-run" / "20260504121212"

    def fake_scan_dirs(
        projects_root: str,
        artifact_dirs: list[str],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        calls.append((projects_root, artifact_dirs, options))
        return minimal_snapshot(projects_root, [])

    fake = install_fake_scan_module(
        monkeypatch, lambda root, opts: minimal_snapshot(root, [])
    )
    fake.scan_agent_artifact_dirs = fake_scan_dirs  # type: ignore[attr-defined]

    snapshot = scan_agent_artifact_dirs(fixture_root, [artifact_dir])

    assert snapshot.records == []
    assert len(calls) == 1
    projects_root, artifact_dirs, options_dict = calls[0]
    assert projects_root == str(fixture_root)
    assert artifact_dirs == [str(artifact_dir)]
    assert options_dict["include_prompt_step_markers"] is True
    assert options_dict["include_raw_prompt_snippets"] is True


def test_agent_artifact_index_metadata_helpers_call_rust_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str | None]] = []

    fake = install_fake_scan_module(
        monkeypatch, lambda root, opts: minimal_snapshot(root, [])
    )
    fake.read_agent_artifact_index_meta = (  # type: ignore[attr-defined]
        lambda index, key: calls.append((index, key, None)) or "stored"
    )

    def fake_write(index: str, key: str, value: str) -> None:
        calls.append((index, key, value))

    fake.write_agent_artifact_index_meta = fake_write  # type: ignore[attr-defined]

    index_path = tmp_path / "agent_artifact_index.sqlite"
    assert (
        read_agent_artifact_index_meta(index_path, "dismissed_projection") == "stored"
    )
    write_agent_artifact_index_meta(index_path, "dismissed_projection", "{}")

    assert calls == [
        (str(index_path), "dismissed_projection", None),
        (str(index_path), "dismissed_projection", "{}"),
    ]


def test_bounded_artifact_index_delete_passes_timeout_to_rust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, int]] = []
    fake = install_fake_scan_module(
        monkeypatch, lambda root, opts: minimal_snapshot(root, [])
    )

    def fake_delete(index: str, artifact_dir: str, timeout_ms: int) -> dict[str, Any]:
        calls.append((index, artifact_dir, timeout_ms))
        return {
            "schema_version": 1,
            "index_path": index,
            "projects_root": "",
            "rows_indexed": 0,
            "rows_deleted": 1,
            "rows_skipped": 0,
        }

    fake.delete_agent_artifact_index_row_bounded = fake_delete  # type: ignore[attr-defined]
    index = tmp_path / "index.sqlite"
    artifact_dir = tmp_path / "artifacts"

    result = delete_agent_artifact_index_row_bounded(
        index,
        artifact_dir,
        lock_timeout_seconds=0.2,
        busy_timeout_seconds=0.125,
    )

    assert result is not None
    assert result.rows_deleted == 1
    assert calls == [(str(index), str(artifact_dir), 125)]


def test_agent_artifact_index_status_calls_rust_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake = install_fake_scan_module(
        monkeypatch, lambda root, opts: minimal_snapshot(root, [])
    )

    def fake_status(index: str) -> dict[str, Any]:
        calls.append(index)
        return {
            "schema_version": 3,
            "index_path": index,
            "agent_artifacts_rows": 7,
            "dismissed_agents_rows": 2,
        }

    fake.agent_artifact_index_status = fake_status  # type: ignore[attr-defined]

    index_path = tmp_path / "agent_artifact_index.sqlite"
    status = agent_artifact_index_status(index_path)

    assert calls == [str(index_path)]
    assert status.schema_version == 3
    assert status.agent_artifacts_rows == 7
    assert status.dismissed_agents_rows == 2


def test_related_agent_artifact_dirs_calls_rust_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, list[str]]] = []
    fake = install_fake_scan_module(
        monkeypatch, lambda root, opts: minimal_snapshot(root, [])
    )

    def fake_query(index: str, artifact_dir: str, seeds: list[str]) -> list[str]:
        calls.append((index, artifact_dir, seeds))
        return [artifact_dir, str(tmp_path / "artifacts" / "20260504120500")]

    fake.query_related_agent_artifact_dirs = fake_query  # type: ignore[attr-defined]

    index_path = tmp_path / "agent_artifact_index.sqlite"
    artifact_dir = tmp_path / "artifacts" / "20260504120000"
    related = query_related_agent_artifact_dirs(
        index_path,
        artifact_dir,
        ["20260504120000", ""],
    )

    assert calls == [
        (str(index_path), str(artifact_dir), ["20260504120000"]),
    ]
    assert related == [artifact_dir, tmp_path / "artifacts" / "20260504120500"]


def test_snapshot_workflow_hidden_maps_to_agent_hidden(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    record = minimal_record(projects_root, "20260514120000", "workflow-parent")
    record["workflow_dir_name"] = "workflow-launcher"
    record["workflow_state"] = {
        "workflow_name": "launcher",
        "status": "running",
        "hidden": True,
        "current_step_index": 0,
        "steps": [],
    }

    snapshot = minimal_snapshot(str(projects_root), [record])
    from sase.core.agent_scan_wire import agent_scan_wire_from_dict

    agents = load_workflow_agents_from_snapshot(agent_scan_wire_from_dict(snapshot))

    assert len(agents) == 1
    assert agents[0].hidden is True


def test_agent_scan_wire_dual_reads_patch_metadata(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    record = minimal_record(projects_root, "20260514120000", "worker")
    record["agent_meta"] = {
        "patch_name": "feature",
        "commit_patch_name": "feature",
        "stitch_id": "2a",
    }
    record["done"] = {"cl_name": "legacy-done"}
    record["running"] = {"cl_name": "legacy-running"}
    record["waiting"] = {"cl_name": "legacy-waiting"}

    from sase.core.agent_scan_wire import agent_scan_wire_from_dict

    parsed = agent_scan_wire_from_dict(minimal_snapshot(str(projects_root), [record]))
    parsed_record = parsed.records[0]

    assert parsed_record.agent_meta is not None
    assert parsed_record.agent_meta.patch_name == "feature"
    assert parsed_record.agent_meta.changespec_name == "feature"
    assert parsed_record.agent_meta.stitch_id == "2a"
    assert parsed_record.agent_meta.commit_entry_id == "2a"
    assert parsed_record.done is not None
    assert parsed_record.done.patch_name == "legacy-done"
    assert parsed_record.running is not None
    assert parsed_record.running.patch_name == "legacy-running"
    assert parsed_record.waiting is not None
    assert parsed_record.waiting.patch_name == "legacy-waiting"


def test_scan_agent_artifacts_missing_extension_raises_importerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the wheel is gone, the facade raises :class:`ImportError`."""
    evict_rust_extension(monkeypatch)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        scan_agent_artifacts(fixture_root)


def test_scan_agent_artifacts_stale_wheel_raises_attributeerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel without the binding raises :class:`AttributeError` naming the op."""
    install_fake_rust_extension(monkeypatch)
    with pytest.raises(AttributeError, match="scan_agent_artifacts"):
        scan_agent_artifacts(fixture_root)


def test_scan_agent_artifact_dirs_stale_wheel_raises_attributeerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_rust_extension(monkeypatch)
    with pytest.raises(AttributeError, match="scan_agent_artifact_dirs"):
        scan_agent_artifact_dirs(fixture_root, [])
