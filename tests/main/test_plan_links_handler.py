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
    write_pair,
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
            "--strict",
            "-W",
        ]
    )
    assert validate.plan_links_subcommand == "validate"
    assert validate.path == "sdd"
    assert validate.json is True
    assert validate.quiet is True
    assert validate.strict is True
    assert validate.show_warnings is True

    repair = parser.parse_args(["plan", "links", "repair", "-p", "sdd", "-w"])
    assert repair.plan_links_subcommand == "repair"
    assert repair.write is True


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


def test_repair_links_write_backfills_unambiguous_pair(
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
    assert {action["field"] for action in payload["actions"]} == {"plan", "prompt"}
    assert payload["changed_files"] == [
        "plans/202605/fixme.md",
        "plans/202605/prompts/fixme.md",
    ]
    assert "plan: '[../sdd/plans/202605/fixme.md](../fixme.md)'" in prompt.read_text(
        encoding="utf-8"
    )
    plan_text = plan.read_text(encoding="utf-8")
    assert "keep: true" in plan_text
    assert (
        "prompt: '[sdd/plans/202605/prompts/fixme.md](prompts/fixme.md)'" in plan_text
    )
    assert plan_text.endswith("---\n# Epic\n")
    assert prompt.read_text(encoding="utf-8").endswith("---\n# Prompt\n")

    second = make_args(plan_links_subcommand="repair", path=str(root), write=True)
    with pytest.raises(SystemExit) as second_excinfo:
        handle_plan_links_command(second)
    assert second_excinfo.value.code == 0
    second_payload = json.loads(capsys.readouterr().out)
    assert second_payload["actions"] == []
    assert second_payload["changed_files"] == []


def test_repair_dry_run_reports_legacy_links_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt, plan = write_pair(root)
    before = {
        prompt: prompt.read_text(encoding="utf-8"),
        plan: plan.read_text(encoding="utf-8"),
    }

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="repair", path=str(root), write=False)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {action["field"] for action in payload["actions"]} == {
        "plan",
        "prompt",
    }
    assert payload["changed_files"] == []
    assert {path: path.read_text(encoding="utf-8") for path in before} == before


def test_links_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "sdd"
    write_pair(root)

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="list", path=str(root), json=True)
        )

    assert excinfo.value.code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["path"] for row in rows} == {
        "plans/202605/linked.md",
        "plans/202605/prompts/linked.md",
    }
    assert all(row["bidirectional"] for row in rows)


def test_links_json_projects_canonical_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "linked.md"
    plan = root / "202607" / "linked.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: '[../202607/linked.md](../linked.md)'\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\nprompt: '[202607/prompts/linked.md](prompts/linked.md)'\n"
        "tier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        handle_plan_links_command(
            make_args(plan_links_subcommand="list", path=str(root), json=True)
        )

    rows = json.loads(capsys.readouterr().out)
    assert {row["target"] for row in rows} == {
        "../202607/linked.md",
        "202607/prompts/linked.md",
    }
    assert all(row["bidirectional"] for row in rows)


def test_flat_sidecar_root_validates_plan_pairs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "linked.md"
    plan = root / "202607" / "linked.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("---\nplan: 202607/linked.md\n---\n# Prompt\n", encoding="utf-8")
    plan.write_text(
        "---\nprompt: 202607/prompts/linked.md\ntier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(
            make_args(plan_links_subcommand="validate", path=str(root), json=True)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert {item["path"] for item in payload["files"]} == {
        "202607/linked.md",
        "202607/prompts/linked.md",
    }


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
