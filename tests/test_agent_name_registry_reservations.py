"""Reservation and transaction tests for the durable agent-name registry."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
import time
from unittest.mock import patch

import pytest

from sase.agent.names import (
    NameCollisionError,
    claim_registered_clan_name,
    claim_registered_name,
    convert_registered_agent_to_family,
    get_reserved_agent_names,
    get_reserved_clan_names,
    get_reserved_family_names,
    load_name_registry,
    lookup_registered_name,
    rebuild_name_registry,
    reserve_registered_clan_name,
    reserve_registered_name,
    reserve_registered_template_name,
    reserve_registered_template_names,
)
from sase.agent.names import _registry
from sase.agent.names.registry_freshness import agent_name_registry_freshness_token
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

from tests._agent_names_fixtures import make_agent as _make_agent


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
        time.sleep(0.01)  # sase-test-wait: contention overlap window
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
        before_conversion = agent_name_registry_freshness_token()
        convert_registered_agent_to_family("foo", "foo--0", root_dir)

        assert get_reserved_family_names() == {"foo"}
        assert agent_name_registry_freshness_token() > before_conversion
        assert lookup_registered_name("foo")["container_kind"] == "family"
        assert lookup_registered_name("foo--0")["reservation_kind"] == "claimed"
        with pytest.raises(NameCollisionError, match="reserved for agent family"):
            claim_registered_name("foo", other_dir, replace_existing=True)


def test_auto_prefix_hood_neighbor_does_not_block_family_conversion(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    root_dir = artifacts_root / "20260803082344"
    hood_dir = artifacts_root / "20260803082549"
    root_dir.mkdir(parents=True)
    hood_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("sq", root_dir)
        claim_registered_name("sq.w0", hood_dir)
        (root_dir / "agent_meta.json").write_text(
            json.dumps({"name": "sq", "model": "test"}),
            encoding="utf-8",
        )
        (hood_dir / "agent_meta.json").write_text(
            json.dumps({"name": "sq.w0", "model": "test"}),
            encoding="utf-8",
        )
        rebuild_name_registry()
        convert_registered_agent_to_family("sq", "sq--plan", root_dir)

        assert lookup_registered_name("sq")["container_kind"] == "family"
        assert lookup_registered_name("sq--plan")["reservation_kind"] == "claimed"
        assert {"sq", "sq.w0"} <= get_reserved_agent_names()


def test_family_conversion_still_rejects_other_exact_claim_owner(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    root_dir = artifacts_root / "20260803082344"
    other_dir = artifacts_root / "20260803082549"
    root_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    for artifact_dir in (root_dir, other_dir):
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "sq", "model": "test"}),
            encoding="utf-8",
        )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with pytest.raises(NameCollisionError, match="agent name 'sq'"):
            convert_registered_agent_to_family("sq", "sq--plan", root_dir)


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


def test_rebuild_from_imported_only_source_frees_the_local_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebuild seeded only by an imported artifact must not squat local names.

    Before localization, a bare imported ``workflow_name`` such as
    ``research.b.cld.f0`` derived a bare ``research`` auto-prefix entry that
    permanently blocked every local ``research.*`` allocation. After the
    fix, the base is free locally, while the sibling machine's own root
    (``athena``) remains correctly reserved.
    """
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "zeus"),
        ("zeus", "athena"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )
    _make_agent(
        tmp_path,
        "proj",
        "run1",
        "athena.research.b.cld.f0",
        workflow_name="research.b.cld.f0",
        extra_meta={
            "imported_source_owner": {"username": "alice", "machine_name": "athena"},
            "canonical_global_name": "alice.athena.research.b.cld.f0",
            "imported_snapshot_digest": "a" * 64,
        },
    )
    local_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "run2"
    )
    local_dir.mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()

        claim_registered_name("research.0", local_dir)
        assert lookup_registered_name("research.0") is not None

        with pytest.raises(NameCollisionError, match="owner namespace 'athena'"):
            claim_registered_name("athena.anything", local_dir)
