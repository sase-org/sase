"""Tests for ``sase sdd`` link repair, link listing, and file listing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.sdd_handler import handle_sdd_command
from tests.main.sdd_handler_helpers import (
    make_args,
    mark_tmp_path_as_project,
    write_pair,
)

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


def test_repair_links_write_backfills_unambiguous_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "prompts" / "202605" / "fixme.md"
    plan = root / "plans" / "202605" / "fixme.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    plan.write_text("---\nkeep: yes\ntier: epic\n---\n# Epic\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="repair-links", path=str(root), write=True)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {action["field"] for action in payload["actions"]} == {"plan", "prompt"}
    assert payload["changed_files"] == [
        "plans/202605/fixme.md",
        "prompts/202605/fixme.md",
    ]
    assert "plan: sdd/plans/202605/fixme.md" in prompt.read_text(encoding="utf-8")
    plan_text = plan.read_text(encoding="utf-8")
    assert "keep: true" in plan_text
    assert "prompt: sdd/prompts/202605/fixme.md" in plan_text


def test_links_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "sdd"
    write_pair(root)

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="links", path=str(root), json=True))

    assert excinfo.value.code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["path"] for row in rows} == {
        "plans/202605/linked.md",
        "prompts/202605/linked.md",
    }
    assert all(row["bidirectional"] for row in rows)


def test_list_default_uses_configured_separate_repo_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: separate_repo\n", encoding="utf-8"
    )
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    root = tmp_path / ".sase" / "sdd"
    write_pair(root)

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="list", path=None, kind="tales", json=False)
        )

    assert excinfo.value.code == 0
    assert capsys.readouterr().out == "tales\tplans/202605/linked.md\n"


def test_list_invalid_path_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="list", path=str(missing), kind="all", json=False)
        )

    assert excinfo.value.code == 1
    assert "does not exist" in capsys.readouterr().err
