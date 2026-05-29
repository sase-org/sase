from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from sase.memory.episodes.storage import write_project_episode
from tests._memory_episodes_cli_helpers import _inventory_episode


def test_memory_episodes_list_inventory_filters_groups_and_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    write_project_episode(
        _inventory_episode(
            "ep-high",
            tmp_path,
            title="Retry Recovery",
            timestamp="2026-05-19T10:00:00Z",
            agent="agent-a",
            band="high",
            score=90,
            changespec="cl-retry",
            bead_id="sase-48.5",
            warnings=["missing-source:chat"],
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _inventory_episode(
            "ep-low",
            tmp_path,
            title="No-Op Cleanup",
            timestamp="2026-05-21T10:00:00Z",
            agent="agent-b",
            band="low",
            score=10,
            changespec="cl-cleanup",
            bead_id="sase-48.7",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _inventory_episode(
            "ep-span",
            tmp_path,
            title="Bridge Episode",
            timestamp="2026-05-18T22:00:00Z",
            agent="agent-c",
            band="medium",
            score=50,
            changespec="cl-bridge",
            bead_id="sase-48.6",
            extra_timestamp="2026-05-20T01:00:00Z",
        ),
        projects_root=projects_root,
    )

    human_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "list",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-20",
            "-g",
            "day",
            "-b",
            "high",
        ]
    )
    handle_memory_episodes_command(human_args, projects_root=projects_root)
    human = capsys.readouterr().out
    assert "2026-05-19:" in human
    assert "ep-high" in human
    assert "Retry Recovery" in human
    assert "chats=1" in human
    assert "sources=1" in human
    assert "warnings=1" in human
    assert "ep-low" not in human

    json_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "list",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-20",
            "-n",
            "agent-a",
            "-c",
            "cl-retry",
            "-B",
            "sase-48.5",
            "-q",
            "retry",
            "-o",
            "importance",
            "-j",
        ]
    )
    handle_memory_episodes_command(json_args, projects_root=projects_root)
    payload = json.loads(capsys.readouterr().out)
    assert [episode["episode_id"] for episode in payload["episodes"]] == ["ep-high"]
    assert payload["episodes"][0]["version"] == "v2"
    assert payload["episodes"][0]["warnings"] == ["missing-source:chat"]
    assert payload["filters"]["bead"] == "sase-48.5"

    span_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "list",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-19",
            "-q",
            "bridge",
            "-j",
        ]
    )
    handle_memory_episodes_command(span_args, projects_root=projects_root)
    span_payload = json.loads(capsys.readouterr().out)
    assert [episode["episode_id"] for episode in span_payload["episodes"]] == [
        "ep-span"
    ]
