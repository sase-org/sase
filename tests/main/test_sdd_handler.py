"""Tests for the ``sase sdd`` parser, handler, and link repair commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.sdd_handler import handle_sdd_command


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "sdd_subcommand": "validate",
        "path": None,
        "json": False,
        "quiet": False,
        "strict": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _write_pair(root: Path, name: str = "linked") -> tuple[Path, Path]:
    prompt = root / "prompts" / "202605" / f"{name}.md"
    plan = root / "tales" / "202605" / f"{name}.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(
        f"---\nplan: sdd/tales/202605/{name}.md\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        f"---\nprompt: sdd/prompts/202605/{name}.md\n---\n# Plan\n",
        encoding="utf-8",
    )
    return prompt, plan


def test_parser_registers_sdd_subcommands() -> None:
    parser = create_parser()

    args = parser.parse_args(["sdd", "validate", "-p", "sdd", "-j", "-q", "--strict"])
    assert args.command == "sdd"
    assert args.sdd_subcommand == "validate"
    assert args.path == "sdd"
    assert args.json is True
    assert args.quiet is True
    assert args.strict is True

    args = parser.parse_args(["sdd", "list", "-p", "sdd", "-k", "prompts", "-j"])
    assert args.sdd_subcommand == "list"
    assert args.kind == "prompts"

    args = parser.parse_args(["sdd", "list", "-p", "sdd", "-k", "tales"])
    assert args.kind == "tales"

    args = parser.parse_args(["sdd", "repair-links", "-p", "sdd", "-w"])
    assert args.write is True


def test_validate_allows_default_unpaired_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    _write_pair(root)
    unpaired = root / "tales" / "202605" / "legacy.md"
    unpaired.parent.mkdir(parents=True, exist_ok=True)
    unpaired.write_text("# Legacy plan\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root)))

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "SDD validation passed" in out
    assert "unpaired-file" in out


def test_validate_strict_fails_unpaired_warnings(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    (root / "prompts" / "202605").mkdir(parents=True)
    (root / "prompts" / "202605" / "legacy.md").write_text(
        "# Legacy prompt\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), strict=True, quiet=True))

    assert excinfo.value.code == 1


def test_validate_fails_broken_bidirectional_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt, plan = _write_pair(root)
    plan.write_text(
        "---\nprompt: sdd/prompts/202605/other.md\n---\n# Plan\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(error["code"] == "link-missing-target" for error in payload["errors"])
    assert prompt.exists()


def test_validate_reports_invalid_yaml_frontmatter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nplan: [unterminated\n---\n# Bad\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "frontmatter-parse"


def test_repair_links_write_backfills_unambiguous_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "prompts" / "202605" / "fixme.md"
    plan = root / "epics" / "202605" / "fixme.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    plan.write_text("---\nkeep: yes\n---\n# Epic\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            _args(sdd_subcommand="repair-links", path=str(root), write=True)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {action["field"] for action in payload["actions"]} == {"plan", "prompt"}
    assert payload["changed_files"] == [
        "epics/202605/fixme.md",
        "prompts/202605/fixme.md",
    ]
    assert "plan: sdd/epics/202605/fixme.md" in prompt.read_text(encoding="utf-8")
    plan_text = plan.read_text(encoding="utf-8")
    assert "keep: true" in plan_text
    assert "prompt: sdd/prompts/202605/fixme.md" in plan_text


def test_links_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "sdd"
    _write_pair(root)

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(sdd_subcommand="links", path=str(root), json=True))

    assert excinfo.value.code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["path"] for row in rows} == {
        "tales/202605/linked.md",
        "prompts/202605/linked.md",
    }
    assert all(row["bidirectional"] for row in rows)


def test_validate_resolves_legacy_plans_link_to_canonical_tales(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "prompts" / "202605" / "linked.md"
    plan = root / "tales" / "202605" / "linked.md"
    prompt.parent.mkdir(parents=True)
    plan.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: sdd/plans/202605/linked.md\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\nprompt: sdd/prompts/202605/linked.md\n---\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), quiet=True))

    assert excinfo.value.code == 0


def test_list_invalid_path_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            _args(sdd_subcommand="list", path=str(missing), kind="all", json=False)
        )

    assert excinfo.value.code == 1
    assert "does not exist" in capsys.readouterr().err
