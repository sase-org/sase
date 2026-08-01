"""Tests for ``sase agent prompts`` CLI handling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.agents import cli_prompts
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.main.parser import create_parser, default_list_delegation_notice


def _target(repo: Path, workspace: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="project-key",
        project="Project",
        primary_checkout=workspace,
        primary_roots=(workspace,),
        sidecar_path=repo,
        remote_url="git@example.test:project/agents.git",
    )


def _args(subcommand: str, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "prompts_subcommand": subcommand,
        "json": False,
        "month": None,
        "project": None,
        "show_warnings": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_bare_agent_prompts_defaults_to_list() -> None:
    args = create_parser().parse_args(["agent", "prompts"])

    assert args.prompts_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase agent prompts'; "
        "delegating to 'sase agent prompts list'."
    )


def test_prompt_month_rejects_invalid_format() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["agent", "prompts", "validate", "--month", "202613"])

    assert excinfo.value.code == 2


def test_prompt_list_and_validate_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "agents"
    workspace = tmp_path / "workspace"
    prompt = repo / "prompts/202608/example.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    target = _target(repo, workspace)
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((target,), ()),
    )
    monkeypatch.setattr(cli_prompts, "_plans_repo", lambda _target: None)

    assert cli_prompts.handle_agents_prompts(_args("list", json=True)) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing[0]["path"] == "prompts/202608/example.md"

    assert cli_prompts.handle_agents_prompts(_args("validate", json=True)) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["ok"] is True
    assert validation["files"][0]["name"] == "example"
