"""Parser and handler tests for ``sase repo``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.repo_handler import handle_repo_command
from sase.repo_inventory import RepoInventory, RepoRecord


def test_repo_parser_defaults_to_list() -> None:
    args = create_parser().parse_args(["repo"])
    assert args.command == "repo"
    assert args.repo_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase repo'; delegating to 'sase repo list'."
    )


def test_repo_list_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = RepoRecord(
        name="widget",
        kind="primary",
        project="widget",
        project_key="widget",
        path=str(tmp_path),
        exists=True,
        auto_clone=False,
        description=None,
        source="ProjectSpec",
        env_name=None,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((record,)),
    )
    args = create_parser().parse_args(["repo", "list", "--json"])

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repos"][0]["kind"] == "primary"
    assert payload["repos"][0]["path"] == str(tmp_path)
