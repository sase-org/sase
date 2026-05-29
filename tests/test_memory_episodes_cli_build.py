from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.episode_wire import EPISODE_WIRE_SCHEMA_VERSION
from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from tests._memory_episodes_cli_helpers import (
    _seed_agent_artifacts,
    _seed_split_agent_artifacts,
)


def test_memory_episodes_build_writes_episode_from_agent_selector(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-j"]
    )
    handle_memory_episodes_command(
        build_args,
        projects_root=projects_root,
        repo_root=repo_root,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["wrote"] is True
    assert payload["episode_id"].startswith("ep-")
    assert payload["project"] == "proj"
    assert payload["source_count"] >= 4
    assert payload["schema_version"] == EPISODE_WIRE_SCHEMA_VERSION
    assert payload["build_request"] == {
        "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
        "project": "proj",
        "selector_kind": "agent",
        "selector_value": "episode-agent",
        "since": None,
        "until": None,
        "limit": None,
        "dry_run": False,
        "force": False,
        "source_refs": payload["episode"]["sources"],
    }
    assert payload["build_report"] == {
        "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
        "project": "proj",
        "source_count": payload["source_count"],
        "lesson_count": payload["lesson_count"],
        "episode_id": payload["episode_id"],
        "would_write": False,
        "changed": payload["changed"],
        "warnings": payload["warnings"],
    }
    assert Path(payload["episode_dir"], "episode.json").is_file()


def test_memory_episodes_split_build_writes_component_reports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_split_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "build",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-19",
            "--split",
            "-j",
        ]
    )
    handle_memory_episodes_command(
        build_args,
        projects_root=projects_root,
        repo_root=repo_root,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["split"] is True
    assert payload["aggregate"] is False
    assert payload["component_count"] == 2
    assert len(payload["build_reports"]) == 2
    assert len({component["episode_id"] for component in payload["components"]}) == 2
    assert all(
        component["build_report"]["episode_id"] == component["episode_id"]
        for component in payload["components"]
    )
    assert all(
        component["episode"]["lessons"] == [] for component in payload["components"]
    )
    assert all(
        not Path(component["episode_dir"], "lesson.md").exists()
        for component in payload["components"]
    )

    list_args = create_parser().parse_args(
        ["memory", "episodes", "list", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(list_args, projects_root=projects_root)
    list_payload = json.loads(capsys.readouterr().out)
    assert len(list_payload["episodes"]) == 2
    assert {episode["version"] for episode in list_payload["episodes"]} == {"v2"}


def test_memory_episodes_build_prints_progress_to_stderr_in_human_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent"]
    )
    handle_memory_episodes_command(
        build_args, projects_root=projects_root, repo_root=repo_root
    )
    captured = capsys.readouterr()

    for label in ("Collecting", "Building", "Rendering", "Writing"):
        assert label in captured.err, (
            f"expected phase label {label!r} in stderr, got: {captured.err!r}"
        )
    assert captured.out.startswith("Built episode ep-")
    assert "project: proj" in captured.out
    assert "episode_dir:" in captured.out


def test_memory_episodes_build_is_silent_on_stderr_in_json_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-j"]
    )
    handle_memory_episodes_command(
        build_args, projects_root=projects_root, repo_root=repo_root
    )
    captured = capsys.readouterr()

    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["wrote"] is True


def test_memory_episodes_build_quiet_flag_suppresses_progress(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-q"]
    )
    handle_memory_episodes_command(
        build_args, projects_root=projects_root, repo_root=repo_root
    )
    captured = capsys.readouterr()

    assert captured.err == ""
    assert captured.out.startswith("Built episode ep-")
