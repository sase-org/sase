"""Rebuild and discovery tests for the durable agent-name registry."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.names import (
    claim_registered_name,
    get_reserved_agent_names,
    get_reserved_family_names_for_display,
    load_name_registry,
    lookup_registered_name,
    lowest_name_suggestion,
    rebuild_name_registry,
    reset_name_registry_caches_for_tests,
)
from sase.agent.names import _registry, _registry_scan, _registry_store
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


def test_registry_rebuild_family_container_outranks_auto_prefix(
    tmp_path: Path,
) -> None:
    _make_agent(tmp_path, "proj", "run1", "sq.w0")
    _make_agent(
        tmp_path,
        "proj",
        "run2",
        "sq--plan",
        workflow_name="sq",
        agent_family="sq",
        role_suffix="--plan",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entry = data["entries"]["sq"]
    assert entry["container_kind"] == "family"
    assert entry["reservation_kind"] == "family"


def test_registry_rebuild_clan_container_outranks_auto_prefix(
    tmp_path: Path,
) -> None:
    _make_agent(tmp_path, "proj", "run1", "sq.w0")
    clan_dir = _make_agent(tmp_path, "proj", "run2", "sq.member")
    (clan_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "sq.member",
                "model": "test",
                "agent_clan": "sq",
                "agent_clan_generation": "run0",
            }
        ),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()

    entry = data["entries"]["sq"]
    assert entry["container_kind"] == "clan"
    assert entry["reservation_kind"] == "clan"
    assert entry["clan_generation"] == "run0"


def test_registry_rebuild_collects_sharded_agent_and_tracks_day_dir(
    tmp_path: Path,
) -> None:
    first = _make_sharded_agent(tmp_path, "proj", "20260613120000", "sharded")
    with patch.object(Path, "home", return_value=tmp_path):
        paths = _registry_store._registry_source_signature_paths()
        assert first in paths

        data = rebuild_name_registry()
        assert data["entries"]["sharded"]["project_name"] == "proj"
        assert data["entries"]["sharded"]["workflow_dir"] == "ace-run"
        assert data["entries"]["sharded"]["raw_suffix"] == "20260613120000"

        before = _registry_store._source_signature()
        time.sleep(0.01)  # sase-test-wait: separates source mtimes
        _make_sharded_agent(tmp_path, "proj", "20260613120100", "sharded-later")
        after = _registry_store._source_signature()
        assert after != before


def test_registry_signature_ignores_live_artifact_output(tmp_path: Path) -> None:
    artifact = _make_sharded_agent(
        tmp_path,
        "proj",
        "20260613120000",
        "sharded",
    )
    with patch.object(Path, "home", return_value=tmp_path):
        before = _registry_store._source_signature()
        (artifact / "reply.md").write_text("still running\n", encoding="utf-8")
        (artifact / "tool-output.json").write_text("{}\n", encoding="utf-8")
        after = _registry_store._source_signature()

    assert after == before


def test_registry_signature_detects_dismissed_bundle_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _registry_scan._directory_entries_for_signature.cache_clear()
    bundle = _write_bundle(
        tmp_path,
        "20260508120000.json",
        {"agent_name": "foo", "raw_suffix": "20260508120000"},
    )
    before = _registry_store._source_signature()

    bundle.write_text(
        json.dumps(
            {
                "agent_name": "rewritten-name",
                "raw_suffix": "20260508120000",
            }
        ),
        encoding="utf-8",
    )
    rewritten = _registry_store._source_signature()

    time.sleep(0.01)  # sase-test-wait: separates bundle mtimes
    added_bundle = _write_bundle(
        tmp_path,
        "20260508120100.json",
        {"agent_name": "bar", "raw_suffix": "20260508120100"},
    )
    added = _registry_store._source_signature()

    time.sleep(0.01)  # sase-test-wait: separates unlink mtime
    added_bundle.unlink()
    removed = _registry_store._source_signature()

    assert rewritten != before
    assert added != rewritten
    assert removed != added


def test_registry_source_scan_caches_unchanged_shards(tmp_path: Path) -> None:
    for index in range(100):
        _write_bundle(
            tmp_path,
            f"20260508{index:06d}.json",
            {"agent_name": f"name-{index}", "raw_suffix": f"20260508{index:06d}"},
        )
    cache = _registry_scan._directory_entries_for_signature
    cache.cache_clear()

    with patch.object(Path, "home", return_value=tmp_path):
        first = _registry_scan.source_signature_paths()
        first_info = cache.cache_info()
        second = _registry_scan.source_signature_paths()
        second_info = cache.cache_info()

        time.sleep(0.01)  # sase-test-wait: invalidates cached shard mtime
        added = _write_bundle(
            tmp_path,
            "20260508999999.json",
            {"agent_name": "later", "raw_suffix": "20260508999999"},
        )
        third = _registry_scan.source_signature_paths()
        third_info = cache.cache_info()

    assert second == first
    assert added in third
    assert second_info.misses == first_info.misses
    assert second_info.hits > first_info.hits
    assert third_info.misses == second_info.misses + 1


def test_registry_source_scan_caches_unchanged_artifact_walks(
    tmp_path: Path,
) -> None:
    for index in range(100):
        _make_sharded_agent(
            tmp_path,
            "proj",
            f"20260613{index:06d}",
            f"name-{index}",
        )
    _registry_scan._directory_entries_for_signature.cache_clear()
    _registry_scan._artifact_dirs_for_signature.cache_clear()

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch.object(
            _registry_scan,
            "iter_agent_artifact_dirs",
            wraps=_registry_scan.iter_agent_artifact_dirs,
        ) as artifact_scan,
    ):
        first = _registry_scan.source_signature_paths()
        second = _registry_scan.source_signature_paths()
        time.sleep(0.01)  # sase-test-wait: invalidates artifact scan mtime
        added = _make_sharded_agent(
            tmp_path,
            "proj",
            "20260613199999",
            "later",
        )
        third = _registry_scan.source_signature_paths()

    assert second == first
    assert added in third
    assert artifact_scan.call_count == 2


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
    reset_name_registry_caches_for_tests()

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


def test_registry_load_session_reuses_validated_cache(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch.object(
            _registry,
            "_registry_file_is_stale",
            wraps=_registry._registry_file_is_stale,
        ) as is_stale:
            with _registry.name_registry_load_session():
                for _ in range(20):
                    assert "foo" in load_name_registry()["entries"]

    assert is_stale.call_count == 0


def test_registry_load_session_memoizes_source_signature(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch.object(
            _registry_store,
            "source_signature_paths",
            wraps=_registry_store.source_signature_paths,
        ) as signature_paths,
    ):
        with _registry.name_registry_load_session():
            first = _registry_store._source_signature()
            second = _registry_store._source_signature()

    assert second == first
    assert signature_paths.call_count == 1


def test_stale_proof_memo_reused_across_repeated_loads(tmp_path: Path) -> None:
    """A burst of loads outside a load session pays the full proof once."""
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch.object(
            _registry,
            "_registry_file_is_stale",
            wraps=_registry._registry_file_is_stale,
        ) as is_stale:
            for _ in range(20):
                assert "foo" in load_name_registry()["entries"]

    assert is_stale.call_count == 1


def test_stale_proof_memo_invalidated_by_mutation(tmp_path: Path) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    (artifacts_root / "run1").mkdir(parents=True)
    with patch.object(Path, "home", return_value=tmp_path):
        load_name_registry()  # rebuild the absent registry
        load_name_registry()  # prove the rebuilt file fresh, arming the memo
        assert _registry._stale_proof_memo_valid()
        with patch.object(
            _registry,
            "_registry_file_is_stale",
            wraps=_registry._registry_file_is_stale,
        ) as is_stale:
            claim_registered_name("foo", artifacts_root / "run1")
            data = load_name_registry()

    assert "foo" in data["entries"]
    assert is_stale.call_count == 1


def test_reservation_reads_skip_the_stale_proof_memo(tmp_path: Path) -> None:
    """A name-reservation answer sees a directory the memo would still hide."""
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        workflow_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
        )
        rebuild_name_registry()
        load_name_registry()  # arm the memo
        assert _registry._stale_proof_memo_valid()
        workflow_stat = workflow_dir.stat()
        _make_agent(tmp_path, "proj", "run2", "bar")

        original_stat = Path.stat

        def stale_workflow_stat(self: Path, *args: Any, **kwargs: Any) -> object:
            if self == workflow_dir:
                return workflow_stat
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", stale_workflow_stat):
            # The display read is allowed to miss ``bar`` until the memo expires.
            assert "bar" not in load_name_registry()["entries"]
            # Allocation must not be, or it would hand ``bar`` out a second time.
            assert "bar" in get_reserved_agent_names()


def _make_family_agent(tmp_path: Path, suffix: str, family: str) -> Path:
    """Create an artifact whose rebuild registers *family* as a container."""
    artifact_dir = _make_agent(tmp_path, "proj", suffix, f"{family}--0")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": f"{family}--0",
                "workflow_name": family,
                "agent_family": family,
                "agent_family_role": "root",
                "role_suffix": "--0",
            }
        ),
        encoding="utf-8",
    )
    return artifact_dir


def test_display_family_read_never_rebuilds_a_stale_registry(tmp_path: Path) -> None:
    """A render answers from a stale registry instead of rebuilding it.

    ``rebuild_name_registry`` holds the process-wide name-allocation flock for
    the length of a full artifact scan, so a render that rebuilds stalls every
    concurrent ``sase run`` behind it. Link rendering only shapes a URL from
    the answer, so it must tolerate staleness; only reservation reads, which
    decide whether a name is free, may pay for a rebuild.
    """
    artifact_dir = _make_family_agent(tmp_path, "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        # Deleting the owner leaves the registry permanently stale until some
        # caller rebuilds it, which is what makes the two tiers diverge.
        shutil.rmtree(artifact_dir)
        reset_name_registry_caches_for_tests()
        assert _registry._registry_file_is_stale(
            _registry._read_registry(_registry._registry_path())
        )

        with patch.object(
            _registry,
            "rebuild_name_registry",
            wraps=_registry.rebuild_name_registry,
        ) as rebuild:
            assert "foo" in get_reserved_family_names_for_display()
            assert rebuild.call_count == 0

            # The reservation tier still pays for a correct answer.
            get_reserved_agent_names()
            assert rebuild.call_count == 1


def test_display_family_read_rebuilds_when_no_registry_exists(
    tmp_path: Path,
) -> None:
    """With nothing on disk there is no stale answer to prefer, so rebuild."""
    _make_family_agent(tmp_path, "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        reset_name_registry_caches_for_tests()
        assert not _registry._registry_path().exists()
        assert "foo" in get_reserved_family_names_for_display()


def test_stale_proof_memo_expires_after_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo")
    monkeypatch.setattr(_registry, "_STALE_PROOF_TTL_SECONDS", 0.01)
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        load_name_registry()  # arm the memo
        time.sleep(0.02)  # sase-test-wait: expires the TTL memo
        with patch.object(
            _registry,
            "_registry_file_is_stale",
            wraps=_registry._registry_file_is_stale,
        ) as is_stale:
            load_name_registry()

    assert is_stale.call_count == 1


def test_stale_proof_memo_still_detects_deleted_owner_after_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A memo that masks a deletion within its TTL must not mask it forever."""
    artifact_dir = _make_agent(tmp_path, "proj", "run1", "foo")
    monkeypatch.setattr(_registry, "_STALE_PROOF_TTL_SECONDS", 0.01)
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        load_name_registry()  # arm the memo
        shutil.rmtree(artifact_dir)
        time.sleep(0.02)  # sase-test-wait: expires the TTL memo
        data = load_name_registry()

    assert "foo" not in data["entries"]
