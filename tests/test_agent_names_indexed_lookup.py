"""Indexed named-agent lookup parity and healthy-index regression tests.

Proves ``find_named_agent`` preserves fixture results while reading only
matching records: the unbounded artifact scanner and the dismissed-bundle
``rglob`` are patched to fail, so any unrelated archive read breaks the test.
Covers duplicate names, exact-versus-workflow collisions, alive/dead/done,
``only_done``/``include_dead``, qualified/local/foreign spellings, dismissed
prefixes, bundle-only agents, child bundles, and all archive visibilities.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import find_named_agent
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)

from tests._agent_names_fixtures import DEAD_PID as _DEAD_PID
from tests._agent_names_fixtures import make_agent as _make_agent


def _configure_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def _failing_scan(*args: object, **kwargs: object) -> object:
    raise AssertionError("indexed lookup must not call scan_agent_artifacts")


def _failing_rglob(self: object, *args: object, **kwargs: object) -> object:
    raise AssertionError("indexed lookup must not rglob dismissed bundles")


def _patched_indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.scan_agent_artifacts", _failing_scan
    )
    monkeypatch.setattr(Path, "rglob", _failing_rglob)


def _rebuild_artifact_index() -> None:
    """Rebuild the artifact index for the (patched) home."""
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        rebuild_agent_artifact_index,
    )
    from sase.core.paths import sase_projects_dir

    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(), sase_projects_dir()
    )


def _write_bundle(tmp_path: Path, raw_suffix: str, payload: dict[str, object]) -> Path:
    from sase.ace import dismissed_agents

    bundles_dir = dismissed_agents.dismissed_bundles_dir()
    shard = bundles_dir / raw_suffix[:6]
    shard.mkdir(parents=True, exist_ok=True)
    target = shard / f"{raw_suffix}.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


class TestIndexedNamedLookupParity:
    def test_exact_beats_workflow_with_scanners_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            done=True,
            outcome="completed",
        )
        exact_dir = _make_agent(
            tmp_path, "proj", "run2", "a", done=True, outcome="completed"
        )
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            result = find_named_agent("a")
        assert result is not None
        assert result.artifacts_dir == str(exact_dir)

    def test_live_beats_done_with_scanners_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        running_dir = _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            result = find_named_agent("foo")
        assert result is not None
        assert not result.is_done
        assert result.artifacts_dir == str(running_dir)

    def test_only_done_and_include_dead_parity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        done_dir = _make_agent(
            tmp_path, "proj", "run-old", "foo", done=True, outcome="completed"
        )
        crashed_dir = _make_agent(tmp_path, "proj", "run-crashed", "bar", pid=_DEAD_PID)
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            assert find_named_agent("foo", only_done=True) is not None
            assert find_named_agent("foo", only_done=True).artifacts_dir == str(
                done_dir
            )
            assert find_named_agent("bar") is None
            assert find_named_agent("bar", include_dead=True) is not None
            assert find_named_agent("bar", include_dead=True).artifacts_dir == str(
                crashed_dir
            )

    def test_workflow_match_requires_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            done=True,
            outcome="completed",
        )
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            result = find_named_agent("a")
        assert result is not None
        assert result.is_done
        assert result.artifacts_dir == str(child_dir)

    def test_owner_spellings_share_exact_first_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure_machine(monkeypatch)
        legacy = _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        qualified = _make_agent(tmp_path, "proj", "run2", "athena.foo", done=True)
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            assert find_named_agent("foo").artifacts_dir == str(legacy)
            assert find_named_agent("athena.foo").artifacts_dir == str(qualified)

    def test_healthy_miss_with_scanners_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            assert find_named_agent("bar") is None


class TestIndexedDismissedBundles:
    def test_bundle_fallback_without_artifact_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
        ):
            _rebuild_artifact_index()
            from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index
            from sase.ace import dismissed_agents

            bundles_dir = dismissed_agents.dismissed_bundles_dir()
            shard = bundles_dir / "202604"
            shard.mkdir(parents=True)
            (shard / "20260428103000.json").write_text(
                json.dumps(
                    {
                        "agent_name": "260428.bar",
                        "raw_suffix": "20260428103000",
                        "cl_name": "bar",
                    }
                )
            )
            rebuild_dismissed_bundle_index()
            _patched_indexed(monkeypatch)
            result = find_named_agent("260428.bar")
        assert result is not None
        assert result.is_done
        assert result.outcome == "dismissed"

    def test_bundle_workflow_name_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
        ):
            _rebuild_artifact_index()
            from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index
            from sase.ace import dismissed_agents

            bundles_dir = dismissed_agents.dismissed_bundles_dir()
            shard = bundles_dir / "202605"
            shard.mkdir(parents=True)
            (shard / "20260501120000.json").write_text(
                json.dumps(
                    {
                        "agent_name": "other-agent",
                        "workflow_name": "wanted-wf",
                        "raw_suffix": "20260501120000",
                        "cl_name": "wf_cl",
                    }
                )
            )
            rebuild_dismissed_bundle_index()
            _patched_indexed(monkeypatch)
            result = find_named_agent("wanted-wf")
        assert result is not None
        assert result.is_done

    def test_bundle_search_covers_all_visibilities(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
        ):
            _rebuild_artifact_index()
            from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index
            from sase.ace.dismissed_bundle_index import (
                set_archive_visibility_for_suffixes,
            )
            from sase.ace import dismissed_agents

            bundles_dir = dismissed_agents.dismissed_bundles_dir()
            shard = bundles_dir / "202606"
            shard.mkdir(parents=True)
            (shard / "20260601120000.json").write_text(
                json.dumps(
                    {
                        "agent_name": "visible-agent",
                        "raw_suffix": "20260601120000",
                        "cl_name": "vis_cl",
                    }
                )
            )
            rebuild_dismissed_bundle_index()
            set_archive_visibility_for_suffixes(
                bundles_dir, {"20260601120000"}, "visible"
            )
            _patched_indexed(monkeypatch)
            result = find_named_agent("visible-agent")
        assert result is not None
        assert result.is_done
