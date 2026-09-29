"""Staleness, caching, and session-display reads for the name registry rebuild.

Split from ``tests.test_agent_name_registry_rebuild``; the original module
re-exports these tests so its import path keeps working.
"""

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
    get_reserved_agent_session_names,
    get_reserved_agent_session_names_for_display,
    load_name_registry,
    lookup_registered_name,
    lowest_name_suggestion,
    rebuild_name_registry,
    reset_name_registry_caches_for_tests,
)
from sase.agent.names import (
    _registry,
    _registry_queries,
    _registry_store,
)

from tests._agent_names_fixtures import make_agent as _make_agent

__all__ = [
    "test_cached_registry_avoids_repeated_tree_walks",
    "test_display_agent_session_read_never_rebuilds_a_stale_registry",
    "test_display_agent_session_read_rebuilds_when_no_registry_exists",
    "test_legacy_v2_registry_with_agent_family_kinds_upgrades_to_session_v3",
    "test_lowest_name_suggestion",
    "test_missing_index_rebuilds_on_lookup",
    "test_registry_load_session_memoizes_source_signature",
    "test_registry_load_session_reuses_validated_cache",
    "test_registry_missing_scan_version_is_stale_and_rebuilds_once",
    "test_reservation_reads_skip_the_stale_proof_memo",
    "test_stale_index_rebuilds_when_owner_disappears",
    "test_stale_proof_memo_expires_after_ttl",
    "test_stale_proof_memo_invalidated_by_mutation",
    "test_stale_proof_memo_reused_across_repeated_loads",
    "test_stale_proof_memo_still_detects_deleted_owner_after_ttl",
    "test_v3_rebuild_emits_no_legacy_kinds",
]


def _make_session_agent(tmp_path: Path, suffix: str, agent_session: str) -> Path:
    """Create an artifact whose rebuild registers *agent_session* as a container."""
    artifact_dir = _make_agent(tmp_path, "proj", suffix, f"{agent_session}--0")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": f"{agent_session}--0",
                "workflow_name": agent_session,
                "agent_session": agent_session,
                "agent_session_role": "root",
                "role_suffix": "--0",
            }
        ),
        encoding="utf-8",
    )
    return artifact_dir


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


def test_registry_missing_scan_version_is_stale_and_rebuilds_once(
    tmp_path: Path,
) -> None:
    """A registry written before ``scan_version`` existed rebuilds on upgrade.

    The staleness check only fingerprints artifact paths/mtimes, so a code
    upgrade alone never triggers a rebuild without this. A registry that
    predates ``scan_version`` (or carries a stale value) must rebuild exactly
    once so any bare imported entries from the old scan logic are dropped.
    """
    _make_agent(tmp_path, "proj", "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        data = rebuild_name_registry()
        assert data["scan_version"] == _registry_store.SCAN_VERSION

        path = _registry_store.registry_path()
        stale = json.loads(path.read_text(encoding="utf-8"))
        del stale["scan_version"]
        path.write_text(json.dumps(stale), encoding="utf-8")
        reset_name_registry_caches_for_tests()

        assert _registry_store.registry_file_is_stale(stale)
        loaded = load_name_registry()
        assert loaded["scan_version"] == _registry_store.SCAN_VERSION
        assert "foo" in loaded["entries"]


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


def test_display_agent_session_read_never_rebuilds_a_stale_registry(
    tmp_path: Path,
) -> None:
    """A render answers from a stale registry instead of rebuilding it.

    ``rebuild_name_registry`` holds the process-wide name-allocation flock for
    the length of a full artifact scan, so a render that rebuilds stalls every
    concurrent ``sase run`` behind it. Link rendering only shapes a URL from
    the answer, so it must tolerate staleness; only reservation reads, which
    decide whether a name is free, may pay for a rebuild.
    """
    artifact_dir = _make_session_agent(tmp_path, "run1", "foo")
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
            assert "foo" in get_reserved_agent_session_names_for_display()
            assert rebuild.call_count == 0

            # The reservation tier still pays for a correct answer.
            get_reserved_agent_names()
            assert rebuild.call_count == 1


def test_display_agent_session_read_rebuilds_when_no_registry_exists(
    tmp_path: Path,
) -> None:
    """With nothing on disk there is no stale answer to prefer, so rebuild."""
    _make_session_agent(tmp_path, "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        reset_name_registry_caches_for_tests()
        assert not _registry._registry_path().exists()
        assert "foo" in get_reserved_agent_session_names_for_display()


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


def test_legacy_v2_registry_with_agent_family_kinds_upgrades_to_session_v3(
    tmp_path: Path,
) -> None:
    """A realistic v2 file loads, answers container queries, and rebuilds as v3."""
    artifact_dir = _make_session_agent(tmp_path, "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        reset_name_registry_caches_for_tests()
        path = _registry_store.registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "scan_version": _registry_store.SCAN_VERSION,
                    "source_signature": _registry_store._source_signature(),
                    "entries": {
                        "foo": {
                            "name": "foo",
                            "source": "artifact",
                            "artifacts_dir": str(artifact_dir),
                            # legacy agent-family spelling: pre-rename kinds
                            "reservation_kind": "family",
                            "container_kind": "family",
                        },
                        "foo--0": {
                            "name": "foo--0",
                            "source": "artifact",
                            "artifacts_dir": str(artifact_dir),
                            "reservation_kind": "claimed",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        reset_name_registry_caches_for_tests()

        upgraded = _registry_store.read_registry(path)
        assert upgraded is not None
        assert upgraded["schema_version"] == 3
        assert upgraded["_needs_rebuild"] is True
        assert upgraded["entries"]["foo"]["reservation_kind"] == "session"
        assert upgraded["entries"]["foo"]["container_kind"] == "session"
        assert upgraded["entries"]["foo--0"]["reservation_kind"] == "claimed"

        assert _registry_queries.get_reserved_agent_session_names(
            load_registry=lambda: upgraded
        ) == {"foo"}
        # The raw legacy agent-family spelling still resolves through the
        # same reader.
        assert _registry_queries.get_reserved_agent_session_names(
            load_registry=lambda: {"entries": {"foo": {"container_kind": "family"}}}
        ) == {"foo"}

        data = load_name_registry()
        assert data["schema_version"] == 3
        assert data["entries"]["foo"]["container_kind"] == "session"
        assert data["entries"]["foo"]["reservation_kind"] == "session"
        assert get_reserved_agent_session_names() == {"foo"}

        rewritten = json.loads(path.read_text(encoding="utf-8"))
        assert rewritten["schema_version"] == 3
        for entry in rewritten["entries"].values():
            # legacy agent-family spelling must be gone after the rewrite
            assert entry.get("reservation_kind") != "family"
            assert entry.get("container_kind") != "family"


def test_v3_rebuild_emits_no_legacy_kinds(tmp_path: Path) -> None:
    """A v3 rebuild stores session container kinds and no legacy spelling."""
    _make_session_agent(tmp_path, "run1", "foo")
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        written = json.loads(
            _registry_store.registry_path().read_text(encoding="utf-8")
        )

    assert written["schema_version"] == 3
    assert written["entries"]["foo"]["container_kind"] == "session"
    assert written["entries"]["foo"]["reservation_kind"] == "session"
    for entry in written["entries"].values():
        # legacy agent-family spelling: must never be emitted by a v3 rebuild
        assert entry.get("reservation_kind") != "family"
        assert entry.get("container_kind") != "family"


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
