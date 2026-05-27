from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from sase.memory.episodes.storage import write_project_episode


def test_memory_episodes_cli_lists_shows_verifies_and_recalls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    source_path = tmp_path / "source.md"
    source_path.write_text("retry feedback source\n", encoding="utf-8")
    episode = _episode(source_path)
    write_project_episode(
        episode,
        lesson_markdown=(
            "# Retry Feedback Episode\n\n"
            "The agent learned to preserve deterministic retry feedback.\n"
        ),
        projects_root=projects_root,
    )

    list_args = create_parser().parse_args(
        ["memory", "episodes", "list", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(list_args, projects_root=projects_root)
    list_payload = json.loads(capsys.readouterr().out)
    assert [row["episode_id"] for row in list_payload["episodes"]] == ["ep-cli"]

    show_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-cli", "-p", "proj"]
    )
    handle_memory_episodes_command(show_args, projects_root=projects_root)
    assert "deterministic retry feedback" in capsys.readouterr().out

    timeline_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-cli", "-p", "proj", "-f", "timeline"]
    )
    handle_memory_episodes_command(timeline_args, projects_root=projects_root)
    assert "Agent finished" in capsys.readouterr().out

    verify_args = create_parser().parse_args(
        ["memory", "episodes", "verify", "ep-cli", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(verify_args, projects_root=projects_root)
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["reports"][0]["ok"] is True

    recall_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "recall",
            "-p",
            "proj",
            "-q",
            "retry feedback",
            "-j",
        ]
    )
    handle_memory_episodes_command(recall_args, projects_root=projects_root)
    recall_payload = json.loads(capsys.readouterr().out)
    assert recall_payload["matches"][0]["episode_id"] == "ep-cli"
    assert recall_payload["matches"][0]["matched_terms"] == ["feedback", "retry"]


def test_memory_episodes_build_writes_episode_from_agent_selector(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260526120000"
    artifact_dir.mkdir(parents=True)
    chat_path = tmp_path / "chat.md"
    chat_path.write_text(
        "## Prompt\n\nBuild retry feedback memory.\n\n"
        "## Response\n\nImplemented it and ran `just check`.\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "output.txt"
    output_path.write_text("just check\npassed\n", encoding="utf-8")
    (artifact_dir / "submitted_xprompt.md").write_text(
        "# Retry Feedback Memory\n\nBuild an episode.\n",
        encoding="utf-8",
    )
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "episode-agent",
            "chat_path": str(chat_path),
            "phase_bead_id": "sase-45.5",
            "plan_action": "approve",
            "plan_approved": True,
            "plan_submitted_at": ["2026-05-26T12:01:00Z"],
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "name": "episode-agent",
            "outcome": "completed",
            "finished_at": 1.0,
            "response_path": str(chat_path),
            "output_path": str(output_path),
        },
    )

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-j"]
    )
    handle_memory_episodes_command(
        build_args,
        projects_root=projects_root,
        repo_root=tmp_path,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["wrote"] is True
    assert payload["episode_id"].startswith("ep-")
    assert payload["project"] == "proj"
    assert payload["source_count"] >= 4
    assert Path(payload["episode_dir"], "episode.json").is_file()


def _episode(source_path: Path) -> EpisodeWire:
    content = source_path.read_bytes()
    source = EpisodeSourceRefWire(
        id="src-cli",
        kind="chat",
        path=str(source_path.resolve(strict=False)),
        label=source_path.name,
        exists=True,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id="ep-cli",
        project="proj",
        title="Retry Feedback Episode",
        summary="Captured retry feedback for deterministic memory.",
        root_source_id=source.id,
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id="node-agent",
                kind="agent_run",
                label="episode-agent",
                metadata={"outcome": "completed"},
            )
        ],
        edges=[],
        events=[
            EpisodeEventWire(
                id="event-finish",
                kind="agent_finish",
                title="Agent finished",
                timestamp="2026-05-26T12:00:00Z",
                evidence_ids=[source.id],
            )
        ],
        lessons=[
            EpisodeLessonWire(
                id="lesson-feedback",
                kind="feedback",
                text="Retry feedback should stay deterministic.",
                evidence_ids=[source.id],
            )
        ],
    )


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
