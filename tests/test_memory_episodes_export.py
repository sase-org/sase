from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from sase.memory.episodes.storage import write_project_episode
from tests._memory_episodes_cli_helpers import _drilldown_episode


def test_memory_episodes_export_outputs_bounded_event_readiness_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    write_project_episode(_drilldown_episode(tmp_path), projects_root=projects_root)

    args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "export",
            "-p",
            "proj",
            "-s",
            "2026-05-26",
            "-u",
            "2026-05-26",
            "-b",
            "medium",
            "-B",
            "sase-48.6",
            "-j",
        ]
    )
    handle_memory_episodes_command(args, projects_root=projects_root)
    payload = json.loads(capsys.readouterr().out)

    assert payload["writes_events"] is False
    assert payload["filters"]["band"] == "medium"
    assert payload["limits"]["source_refs_per_episode"] == 20
    assert [episode["episode_id"] for episode in payload["episodes"]] == ["ep-drill"]
    episode = payload["episodes"][0]
    assert episode["importance"]["factors"][0]["kind"] == "verification_present"
    assert episode["safety"]["warnings"] == ["missing-source:src-missing"]
    assert episode["source_refs"][0]["kind"] == "chat"
    assert episode["weak_refs"]["bead_ids"] == ["sase-48.6"]
    assert not (tmp_path / "sdd" / "events").exists()


def test_memory_episodes_export_human_output_is_compact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    write_project_episode(_drilldown_episode(tmp_path), projects_root=projects_root)

    args = create_parser().parse_args(
        ["memory", "episodes", "export", "-p", "proj", "-q", "drilldown"]
    )
    handle_memory_episodes_command(args, projects_root=projects_root)
    output = capsys.readouterr().out

    assert "ep-drill  medium (55)  active  Drilldown Episode" in output
    assert "sources=1" in output
    assert "factors=Verification evidence is present" in output
