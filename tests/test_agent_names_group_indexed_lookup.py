"""Indexed session and clan lookup parity and boundedness tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.names import (
    find_agent_clan,
    find_agent_session,
    find_agent_session_by_member_artifact_dir,
    find_agent_session_by_root_artifact_dir,
    is_agent_session_complete,
)
from sase.agent.names._common import NamedAgent
from sase.core.agent_artifact_group_lookup import AgentArtifactGroupLookupUnavailable
from sase.core.agent_artifact_lookup_wire import (
    AgentArtifactLookupResultWire,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests._agent_names_fixtures import make_agent


def _rebuild_index() -> None:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        rebuild_agent_artifact_index,
    )
    from sase.core.paths import sase_projects_dir

    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(), sase_projects_dir()
    )


def _current_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"), ("athena",))
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def _fail_archive_walk(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("healthy indexed group lookup walked the artifact archive")


def test_session_lookup_selects_latest_and_explicit_older_generation_without_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _current_owner(monkeypatch)
    old_root = make_agent(
        tmp_path,
        "proj-a",
        "20260701010101",
        "foo--plan",
        workflow_name="foo",
        agent_session="foo",
        role_suffix="--plan",
        done=True,
    )
    old_child = make_agent(
        tmp_path,
        "proj-b",
        "20260701010202",
        "athena.foo--code",
        workflow_name="athena.foo",
        agent_session="athena.foo",
        role_suffix="--code",
        parent_timestamp="20260701010101",
        done=True,
    )
    new_root = make_agent(
        tmp_path,
        "proj-b",
        "20260702010101",
        "foo--plan",
        workflow_name="foo",
        agent_session="foo",
        role_suffix="--plan",
        done=True,
    )
    new_child = make_agent(
        tmp_path,
        "proj-a",
        "20260702010202",
        "foo--commit",
        workflow_name="foo",
        agent_session="foo",
        role_suffix="--commit",
        parent_timestamp="20260702010101",
        done=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        monkeypatch.setattr(
            "sase.core.agent_artifact_paths.iter_agent_artifact_dirs",
            _fail_archive_walk,
        )

        latest = find_agent_session("foo")
        explicit_root = find_agent_session_by_root_artifact_dir(old_root)
        explicit_member = find_agent_session_by_member_artifact_dir(old_child)

    assert latest is not None
    assert latest.root is not None
    assert latest.root.artifacts_dir == new_root
    assert [member.artifacts_dir for member in latest.members] == [new_root, new_child]
    assert explicit_root is not None
    assert [member.artifacts_dir for member in explicit_root.members] == [
        old_root,
        old_child,
    ]
    assert explicit_member is not None
    generation, selected = explicit_member
    assert selected.artifacts_dir == old_child
    assert [member.artifacts_dir for member in generation.members] == [
        old_root,
        old_child,
    ]


def test_clan_lookup_combines_owner_spellings_and_legacy_parallel_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _current_owner(monkeypatch)
    make_agent(
        tmp_path,
        "proj-a",
        "20260701010101",
        "review.old",
        done=True,
        extra_meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260701010000",
        },
    )
    newest_local = make_agent(
        tmp_path,
        "proj-b",
        "20260702010101",
        "review.alpha",
        done=True,
        extra_meta={
            "agent_clan": "athena.review",
            "agent_clan_generation": "20260702010000",
        },
    )
    newest_global = make_agent(
        tmp_path,
        "proj-a",
        "20260702010202",
        "review.beta",
        done=True,
        extra_meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260702010000",
        },
    )
    legacy_parallel = make_agent(
        tmp_path,
        "proj-c",
        "20260703010101",
        "wave--1",
        agent_session="wave",
        extra_meta={"agent_session_parallel": True},
        done=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        monkeypatch.setattr(
            "sase.core.agent_artifact_paths.iter_agent_artifact_dirs",
            _fail_archive_walk,
        )
        clan = find_agent_clan("review")
        legacy = find_agent_clan("wave")

    assert clan is not None
    assert clan.generation == "20260702010000"
    assert [member.artifacts_dir for member in clan.members] == [
        newest_local,
        newest_global,
    ]
    assert legacy is not None
    assert [member.artifacts_dir for member in legacy.members] == [legacy_parallel]


def test_late_successor_and_marker_change_are_visible_after_index_population(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
    )
    child = make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp="20260701010101",
        done=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        successor = make_agent(
            tmp_path,
            "proj",
            "20260701010303",
            "lane--commit",
            workflow_name="lane",
            agent_session="lane",
            role_suffix="--commit",
            parent_timestamp="20260701010202",
            done=True,
        )
        from sase.core.agent_artifact_index_lifecycle_mutations import (
            upsert_agent_artifact_index_artifacts,
        )

        assert upsert_agent_artifact_index_artifacts([successor]) == 1
        monkeypatch.setattr(
            "sase.core.agent_artifact_paths.iter_agent_artifact_dirs",
            _fail_archive_walk,
        )
        before_marker_refresh = find_agent_session("lane")
        (root / "done.json").write_text(json.dumps({"outcome": "completed"}))
        after_marker_refresh = find_agent_session("lane")

    assert before_marker_refresh is not None
    assert [member.artifacts_dir for member in before_marker_refresh.members] == [
        root,
        child,
        successor,
    ]
    assert after_marker_refresh is not None
    assert after_marker_refresh.members[0].outcome == "completed"


def test_session_preserves_archived_completion_failure_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _current_owner(monkeypatch)
    root = make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
    )
    archived = make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp="20260701010101",
        done=True,
    )
    from tests._dismissed_completion_helpers import (
        add_archive_identity,
        rebuild_completion_archive,
        write_dismissed_completion,
    )

    add_archive_identity(archived)
    write_dismissed_completion(
        tmp_path,
        archived,
        "lane--code",
        status="FAILED",
    )
    (archived / "done.json").unlink()
    rebuild_completion_archive()

    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        session = find_agent_session("lane")
        complete = is_agent_session_complete("lane")

    assert session is not None
    assert session.root is not None
    assert [member.artifacts_dir for member in session.members] == [root, archived]
    assert session.members[1].outcome == "failed"
    assert session.members[1].archived_completion is not None
    assert complete is False


def test_incomplete_group_lookup_refuses_hijack_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "artifact"
    named = NamedAgent("lane", str(target), False, None)

    def incomplete_lookup(
        _index: Path | str,
        _projects: Path | str,
        query: object,
    ) -> AgentArtifactLookupResultWire:
        return AgentArtifactLookupResultWire(
            schema_version=38,
            index_path="/tmp/index.sqlite",
            projects_root="/tmp/projects",
            query=query,  # type: ignore[arg-type]
            availability="busy",
            complete=False,
            source="fallback",
            diagnostic="fallback budget exceeded",
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_lookup.lookup_agent_artifacts", incomplete_lookup
    )
    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentArtifactGroupLookupUnavailable):
            find_agent_session("lane")

        subject, decision = resolve_and_decide(
            "lane",
            deps=StopDeps(find_agent=lambda _name: named),
        )
        from sase.agents.cli_hijack import handle_agents_hijack

        exit_code = handle_agents_hijack(
            argparse.Namespace(
                name="lane",
                reason=None,
                json=True,
                cancel=False,
                explain=True,
                now=False,
            )
        )
        payload = json.loads(capsys.readouterr().out)

    assert subject.target is None
    assert subject.selected is None
    assert decision["mode"] == "refused"
    assert decision["code"] == "lookup_unavailable"
    assert "fallback budget exceeded" in decision["message"]
    assert exit_code == 2
    assert payload["reason"] == "lookup_unavailable"
    assert "fallback budget exceeded" in payload["message"]


def test_missing_target_query_does_not_walk_when_index_is_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "plain-agent",
        done=True,
    )
    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        monkeypatch.setattr(
            "sase.core.agent_artifact_paths.iter_agent_artifact_dirs",
            _fail_archive_walk,
        )
        assert find_agent_session("missing") is None
        assert find_agent_clan("missing") is None


def test_qualified_only_relation_preserves_requested_group_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _current_owner(monkeypatch)
    make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "athena.lane--1",
        agent_session="athena.lane",
        done=True,
        extra_meta={"agent_clan": "athena.review"},
    )
    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        session = find_agent_session("lane")
        clan = find_agent_clan("review")
    assert session is not None and session.base_name == "lane"
    assert clan is not None and clan.name == "review"


@pytest.mark.parametrize("cycle", [False, True])
def test_rootless_and_cyclic_sessions_keep_parent_traversal(
    tmp_path: Path,
    cycle: bool,
) -> None:
    first = make_agent(
        tmp_path,
        "proj-a",
        "20260701010101",
        "lane--mon",
        agent_session="lane",
        parent_timestamp="20260701010202" if cycle else "missing",
    )
    second = make_agent(
        tmp_path,
        "proj-b",
        "20260701010202",
        "lane--gate",
        agent_session="lane",
        parent_timestamp=first.name,
    )
    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        session = find_agent_session("lane")
        explicit = find_agent_session_by_member_artifact_dir(second)
    assert session is not None and session.root is None
    assert [member.artifacts_dir for member in session.members] == [first, second]
    assert explicit is not None and explicit[0].root is None
    assert [member.artifacts_dir for member in explicit[0].members] == [first, second]


def test_unindexed_explicit_member_cannot_become_a_standalone_target(
    tmp_path: Path,
) -> None:
    make_agent(tmp_path, "proj", "20260701010101", "lane--plan", agent_session="lane")
    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        child = make_agent(
            tmp_path,
            "proj",
            "20260701010202",
            "lane--code",
            agent_session="lane",
            parent_timestamp="20260701010101",
        )
        with pytest.raises(AgentArtifactGroupLookupUnavailable, match="not yet"):
            find_agent_session_by_member_artifact_dir(child)


def test_clan_ignores_unnamed_new_generation(tmp_path: Path) -> None:
    valid = make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "review.a",
        extra_meta={"agent_clan": "review", "agent_clan_generation": "100"},
    )
    make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "",
        extra_meta={"agent_clan": "review", "agent_clan_generation": "200"},
    )
    with patch.object(Path, "home", return_value=tmp_path):
        _rebuild_index()
        clan = find_agent_clan("review")
    assert clan is not None
    assert [member.artifacts_dir for member in clan.members] == [valid]
