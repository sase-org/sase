"""Tests for ``sase plan links validate`` handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.plan_links_handler import handle_plan_links_command
from sase.sdd._link_files import list_sdd_files
from sase.sdd.links import validate_sdd_tree
from tests.main.plan_links_handler_helpers import (
    make_args,
    mark_tmp_path_as_project,
)

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


def _write_archived_plan(root: Path, name: str = "linked") -> Path:
    plan = root / "plans" / "202605" / f"{name}.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        f"- **PROMPT:** [prompts/202605/{name}.md]"
        f"(https://github.com/example/project--agents/blob/main/"
        f"prompts/202605/{name}.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )
    return plan


def test_validate_accepts_empty_sidecar_clone_root(tmp_path: Path) -> None:
    root = tmp_path / "sase" / "repos" / "plans"
    (root / ".git").mkdir(parents=True)

    validation = validate_sdd_tree(str(root))

    assert validation.ok
    assert validation.root == root.resolve()


def test_validate_allows_default_unpaired_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    _write_archived_plan(root)
    unpaired = root / "plans" / "202605" / "unpaired.md"
    unpaired.write_text("---\ntier: tale\n---\n# Unpaired plan\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root)))

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "SDD validation passed" in out
    assert "unpaired-file" not in out
    assert "(use --show-warnings to display)" in out


def test_validate_show_warnings_flag_displays_warning_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    unpaired = root / "plans" / "202605" / "unpaired.md"
    unpaired.parent.mkdir(parents=True)
    unpaired.write_text("---\ntier: tale\n---\n# Unpaired plan\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), show_warnings=True))

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "unpaired-file" in out
    assert "(use --show-warnings to display)" not in out


def test_validate_default_uses_configured_separate_repo_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: separate_repo\n", encoding="utf-8"
    )
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    _write_archived_plan(tmp_path / ".sase" / "sdd")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=None))

    assert excinfo.value.code == 0
    assert "SDD validation passed: 1 files" in capsys.readouterr().out


def test_validate_strict_fails_unpaired_plan(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    plan = root / "plans" / "202605" / "legacy.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntier: tale\n---\n# Plan\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), strict=True, quiet=True))

    assert excinfo.value.code == 1


def test_validate_passing_run_prints_no_repair_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    _write_archived_plan(root)

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root)))

    assert excinfo.value.code == 0
    out, err = capsys.readouterr()
    assert "SDD validation passed" in out
    assert "sase plan links repair --write" not in out + err


def test_validate_reports_broken_relative_prompt_target(tmp_path: Path) -> None:
    root = tmp_path / "repo--plans"
    plan = root / "202607" / "broken.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202607/broken.md](prompts/broken.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    issue = next(
        issue for issue in validation.errors if issue.code == "link-missing-target"
    )
    assert "prompts/broken.md" in issue.message


def test_validate_accepts_external_prompt_target_and_marks_plan_paired(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo--plans"
    _write_archived_plan(root, "external")

    validation = validate_sdd_tree(str(root))

    assert validation.ok
    assert not any(issue.code == "unpaired-file" for issue in validation.issues)
    assert not any(issue.code == "link-missing-target" for issue in validation.issues)


@pytest.mark.parametrize(
    "relative",
    (
        "202608/prompts/legacy.md",
        "plans/202608/prompts/legacy.md",
        "prompts/202608/legacy.md",
        "specs/202608/legacy.md",
    ),
)
def test_validate_errors_for_prompt_remaining_in_plans_store(
    tmp_path: Path,
    relative: str,
) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / relative
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Historical prompt\n", encoding="utf-8")

    validation = validate_sdd_tree(str(root))

    assert not validation.ok
    assert [issue.code for issue in validation.errors] == ["prompt-in-plans-store"]
    assert list_sdd_files(root, kind="all") == []


def test_validate_reports_unresolvable_parent_section(tmp_path: Path) -> None:
    root = tmp_path / "repo--plans"
    plan = root / "202607" / "child.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202607/child.md](https://example.test/child)\n"
        "- **PARENT:** [202607/missing.md](missing.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert any(issue.code == "parent-missing-target" for issue in validation.errors)


def test_validate_reports_invalid_plan_frontmatter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    path = root / "plans" / "202605" / "bad.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntier: [unterminated\n---\n# Bad\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "frontmatter-parse"
