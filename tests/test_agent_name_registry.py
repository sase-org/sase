"""Tests for the durable agent-name registry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    delete_registered_name,
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    lowest_name_suggestion,
    rebuild_name_registry,
)

from tests._agent_names_fixtures import make_agent as _make_agent


def _write_bundle(base: Path, filename: str, data: dict[str, object]) -> Path:
    path = base / ".sase" / "dismissed_bundles" / "202605" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_registry_rebuild_collects_active_agent(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()
        assert "foo" in data["entries"]
        assert lookup_registered_name("foo")["state"] == "active"


def test_registry_rebuild_collects_done_agent(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo", done=True)
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert lookup_registered_name("foo")["state"] == "done"


def test_registry_rebuild_collects_dismissed_artifact(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo", done=True)
    dismissed_file = tmp_path / ".sase" / "dismissed_agents.json"
    dismissed_file.parent.mkdir(parents=True, exist_ok=True)
    dismissed_file.write_text('[["run", "proj", "run1"]]', encoding="utf-8")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert lookup_registered_name("foo")["state"] == "dismissed"


def test_registry_rebuild_collects_bundle_only_agent(tmp_path: Path) -> None:
    _write_bundle(
        tmp_path,
        "20260508120000.json",
        {
            "agent_name": "foo",
            "workflow_name": "foo.workflow",
            "raw_suffix": "20260508120000",
        },
    )
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        reserved = get_reserved_agent_names()
        assert {"foo", "foo.workflow"} <= reserved
        assert lookup_registered_name("foo")["source"] == "dismissed_bundle"


def test_missing_index_rebuilds_on_lookup(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        assert lookup_registered_name("foo")["raw_suffix"] == "run1"
        assert (tmp_path / ".sase" / "agent_name_registry.json").is_file()


def test_stale_index_rebuilds_when_owner_disappears(tmp_path: Path) -> None:
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        shutil.rmtree(artifact_dir)
        _make_agent(tmp_path, "proj", "run2", "bar")
        data = load_name_registry()
        assert "foo" not in data["entries"]
        assert "bar" in data["entries"]


def test_delete_registered_name_releases_slot(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        delete_registered_name("foo")
        assert lookup_registered_name("foo") is None


def test_lowest_name_suggestion(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    _make_agent(tmp_path, "proj", "run2", "foo1")
    _make_agent(tmp_path, "proj", "run3", "foo3")
    with patch.object(Path, "home", return_value=tmp_path):
        assert lowest_name_suggestion("foo") == "foo2"


def test_cached_registry_avoids_repeated_tree_walks(tmp_path: Path) -> None:
    for i in range(500):
        _make_agent(tmp_path, "proj", f"run{i}", f"name{i}")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._registry.rebuild_name_registry",
            side_effect=AssertionError("unexpected rebuild"),
        ):
            assert "name499" in get_reserved_agent_names()
