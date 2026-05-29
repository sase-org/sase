from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from sase.memory.episodes.storage import write_project_episode
from tests._memory_episodes_cli_helpers import _identity_episode, _source_ref


def test_memory_episodes_cli_resolves_alias_ids(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    chat_a = tmp_path / "chat-a.md"
    chat_b = tmp_path / "chat-b.md"
    write_project_episode(
        _identity_episode(
            "ep-a",
            component_key="component/a",
            sources=[_source_ref(chat_a, kind="chat", content="a\n")],
            title="Episode A",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _identity_episode(
            "ep-b",
            component_key="component/b",
            sources=[_source_ref(chat_b, kind="chat", content="b\n")],
            title="Episode B",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _identity_episode(
            "ep-a",
            component_key="component/a",
            sources=[
                _source_ref(chat_a, kind="chat", content="a\n"),
                _source_ref(chat_b, kind="chat", content="b\n"),
            ],
            title="Bridge Episode",
        ),
        projects_root=projects_root,
    )

    list_args = create_parser().parse_args(
        ["memory", "episodes", "list", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(list_args, projects_root=projects_root)
    list_payload = json.loads(capsys.readouterr().out)
    assert [row["episode_id"] for row in list_payload["episodes"]] == ["ep-a"]
    assert [
        (row["alias_episode_id"], row["canonical_episode_id"])
        for row in list_payload["aliases"]
    ] == [("ep-b", "ep-a")]

    show_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-b", "-p", "proj"]
    )
    handle_memory_episodes_command(show_args, projects_root=projects_root)
    captured = capsys.readouterr()
    assert "Bridge Episode" in captured.out
    assert "`ep-b` is an alias for `ep-a`" in captured.err

    verify_args = create_parser().parse_args(
        ["memory", "episodes", "verify", "ep-b", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(verify_args, projects_root=projects_root)
    captured = capsys.readouterr()
    assert json.loads(captured.out)["reports"][0]["episode_id"] == "ep-a"
    assert "`ep-b` is an alias for `ep-a`" in captured.err

    recall_args = create_parser().parse_args(
        ["memory", "episodes", "recall", "-p", "proj", "-q", "ep-b", "-j"]
    )
    handle_memory_episodes_command(recall_args, projects_root=projects_root)
    recall_payload = json.loads(capsys.readouterr().out)
    assert recall_payload["matches"][0]["episode_id"] == "ep-a"
