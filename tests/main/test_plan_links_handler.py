"""Tests for ``sase plan links`` parsing, dispatch, listing, and repair."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main import plan_command_handler
from sase.main.parser import create_parser
from sase.main.plan_links_handler import handle_plan_links_command
from tests.main.plan_links_handler_helpers import (
    make_args,
    mark_tmp_path_as_project,
)

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


def test_parser_registers_nested_links_commands() -> None:
    parser = create_parser()

    bare = parser.parse_args(["plan", "links"])
    assert bare.command == "plan"
    assert bare.plan_subcommand == "links"
    assert bare.plan_links_subcommand == "list"

    validate = parser.parse_args(
        [
            "plan",
            "links",
            "validate",
            "-p",
            "sdd",
            "-j",
            "-q",
            "-W",
        ]
    )
    assert validate.plan_links_subcommand == "validate"
    assert validate.path == "sdd"
    assert validate.json is True
    assert validate.quiet is True
    assert validate.show_warnings is True

    repair = parser.parse_args(["plan", "links", "repair", "-p", "sdd", "-w"])
    assert repair.plan_links_subcommand == "repair"
    assert repair.write is True

    refresh = parser.parse_args(
        [
            "plan",
            "links",
            "refresh",
            "-p",
            "sdd",
            "--plan",
            "plans:202607/example.md",
            "-j",
            "-w",
        ]
    )
    assert refresh.plan_links_subcommand == "refresh"
    assert refresh.path == "sdd"
    assert refresh.plan == "plans:202607/example.md"
    assert refresh.json is True
    assert refresh.write is True


def test_plan_command_dispatches_links() -> None:
    args = create_parser().parse_args(["plan", "links", "list"])

    with (
        patch.object(
            plan_command_handler,
            "handle_plan_links_command",
            side_effect=SystemExit(0),
        ) as links_mock,
        pytest.raises(SystemExit) as excinfo,
    ):
        plan_command_handler.handle_plan_command(args)

    assert excinfo.value.code == 0
    links_mock.assert_called_once_with(args)


def test_repair_ignores_retired_plans_store_prompts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "plans" / "202605" / "prompts" / "fixme.md"
    plan = root / "plans" / "202605" / "fixme.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    plan.write_text("---\nkeep: yes\ntier: epic\n---\n# Epic\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="repair", path=str(root), write=True)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["actions"] == []
    assert payload["changed_files"] == []
    assert prompt.read_text(encoding="utf-8") == "# Prompt\n"
    assert "keep: yes" in plan.read_text(encoding="utf-8")


def test_links_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "sdd"
    plan = root / "plans" / "202605" / "linked.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202605/linked.md](https://example.test/prompt)"
        "\n\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="list", path=str(root), json=True)
        )

    assert excinfo.value.code == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["path"] for row in rows] == ["plans/202605/linked.md"]
    assert rows[0]["target"] == "prompts/202605/linked.md"


def test_links_json_projects_canonical_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo--plans"
    plan = root / "202607" / "linked.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202607/linked.md](https://example.test/prompt)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        handle_plan_links_command(
            make_args(plan_links_subcommand="list", path=str(root), json=True)
        )

    rows = json.loads(capsys.readouterr().out)
    assert [row["target"] for row in rows] == ["prompts/202607/linked.md"]


def test_flat_sidecar_root_validates_archived_prompt_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo--plans"
    plan = root / "202607" / "linked.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202607/linked.md](https://example.test/prompt)"
        "\n\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="validate", path=str(root), json=True)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert [item["path"] for item in payload["files"]] == ["202607/linked.md"]


def test_list_invalid_path_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="list", path=str(missing), json=False)
        )

    assert excinfo.value.code == 1
    assert "does not exist" in capsys.readouterr().err
