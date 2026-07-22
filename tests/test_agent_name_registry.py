"""Tests for the durable agent-name registry."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import shutil
from threading import Barrier
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    NameCollisionError,
    claim_registered_name,
    claim_registered_clan_name,
    convert_registered_agent_to_family,
    delete_registered_name,
    get_reserved_agent_names,
    get_reserved_clan_names,
    get_reserved_family_names,
    load_name_registry,
    lookup_registered_name,
    lowest_name_suggestion,
    rebuild_name_registry,
    reserve_registered_name,
    reserve_registered_clan_name,
    reserve_registered_template_name,
    reserve_registered_template_names,
)
from sase.agent.names import _registry

from tests._agent_names_fixtures import make_agent as _make_agent


def _write_bundle(base: Path, filename: str, data: dict[str, object]) -> Path:
    path = base / ".sase" / "dismissed_bundles" / "202605" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _configure_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.machine_hood_facade.get_machine_name",
        lambda: "athena",
    )
    monkeypatch.setattr(
        "sase.core.machine_hood_facade.discover_machine_names",
        lambda: ("athena", "zeus"),
    )


def _make_sharded_agent(
    base: Path,
    project: str,
    timestamp: str,
    name: str,
    *,
    done: bool = False,
) -> Path:
    artifact_dir = (
        base
        / ".sase"
        / "projects"
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"name": name, "model": "test"}),
        encoding="utf-8",
    )
    if done:
        (artifact_dir / "done.json").write_text(
            json.dumps({"outcome": "completed"}),
            encoding="utf-8",
        )
    return artifact_dir


def test_registry_rebuild_collects_active_agent(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()
        assert "foo" in data["entries"]
        assert lookup_registered_name("foo")["state"] == "active"


def test_configured_claim_uses_durable_machine_hood(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifact_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("foo", artifact_dir)
        assert get_reserved_agent_names() == {"athena.foo"}
        assert lookup_registered_name("foo") is not None
        assert lookup_registered_name("athena.foo") is not None


def test_legacy_and_qualified_claims_collide_in_both_directions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    first = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    second = tmp_path / ".sase/projects/proj/artifacts/ace-run/run2"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        _make_agent(tmp_path, "proj", "legacy", "foo")
        rebuild_name_registry()
        with pytest.raises(NameCollisionError):
            claim_registered_name("athena.foo", second)

        delete_registered_name("foo")
        claim_registered_name("athena.bar", first)
        with pytest.raises(NameCollisionError):
            claim_registered_name("bar", second)


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
        paths = _registry._source_signature_paths()
        assert first.parent in paths
        assert first not in paths

        data = rebuild_name_registry()
        assert data["entries"]["sharded"]["project_name"] == "proj"
        assert data["entries"]["sharded"]["workflow_dir"] == "ace-run"
        assert data["entries"]["sharded"]["raw_suffix"] == "20260613120000"

        before = _registry._source_signature()
        time.sleep(0.01)
        _make_sharded_agent(tmp_path, "proj", "20260613120100", "sharded-later")
        after = _registry._source_signature()
        assert after != before


def test_claim_registered_name_records_sharded_owner_identity(
    tmp_path: Path,
) -> None:
    artifact_dir = _make_sharded_agent(
        tmp_path,
        "proj",
        "20260613130000",
        "claimed",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("claimed", artifact_dir)
        entry = lookup_registered_name("claimed")

    assert entry is not None
    assert entry["project_name"] == "proj"
    assert entry["workflow_dir"] == "ace-run"
    assert entry["raw_suffix"] == "20260613130000"
    assert entry["created_at"] == "20260613130000"


def test_registry_rebuild_collects_numeric_auto_prefix(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "1.plan")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        reserved = get_reserved_agent_names()
        assert {"1", "1.plan"} <= reserved
        assert lookup_registered_name("1")["reservation_kind"] == "auto_prefix"


def test_configured_registry_rebuild_preserves_qualified_auto_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    _make_agent(tmp_path, "proj", "run1", "athena.1.plan")
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    assert {"athena.1", "athena.1.plan"} <= set(data["entries"])
    assert "1" not in data["entries"]
    assert data["entries"]["athena.1"]["reservation_kind"] == "auto_prefix"


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
    for path in _registry._source_signature_paths():
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


def test_registry_write_uses_unique_temp_file_for_nested_writer(tmp_path: Path) -> None:
    path = tmp_path / ".sase" / "agent_name_registry.json"
    first_replace = True
    real_replace = _registry.os.replace

    outer_data = {
        "schema_version": 1,
        "source_signature": {"count": 0, "max_mtime_ns": 0},
        "entries": {"outer": {"source": "test"}},
    }
    nested_data = {
        "schema_version": 1,
        "source_signature": {"count": 0, "max_mtime_ns": 0},
        "entries": {"nested": {"source": "test"}},
    }

    def replace_with_nested_write(src: Path, dst: Path) -> None:
        nonlocal first_replace
        if first_replace:
            first_replace = False
            _registry._write_registry(path, nested_data)
        real_replace(src, dst)

    with patch.object(_registry.os, "replace", side_effect=replace_with_nested_write):
        _registry._write_registry(path, outer_data)

    assert json.loads(path.read_text(encoding="utf-8")) == outer_data


def test_concurrent_claim_registered_name_preserves_all_claims(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    for i in range(12):
        (artifacts_root / f"run{i}").mkdir(parents=True)

    real_load = _registry.load_name_registry

    def slow_load() -> dict[str, object]:
        data = real_load()
        time.sleep(0.01)
        return data

    def claim(i: int) -> None:
        claim_registered_name(f"name{i}", artifacts_root / f"run{i}")

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch.object(_registry, "load_name_registry", side_effect=slow_load),
        ThreadPoolExecutor(max_workers=6) as pool,
    ):
        list(pool.map(claim, range(12)))

    path = tmp_path / ".sase" / "agent_name_registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["entries"]) == {f"name{i}" for i in range(12)}


def test_planned_reservation_survives_rebuild_until_child_claims(
    tmp_path: Path,
) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260501120000"
    )

    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_name("research.cdx-1", artifacts_dir)
        planned = lookup_registered_name("research.cdx-1")
        assert planned["reservation_kind"] == "planned"

        artifacts_dir.mkdir(parents=True)
        rebuilt = rebuild_name_registry()
        assert rebuilt["entries"]["research.cdx-1"]["reservation_kind"] == "planned"

        claim_registered_name("research.cdx-1", artifacts_dir, replace_existing=False)
        claimed = lookup_registered_name("research.cdx-1")
        assert claimed["reservation_kind"] == "claimed"
        assert claimed["artifacts_dir"] == str(artifacts_dir)


def test_clan_reservation_blocks_exact_agent_name_but_allows_hood_members(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    first_dir = artifacts_root / "run1"
    second_dir = artifacts_root / "run2"

    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_clan_name("research", "run0", first_dir)
        assert get_reserved_clan_names() == {"research"}
        with pytest.raises(NameCollisionError, match="reserved for clan"):
            claim_registered_name("research", second_dir, replace_existing=True)
        reserve_registered_template_name(
            "research.0.worker",
            "research.0",
            second_dir,
        )


def test_clan_reservation_rejects_existing_agent_and_claims_first_member(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    agent_dir = artifacts_root / "run1"
    clan_dir = artifacts_root / "run2"
    agent_dir.mkdir(parents=True)
    clan_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("taken", agent_dir)
        with pytest.raises(NameCollisionError, match="already reserved by an agent"):
            reserve_registered_clan_name("taken", "run0", clan_dir)

        assert reserve_registered_clan_name("free", "run0", clan_dir) == "run0"
        assert reserve_registered_clan_name("free", "run1", agent_dir) == "run0"
        claim_registered_clan_name("free", "run0", clan_dir)
        entry = lookup_registered_name("free")

    assert entry is not None
    assert entry["reservation_kind"] == "clan"
    assert entry["container_kind"] == "clan"


def test_concurrent_create_only_clan_reservations_allow_one_declaration(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    barrier = Barrier(2)

    def declare(index: int) -> str:
        barrier.wait()
        try:
            reserve_registered_clan_name(
                "research",
                f"run{index}",
                artifacts_root / f"run{index}",
                create_only=True,
            )
        except NameCollisionError:
            return "collision"
        return "created"

    with patch.object(Path, "home", return_value=tmp_path):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(declare, (1, 2)))

    assert sorted(results) == ["collision", "created"]


def test_family_conversion_reserves_base_and_original_member(tmp_path: Path) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    root_dir = artifacts_root / "run1"
    other_dir = artifacts_root / "run2"
    root_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("foo", root_dir)
        convert_registered_agent_to_family("foo", "foo--0", root_dir)

        assert get_reserved_family_names() == {"foo"}
        assert lookup_registered_name("foo")["container_kind"] == "family"
        assert lookup_registered_name("foo--0")["reservation_kind"] == "claimed"
        with pytest.raises(NameCollisionError, match="reserved for agent family"):
            claim_registered_name("foo", other_dir, replace_existing=True)


def test_template_reservation_rejects_existing_namespace_descendant(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    first_dir = artifacts_root / "20260501120000"
    second_dir = artifacts_root / "20260501120001"

    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_name("0.cdx", first_dir)
        with pytest.raises(NameCollisionError):
            reserve_registered_template_name("0.cld", "0", second_dir)


def test_template_reservation_batch_allows_shared_namespace(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    first_dir = artifacts_root / "20260501120000"
    second_dir = artifacts_root / "20260501120001"

    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_template_names(
            [
                ("research.0.cdx", "research.0", first_dir),
                ("research.0.cld", "research.0", second_dir),
            ]
        )

        assert lookup_registered_name("research.0.cdx")["template_namespace"] == (
            "research.0"
        )
        assert lookup_registered_name("research.0.cld")["template_namespace"] == (
            "research.0"
        )


def test_failed_claim_registered_name_does_not_mutate_cached_registry(
    tmp_path: Path,
) -> None:
    artifacts_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "run0"
    )
    artifacts_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch.object(_registry, "_write_registry", side_effect=OSError("boom")):
            with pytest.raises(OSError, match="boom"):
                claim_registered_name("dupe", artifacts_dir)

        assert "dupe" not in load_name_registry()["entries"]
        assert lookup_registered_name("dupe") is None


def test_concurrent_explicit_claims_without_metadata_reject_collision(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    claim_dirs = [artifacts_root / f"run{i}" for i in range(2)]
    for claim_dir in claim_dirs:
        claim_dir.mkdir(parents=True)

    barrier = Barrier(2)

    def claim(index: int) -> tuple[str, str]:
        barrier.wait()
        try:
            claim_registered_name("dupe", claim_dirs[index], replace_existing=False)
        except NameCollisionError as exc:
            return "error", str(exc)
        return "ok", str(claim_dirs[index])

    with (
        patch.object(Path, "home", return_value=tmp_path),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(claim, range(2)))

    statuses = [status for status, _ in results]
    assert statuses.count("ok") == 1
    assert statuses.count("error") == 1
    assert any("dupe1" in detail for status, detail in results if status == "error")
    assert all(not (claim_dir / "agent_meta.json").exists() for claim_dir in claim_dirs)
