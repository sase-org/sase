"""Authoritative hijack ingress uses only the indexed session's source records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.names import AgentSession, AgentSessionMember
from sase.running_field import WorkspaceClaim
from tests._agent_names_fixtures import make_agent
from tests._running_field_helpers import create_project_file_with_running


def test_indexed_hijack_matches_fixture_roster_without_global_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        rebuild_agent_artifact_index,
    )
    from sase.core.paths import sase_projects_dir
    from sase.agents.cli_hijack import handle_agents_hijack
    from sase.agent.hijack._stop_target import resolve_target

    root = make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "lane--plan",
        agent_session="lane",
        done=True,
        outcome="completed",
    )
    child = make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "lane--code",
        agent_session="lane",
        parent_timestamp=root.name,
        pid=424242,
        extra_meta={
            "runner_capabilities": ["hijack"],
            "lifecycle_phase": "provider_running",
            "workspace_dir": str(tmp_path / "workspace"),
        },
    )
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                4, "fixture", "fixture", pid=424242, artifacts_timestamp=child.name
            )
        ],
    )
    monkeypatch.setattr(
        "sase.agent.running.named_agent_project_fields",
        lambda agent: (
            Path(agent.artifacts_dir),
            "proj",
            project_file,
            Path(agent.artifacts_dir).name,
            False,
        ),
    )
    monkeypatch.setattr(
        "sase.agent.names._lookup_named.is_process_alive", lambda *_: True
    )
    monkeypatch.setattr("sase.agent.names.is_process_alive", lambda *_: True)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_target._claim_workspace_dir", lambda *_: None
    )
    members = (
        AgentSessionMember("lane--plan", root, root.name, "completed", None),
        AgentSessionMember("lane--code", child, child.name, None, root.name),
    )
    oracle = AgentSession("lane", members[0], members)
    row = SimpleNamespace(
        name="lane--code",
        artifacts_dir=str(child),
        status="RUNNING",
        pid=424242,
        workspace_num=4,
    )
    deps = StopDeps(
        find_session=lambda _: oracle,
        find_session_by_member_artifact_dir=lambda _: (oracle, members[1]),
        find_clan=lambda _: None,
        list_running=lambda: [row],
        process_alive=lambda *_: True,
    )
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_agent_artifact_index(
            default_agent_artifact_index_path(), sase_projects_dir()
        )
        _, expected = resolve_and_decide("lane", deps=deps)
        with (
            patch(
                "sase.core.agent_scan_facade.scan_agent_artifacts",
                side_effect=AssertionError("archive scan"),
            ) as scanner,
            patch(
                "sase.agent.running_listing.list_running_agents",
                side_effect=AssertionError("global listing"),
            ) as listing,
            patch(
                "sase.core.agent_artifact_paths.iter_agent_artifact_dirs",
                side_effect=AssertionError("directory walk"),
            ) as walk,
        ):
            subject, decision = resolve_and_decide("lane")
            target = resolve_target("lane", deps=StopDeps())
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
        scanner.assert_not_called()
        listing.assert_not_called()
        walk.assert_not_called()
    assert subject.occupant_name == "lane--code"
    assert target is not None and target.name == "lane--code"
    assert decision["mode"] == expected["mode"] == "immediate"
    assert decision["code"] == expected["code"]
    assert exit_code == 0
    assert payload["mode"] == expected["mode"]
    assert payload["occupant_name"] == "lane--code"
