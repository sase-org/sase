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

    def test_later_exact_spelling_survives_ineligible_workflow_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure_machine(monkeypatch)
        child = _make_agent(
            tmp_path,
            "proj",
            "run1",
            "alice.athena.foo",
            workflow_name="foo",
            parent_timestamp="root",
            pid=os.getpid(),
        )
        _patched_indexed(monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _rebuild_artifact_index()
            result = find_named_agent("foo")
        assert result is not None
        assert result.name == "alice.athena.foo"
        assert result.artifacts_dir == str(child)
        assert not result.is_done

    def test_incomplete_artifact_recovery_raises_instead_of_proving_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        from sase.agent.names._lookup_named import AgentNamedLookupUnavailable

        monkeypatch.setattr(
            "sase.core.agent_artifact_lookup.lookup_agent_artifacts",
            lambda *_args, **_kwargs: SimpleNamespace(
                complete=False,
                availability="missing",
                source="fallback",
                diagnostic="fallback budget exhausted",
                truncated=True,
            ),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(AgentNamedLookupUnavailable):
                find_named_agent("missing")


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

    def test_deleted_newest_bundle_uses_older_valid_summary(
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
            shard = bundles_dir / "202611"
            shard.mkdir(parents=True)
            older = shard / "20261116010000.json"
            newer = shard / "20261116020000.json"
            older.write_text(
                json.dumps(
                    {
                        "agent_name": "deleted-newest-agent",
                        "raw_suffix": "20261116010000",
                        "artifacts_dir": "/archive/older",
                        "cl_name": "older",
                    }
                ),
                encoding="utf-8",
            )
            newer.write_text(
                json.dumps(
                    {
                        "agent_name": "deleted-newest-agent",
                        "raw_suffix": "20261116020000",
                        "artifacts_dir": "/archive/newer",
                        "cl_name": "newer",
                    }
                ),
                encoding="utf-8",
            )
            rebuild_dismissed_bundle_index()
            newer.unlink()
            _patched_indexed(monkeypatch)
            result = find_named_agent("deleted-newest-agent")

        assert result is not None
        assert result.is_done
        assert result.artifacts_dir == "/archive/older"


def test_find_named_agent_retries_busy_lookup_only_with_runner_patience(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.names._lookup_named import AgentNamedLookupUnavailable
    from sase.core import agent_artifact_lookup
    from sase.core.index_lookup_patience import (
        LookupPatience,
        process_lookup_patience,
        retry_while_busy,
    )
    from sase.core.rust import require_rust_binding as real_require_rust_binding

    _configure_machine(monkeypatch)
    _make_agent(tmp_path, "proj", "run1", "foo", done=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _rebuild_artifact_index()

    real_lookup = real_require_rust_binding("lookup_agent_artifacts")
    calls = 0

    def lookup_with_initial_busy(*args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "availability": "busy",
                "complete": False,
                "source": "fallback",
                "diagnostic": "database is locked",
            }
        return real_lookup(*args)

    def require_binding(name: str):
        if name == "lookup_agent_artifacts":
            return lookup_with_initial_busy
        return real_require_rust_binding(name)

    monkeypatch.setattr(agent_artifact_lookup, "require_rust_binding", require_binding)

    with process_lookup_patience(None):
        with pytest.raises(AgentNamedLookupUnavailable):
            find_named_agent("foo")
    assert calls == 1

    calls = 0
    now = 0.0

    def fake_retry(attempt: object, **kwargs: object) -> object:
        def sleep(seconds: float) -> None:
            nonlocal now
            now += seconds

        return retry_while_busy(
            attempt,  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
            sleep=sleep,
            monotonic=lambda: now,
        )

    monkeypatch.setattr(agent_artifact_lookup, "retry_while_busy", fake_retry)
    with process_lookup_patience(LookupPatience(1)):
        result = find_named_agent("foo")

    assert result is not None
    assert result.name == "foo"
    assert calls == 2
