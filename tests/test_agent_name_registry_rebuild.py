"""Rebuild and discovery tests for the durable agent-name registry."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from unittest.mock import patch

from sase.agent.names import (
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    lowest_name_suggestion,
    rebuild_name_registry,
)
from sase.agent.names import _registry, _registry_store
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)

from tests._agent_names_fixtures import (
    make_agent as _make_agent,
    make_sharded_agent as _make_sharded_agent,
)


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


def test_registry_rebuild_collects_clan_container(tmp_path: Path) -> None:
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "foo.member")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "foo.member",
                "agent_clan": "foo",
                "agent_clan_generation": "run0",
            }
        ),
        encoding="utf-8",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    assert {"foo", "foo.member"} <= set(data["entries"])
    assert data["entries"]["foo"]["container_kind"] == "clan"
    assert data["entries"]["foo"]["clan_generation"] == "run0"


def test_registry_rebuild_collects_family_container(tmp_path: Path) -> None:
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "foo--0")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "foo--0",
                "workflow_name": "foo",
                "agent_family": "foo",
                "agent_family_role": "root",
                "role_suffix": "--0",
            }
        ),
        encoding="utf-8",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    assert {"foo", "foo--0"} <= set(data["entries"])
    assert data["entries"]["foo"]["container_kind"] == "family"
    assert data["entries"]["foo"]["reservation_kind"] == "family"
    assert data["entries"]["foo--0"]["reservation_kind"] == "claimed"


def test_registry_rebuild_collects_sharded_agent_and_tracks_day_dir(
    tmp_path: Path,
) -> None:
    first = _make_sharded_agent(tmp_path, "proj", "20260613120000", "sharded")
    with patch.object(Path, "home", return_value=tmp_path):
        paths = _registry_store._registry_source_signature_paths()
        assert first.parent in paths
        assert first not in paths

        data = rebuild_name_registry()
        assert data["entries"]["sharded"]["project_name"] == "proj"
        assert data["entries"]["sharded"]["workflow_dir"] == "ace-run"
        assert data["entries"]["sharded"]["raw_suffix"] == "20260613120000"

        before = _registry_store._source_signature()
        time.sleep(0.01)
        _make_sharded_agent(tmp_path, "proj", "20260613120100", "sharded-later")
        after = _registry_store._source_signature()
        assert after != before


def test_registry_rebuild_collects_numeric_auto_prefix(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "1.plan")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        reserved = get_reserved_agent_names()
        assert {"1", "1.plan"} <= reserved
        assert lookup_registered_name("1")["reservation_kind"] == "auto_prefix"


def test_registry_rebuild_resolves_one_identity_snapshot_for_all_sources(
    tmp_path: Path,
) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    _make_agent(tmp_path, "proj", "run1", "athena.1.plan")
    _make_agent(tmp_path, "proj", "run2", "2.plan")
    _write_bundle(
        tmp_path,
        "20260508120000.json",
        {
            "agent_name": "zeus.worker",
            "raw_suffix": "20260508120000",
        },
    )

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch.object(
            AgentIdentitySnapshot,
            "current",
            return_value=identity,
        ) as current_identity,
    ):
        data = rebuild_name_registry()

    assert current_identity.call_count == 1
    assert {
        "athena.1",
        "athena.1.plan",
        "2",
        "2.plan",
        "zeus.worker",
        "zeus",
    } <= set(data["entries"])
    assert "1" not in data["entries"]
    assert "athena.2" not in data["entries"]
    assert "athena.zeus.worker" not in data["entries"]
    assert data["entries"]["athena.1"]["reservation_kind"] == "auto_prefix"
    assert data["entries"]["2"]["reservation_kind"] == "auto_prefix"
    assert data["entries"]["zeus.worker"]["source"] == "dismissed_bundle"


def test_registry_rebuild_stays_under_sase_home(monkeypatch, tmp_path: Path) -> None:
    real_home = tmp_path / "real-home"
    isolated_home = tmp_path / "isolated-home"
    real_sase_home = real_home / ".sase"
    isolated_sase_home = isolated_home / ".sase"
    _make_agent(real_home, "proj", "run-real", "real-name")
    _make_agent(isolated_home, "proj", "run-isolated", "isolated-name")

    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("SASE_HOME", str(isolated_sase_home))
    _registry._CACHE_PATH = None
    _registry._CACHE_SIGNATURE = None
    _registry._CACHE_DATA = None

    assert _registry._registry_path() == isolated_sase_home / (
        "agent_name_registry.json"
    )
    for path in _registry_store._registry_source_signature_paths():
        assert path == isolated_sase_home or isolated_sase_home in path.parents
        assert path != real_sase_home and real_sase_home not in path.parents

    data = rebuild_name_registry()
    loaded = load_name_registry()

    assert "isolated-name" in data["entries"]
    assert "real-name" not in data["entries"]
    assert "isolated-name" in loaded["entries"]


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
