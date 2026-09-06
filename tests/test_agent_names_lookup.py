"""Lookup/history tests for sase.agent.names."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)

from sase.agent.names import (
    find_agent_clan,
    find_agent_family,
    find_named_agent,
    get_most_recent_agent_name,
    is_agent_clan_complete,
    is_agent_family_complete,
    most_recent_completed_clan_member,
    most_recent_completed_family_member,
    resolve_resume_agent_name,
    resolve_wait_dependency,
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


class TestFindNamedAgent:
    def test_finds_done_agent(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True, outcome="success")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "success"

    def test_local_bare_and_qualified_selectors_share_exact_first_lookup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _configure_machine(monkeypatch)
        legacy = _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        qualified = _make_agent(
            tmp_path,
            "proj",
            "run2",
            "athena.foo",
            done=True,
        )
        foreign = _make_agent(
            tmp_path,
            "proj",
            "run3",
            "zeus.foo",
            done=True,
        )

        with patch.object(Path, "home", return_value=tmp_path):
            bare_result = find_named_agent("foo")
            qualified_result = find_named_agent("athena.foo")
            foreign_result = find_named_agent("zeus.foo")

        assert bare_result is not None
        assert bare_result.artifacts_dir == str(legacy)
        assert qualified_result is not None
        assert qualified_result.artifacts_dir == str(qualified)
        assert foreign_result is not None
        assert foreign_result.artifacts_dir == str(foreign)

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("bar")
        assert result is None

    def test_returns_none_when_no_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is None

    def test_prefers_running_over_done(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        running_dir = _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert not result.is_done
        assert result.artifacts_dir == str(running_dir)

    def test_finds_agent_by_workflow_name(self, tmp_path: Path) -> None:
        """Resolves workflow name to the most recent done child agent."""
        _make_agent(tmp_path, "proj", "run1", "a.1", workflow_name="a", pid=_DEAD_PID)
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
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("a")
        assert result is not None
        assert result.is_done
        assert result.outcome == "completed"
        assert result.artifacts_dir == str(child_dir)

    def test_exact_name_preferred_over_workflow(self, tmp_path: Path) -> None:
        """Exact name match takes priority over workflow_name match."""
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
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("a")
        assert result is not None
        assert result.artifacts_dir == str(exact_dir)

    def test_skips_dead_agent_without_done(self, tmp_path: Path) -> None:
        """Dead parent phases (no done.json, dead PID) are skipped."""
        _make_agent(tmp_path, "proj", "run-old", "foo", pid=_DEAD_PID)
        done_dir = _make_agent(
            tmp_path, "proj", "run-new", "foo", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "completed"
        assert result.artifacts_dir == str(done_dir)

    def test_only_done_skips_running(self, tmp_path: Path) -> None:
        """only_done=True skips running agents and returns done one."""
        _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        done_dir = _make_agent(
            tmp_path, "proj", "run-old", "foo", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo", only_done=True)
        assert result is not None
        assert result.is_done
        assert result.artifacts_dir == str(done_dir)

    def test_only_done_returns_none_when_no_done(self, tmp_path: Path) -> None:
        """only_done=True returns None when only running agents exist."""
        _make_agent(tmp_path, "proj", "run1", "foo", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo", only_done=True)
        assert result is None

    def test_finds_dismissed_prefixed_artifact_without_done(
        self, tmp_path: Path
    ) -> None:
        """Dismissal removes done.json but keeps the prefixed agent_meta.json.

        Historical references like ``%w:260428.foo`` and ``#fork:260428.foo``
        must still resolve, so dismissed-prefixed artifacts are treated as
        completed-historical even when their done.json is gone.
        """
        artifact_dir = _make_agent(
            tmp_path, "proj", "run-old", "260428.foo", pid=_DEAD_PID
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("260428.foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "dismissed"
        assert result.artifacts_dir == str(artifact_dir)

    def test_finds_dismissed_name_via_bundle_when_artifact_gone(
        self, tmp_path: Path
    ) -> None:
        """Bundles are the source of truth when the artifact dir is purged."""
        bundles_dir = tmp_path / ".sase" / "dismissed_bundles" / "202604"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "20260428103000.json").write_text(
            json.dumps(
                {
                    "agent_name": "260428.bar",
                    "raw_suffix": "20260428103000",
                    "cl_name": "bar",
                }
            )
        )
        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            result = find_named_agent("260428.bar")
        assert result is not None
        assert result.is_done
        assert result.outcome == "dismissed"


class TestGetMostRecentAgentName:
    """Bare ``%wait`` should never resolve to a dismissed historical name."""

    def test_skips_dismissed_prefixed_names(self, tmp_path: Path) -> None:
        # Older active name + newer dismissed-prefixed name. Without the
        # filter, the dismissed entry would win because its directory
        # name sorts later.
        _make_agent(tmp_path, "proj", "20260427000000", "foo", done=True)
        _make_agent(tmp_path, "proj", "20260428000000", "260428.bar", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_most_recent_agent_name()
        assert result == "foo"

    def test_returns_none_when_only_dismissed_prefixed(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "20260428000000", "260428.foo", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_most_recent_agent_name()
        assert result is None


def test_find_agent_family_includes_sequential_descendants(tmp_path: Path) -> None:
    _make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "foo--0",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--0",
        done=True,
    )
    _make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "foo--review",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--review",
        parent_timestamp="20260701010101",
        done=True,
    )
    _make_agent(
        tmp_path,
        "proj",
        "20260701010303",
        "foo--land",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--land",
        parent_timestamp="20260701010202",
        done=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        family = find_agent_family("foo")

    assert family is not None
    assert [member.name for member in family.members] == [
        "foo--0",
        "foo--review",
        "foo--land",
    ]


def test_family_lookup_combines_legacy_and_qualified_local_relations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    _make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "foo--0",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--0",
        done=True,
    )
    _make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "athena.foo--code",
        workflow_name="athena.foo",
        agent_family="athena.foo",
        role_suffix="--code",
        parent_timestamp="20260701010101",
        done=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        family = find_agent_family("foo")

    assert family is not None
    assert [member.name for member in family.members] == [
        "foo--0",
        "athena.foo--code",
    ]


def test_family_lookup_accepts_dotted_numeric_family_roots(
    tmp_path: Path,
) -> None:
    base_name = "sase-x7.3.1.5"
    _make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        f"{base_name}--plan",
        workflow_name=base_name,
        agent_family=base_name,
        role_suffix="--plan",
        done=True,
    )
    newest = _make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        f"{base_name}--code",
        workflow_name=base_name,
        agent_family=base_name,
        role_suffix="--code",
        parent_timestamp="20260701010101",
        done=True,
        outcome="completed",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        family = find_agent_family(base_name)
        legacy_parent = find_agent_family("sase-x7.3.1")
        resolved = resolve_resume_agent_name(base_name)

    assert family is not None
    assert [member.name for member in family.members] == [
        f"{base_name}--plan",
        f"{base_name}--code",
    ]
    assert legacy_parent is None
    assert resolved is not None
    assert resolved.artifacts_dir == str(newest)


def test_resume_family_name_uses_newest_completed_renamed_member(
    tmp_path: Path,
) -> None:
    _make_agent(
        tmp_path,
        "proj",
        "20260718010101",
        "foo--plan",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    newest = _make_agent(
        tmp_path,
        "proj",
        "20260718010202",
        "foo--code",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--code",
        parent_timestamp="20260718010101",
        done=True,
        outcome="completed",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        resolved = resolve_resume_agent_name("foo")

    assert resolved is not None
    assert resolved.name == "foo--code"
    assert resolved.artifacts_dir == str(newest)


def _add_meta_fields(artifact_dir: Path, extra: dict[str, object]) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    data = json.loads(meta_path.read_text())
    data.update(extra)
    meta_path.write_text(json.dumps(data))


@pytest.mark.parametrize("outcome", ["noop", "epic_approved", "plan_committed"])
class TestWaitSuccessOutcomeClassification:
    """noop/epic_approved/plan_committed count as success, like "completed"."""

    def test_family_is_complete_and_resolves_newest_success_member(
        self, tmp_path: Path, outcome: str
    ) -> None:
        _make_agent(
            tmp_path,
            "proj",
            "20260718010101",
            "foo--plan",
            workflow_name="foo",
            agent_family="foo",
            role_suffix="--plan",
            done=True,
            outcome="completed",
        )
        newest = _make_agent(
            tmp_path,
            "proj",
            "20260718010202",
            "foo--code",
            workflow_name="foo",
            agent_family="foo",
            role_suffix="--code",
            parent_timestamp="20260718010101",
            done=True,
            outcome=outcome,
        )

        with patch.object(Path, "home", return_value=tmp_path):
            assert is_agent_family_complete("foo") is True
            member = most_recent_completed_family_member("foo")
            assert resolve_wait_dependency("foo") is True
            resolved = resolve_resume_agent_name("foo")

        assert member is not None
        assert member.artifacts_dir == str(newest)
        assert resolved is not None
        assert resolved.artifacts_dir == str(newest)

    def test_clan_is_complete_and_resolves_newest_success_member(
        self, tmp_path: Path, outcome: str
    ) -> None:
        older = _make_agent(
            tmp_path,
            "proj",
            "20260718010101",
            "review.alpha",
            done=True,
            outcome="completed",
        )
        _add_meta_fields(
            older,
            {"agent_clan": "review", "agent_clan_generation": "20260718010000"},
        )
        newest = _make_agent(
            tmp_path,
            "proj",
            "20260718010202",
            "review.beta",
            done=True,
            outcome=outcome,
        )
        _add_meta_fields(
            newest,
            {"agent_clan": "review", "agent_clan_generation": "20260718010000"},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            clan = find_agent_clan("review")
            assert clan is not None
            assert clan.is_complete is True
            assert is_agent_clan_complete("review") is True
            assert resolve_wait_dependency("review") is True
            member = most_recent_completed_clan_member("review")

        assert member is not None
        assert member.artifacts_dir == str(newest)

    def test_bare_named_agent_resolves_as_wait_success(
        self, tmp_path: Path, outcome: str
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True, outcome=outcome)

        with patch.object(Path, "home", return_value=tmp_path):
            assert resolve_wait_dependency("foo") is True


def test_family_incomplete_when_member_outcome_is_plan_rejected(
    tmp_path: Path,
) -> None:
    """plan_rejected stays excluded from wait/family success classification."""
    _make_agent(
        tmp_path,
        "proj",
        "20260718010101",
        "foo--plan",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--plan",
        done=True,
        outcome="plan_rejected",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        assert is_agent_family_complete("foo") is False
        assert resolve_wait_dependency("foo") is False


def test_bare_named_agent_with_plan_rejected_outcome_is_not_wait_success(
    tmp_path: Path,
) -> None:
    _make_agent(tmp_path, "proj", "run1", "foo", done=True, outcome="plan_rejected")

    with patch.object(Path, "home", return_value=tmp_path):
        assert resolve_wait_dependency("foo") is False
