from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from sase.memory.episodes.storage import write_project_episode
from tests._memory_episodes_cli_helpers import _drilldown_episode


def test_memory_episodes_show_v2_drill_down_formats(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    episode = _drilldown_episode(tmp_path)
    write_project_episode(episode, projects_root=projects_root)

    default_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-drill", "-p", "proj"]
    )
    handle_memory_episodes_command(default_args, projects_root=projects_root)
    overview = capsys.readouterr().out
    assert "# Drilldown Episode" in overview
    assert "Importance: medium (55)" in overview
    assert "Weak Metadata" in overview

    graph_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "show",
            "ep-drill",
            "-p",
            "proj",
            "-f",
            "graph",
            "-e",
            "all",
        ]
    )
    handle_memory_episodes_command(graph_args, projects_root=projects_root)
    graph = capsys.readouterr().out
    assert "Edge mode: all" in graph
    assert "planner -> drilldown.md [response_chat; strong]" in graph
    assert "planner -> cl-drill [changespec; weak]" in graph

    sources_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-drill", "-p", "proj", "-f", "sources"]
    )
    handle_memory_episodes_command(sources_args, projects_root=projects_root)
    sources = capsys.readouterr().out
    assert "# Sources: Drilldown Episode" in sources
    assert "sha256=" in sources

    agent_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "show",
            "ep-drill",
            "-p",
            "proj",
            "-f",
            "agent",
            "-j",
        ]
    )
    handle_memory_episodes_command(agent_args, projects_root=projects_root)
    payload = json.loads(capsys.readouterr().out)
    assert payload["episode_id"] == "ep-drill"
    assert payload["framing"].startswith("This is historical evidence")
    assert payload["source_refs"][0]["kind"] == "chat"
