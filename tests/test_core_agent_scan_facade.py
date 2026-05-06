from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_facade import (
    scan_agent_artifacts,
    verify_agent_artifact_index,
)
from sase.core.agent_scan_wire import AGENT_SCAN_WIRE_SCHEMA_VERSION
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

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


def test_scan_agent_artifacts_missing_extension_raises_importerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the wheel is gone, the facade raises :class:`ImportError`."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        scan_agent_artifacts(fixture_root)


def test_scan_agent_artifacts_stale_wheel_raises_attributeerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel without the binding raises :class:`AttributeError` naming the op."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    with pytest.raises(AttributeError, match="scan_agent_artifacts"):
        scan_agent_artifacts(fixture_root)
