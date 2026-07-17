"""Tests for ``sase agent tribe`` CLI subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import AgentType
from sase.agent.names import NamedAgent
from sase.agents.cli_show import handle_agents_show
from sase.agents.cli_tag import (
    _resolve_identity_by_name,
    handle_agents_tribe,
)


def _named(artifacts_dir: Path) -> NamedAgent:
    return NamedAgent(
        name="brisk-otter",
        artifacts_dir=str(artifacts_dir),
        is_done=True,
        outcome="completed",
    )


def _make_artifact_dir(
    tmp_path: Path,
    *,
    project: str = "sase",
    raw_suffix: str = "20260425120000",
    cl_name: str | None = "fix-bug",
    workflow_name: str | None = None,
    sharded: bool = False,
) -> Path:
    art_dir = tmp_path / "projects" / project / "artifacts" / "ace-run"
    if sharded:
        art_dir = art_dir / raw_suffix[:6] / raw_suffix[6:8]
    art_dir = art_dir / raw_suffix
    art_dir.mkdir(parents=True)
    (art_dir / "agent_meta.json").write_text(json.dumps({"pid": 1}))
    if cl_name is not None:
        (art_dir / "done.json").write_text(
            json.dumps({"cl_name": cl_name, "outcome": "completed"})
        )
    if workflow_name is not None:
        (art_dir / "workflow_state.json").write_text(
            json.dumps({"workflow_name": workflow_name})
        )
    return art_dir


def test_resolve_identity_returns_running_for_tmp_workflow(tmp_path: Path) -> None:
    art_dir = _make_artifact_dir(
        tmp_path,
        cl_name="fix-bug",
        workflow_name="tmp_260425_120000",
        raw_suffix="20260425120000",
    )
    with patch(
        "sase.agents.cli_tag.find_named_agent",
        return_value=_named(art_dir),
    ):
        identity = _resolve_identity_by_name("brisk-otter")
    assert identity == (AgentType.RUNNING, "fix-bug", "20260425120000")


def test_resolve_identity_returns_workflow_for_named_workflow(tmp_path: Path) -> None:
    art_dir = _make_artifact_dir(
        tmp_path,
        cl_name="ship-feature",
        workflow_name="ship_feature_pipeline",
        raw_suffix="20260425130000",
    )
    with patch(
        "sase.agents.cli_tag.find_named_agent",
        return_value=_named(art_dir),
    ):
        identity = _resolve_identity_by_name("brisk-otter")
    assert identity == (AgentType.WORKFLOW, "ship-feature", "20260425130000")


def test_resolve_identity_falls_back_to_project_name(tmp_path: Path) -> None:
    art_dir = _make_artifact_dir(
        tmp_path,
        project="dotfiles",
        cl_name=None,
        raw_suffix="20260425140000",
    )
    with patch(
        "sase.agents.cli_tag.find_named_agent",
        return_value=_named(art_dir),
    ):
        identity = _resolve_identity_by_name("brisk-otter")
    assert identity == (AgentType.RUNNING, "dotfiles", "20260425140000")


def test_resolve_identity_falls_back_to_project_name_for_sharded_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    art_dir = _make_artifact_dir(
        tmp_path,
        project="dotfiles",
        cl_name=None,
        raw_suffix="20260613120000",
        sharded=True,
    )
    with patch(
        "sase.agents.cli_tag.find_named_agent",
        return_value=_named(art_dir),
    ):
        identity = _resolve_identity_by_name("brisk-otter")
    assert identity == (AgentType.RUNNING, "dotfiles", "20260613120000")


def test_agents_show_reports_project_for_sharded_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    art_dir = _make_artifact_dir(
        tmp_path,
        project="dotfiles",
        cl_name="ship-it",
        raw_suffix="20260613123000",
        sharded=True,
    )
    with patch(
        "sase.agents.cli_show.find_named_agent",
        return_value=_named(art_dir),
    ):
        handle_agents_show(argparse.Namespace(name="brisk-otter"))

    assert "Project: dotfiles" in capsys.readouterr().out


def test_resolve_identity_returns_none_when_agent_missing() -> None:
    with patch("sase.agents.cli_tag.find_named_agent", return_value=None):
        assert _resolve_identity_by_name("ghost") is None


def _tribe_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "agent_subcommand": "tribe",
        "tribe_subcommand": "set",
        "name": "brisk-otter",
        "tribe": "release-blockers",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_tribe_set_persists_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    test_file = tmp_path / "agent_tags.json"
    identity = (AgentType.RUNNING, "fix-bug", "20260425120000")
    with (
        patch(
            "sase.agents.cli_tag._resolve_identity_by_name",
            return_value=identity,
        ),
        patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file),
    ):
        handle_agents_tribe(_tribe_args(tribe="release-blockers"))
    out = capsys.readouterr().out
    assert "release-blockers" in out
    persisted = json.loads(test_file.read_text())
    assert persisted == [
        {
            "id": ["run", "fix-bug", "20260425120000"],
            "tag": "release-blockers",
        }
    ]


def test_tribe_set_replaces_existing_tag(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text(json.dumps([{"id": ["run", "fix-bug", "ts"], "tag": "alpha"}]))
    identity = (AgentType.RUNNING, "fix-bug", "ts")
    with (
        patch(
            "sase.agents.cli_tag._resolve_identity_by_name",
            return_value=identity,
        ),
        patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file),
    ):
        handle_agents_tribe(_tribe_args(tribe="beta"))
    persisted = json.loads(test_file.read_text())
    assert persisted == [{"id": ["run", "fix-bug", "ts"], "tag": "beta"}]


def test_tribe_set_rejects_at_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_tribe(_tribe_args(tribe="@release"))
    assert excinfo.value.code == 2
    assert "must not start with '@'" in capsys.readouterr().err


def test_tribe_set_rejects_invalid_characters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_tribe(_tribe_args(tribe="has space"))
    assert excinfo.value.code == 2
    assert "must match" in capsys.readouterr().err


def test_tribe_set_unknown_agent_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch("sase.agents.cli_tag._resolve_identity_by_name", return_value=None),
        patch(
            "sase.ace.agent_tags._AGENT_TAGS_FILE",
            tmp_path / "agent_tags.json",
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_tribe(_tribe_args(name="ghost"))
    assert excinfo.value.code == 2
    assert "No agent found" in capsys.readouterr().err


def test_tribe_unset_drops_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text(json.dumps([{"id": ["run", "fix-bug", "ts"], "tag": "alpha"}]))
    identity = (AgentType.RUNNING, "fix-bug", "ts")
    with (
        patch(
            "sase.agents.cli_tag._resolve_identity_by_name",
            return_value=identity,
        ),
        patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file),
    ):
        handle_agents_tribe(_tribe_args(tribe_subcommand="unset"))
    out = capsys.readouterr().out
    assert "(none)" in out
    assert json.loads(test_file.read_text()) == []


def test_tribe_list_all_emits_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text(
        json.dumps(
            [
                {
                    "id": ["run", "fix-bug", "ts1"],
                    "tag": "release-blockers",
                },
                {
                    "id": ["workflow", "ship", "ts2"],
                    "tag": "experiments",
                },
            ]
        )
    )
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        handle_agents_tribe(
            argparse.Namespace(
                agent_subcommand="tribe",
                tribe_subcommand="list",
                name=None,
            )
        )
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2
    by_cl = {row["cl_name"]: row for row in rows}
    assert by_cl["fix-bug"]["tag"] == "release-blockers"
    assert by_cl["ship"]["agent_type"] == "workflow"


def test_tribe_list_one_agent_emits_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    test_file = tmp_path / "agent_tags.json"
    identity = (AgentType.RUNNING, "fix-bug", "ts1")
    test_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "ts1"], "tag": "release-blockers"}])
    )
    with (
        patch(
            "sase.agents.cli_tag._resolve_identity_by_name",
            return_value=identity,
        ),
        patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file),
    ):
        handle_agents_tribe(
            argparse.Namespace(
                agent_subcommand="tribe",
                tribe_subcommand="list",
                name="brisk-otter",
            )
        )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "name": "brisk-otter",
        "agent_type": "run",
        "cl_name": "fix-bug",
        "raw_suffix": "ts1",
        "tag": "release-blockers",
    }


def test_tribe_unknown_subcommand_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_tribe(
            argparse.Namespace(
                agent_subcommand="tribe",
                tribe_subcommand="bogus",
            )
        )
    assert excinfo.value.code == 1
    assert "Usage: sase agent tribe" in capsys.readouterr().err
