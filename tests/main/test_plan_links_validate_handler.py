"""Tests for ``sase plan links validate`` handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.plan_links_handler import handle_plan_links_command
from sase.sdd.links import validate_sdd_tree
from tests.main.plan_links_handler_helpers import (
    make_args,
    mark_tmp_path_as_project,
    write_pair,
)

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


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
    write_pair(root)
    unpaired = root / "plans" / "202605" / "unpaired.md"
    unpaired.parent.mkdir(parents=True, exist_ok=True)
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
    write_pair(root)
    unpaired = root / "plans" / "202605" / "unpaired.md"
    unpaired.parent.mkdir(parents=True, exist_ok=True)
    unpaired.write_text("---\ntier: tale\n---\n# Unpaired plan\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), show_warnings=True))

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "SDD validation passed" in out
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
    write_pair(tmp_path / ".sase" / "sdd")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=None))

    assert excinfo.value.code == 0
    assert "SDD validation passed: 2 files" in capsys.readouterr().out


def test_validate_strict_fails_unpaired_warnings(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    (root / "prompts" / "202605").mkdir(parents=True)
    (root / "prompts" / "202605" / "legacy.md").write_text(
        "# Legacy prompt\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), strict=True, quiet=True))

    assert excinfo.value.code == 1


def test_validate_fails_broken_bidirectional_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt, plan = write_pair(root)
    plan.write_text(
        "---\nprompt: sdd/plans/202605/prompts/other.md\ntier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(error["code"] == "link-missing-target" for error in payload["errors"])
    assert prompt.exists()


def test_validate_accepts_both_legacy_frontmatter_encodings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "mixed.md"
    plan = root / "202607" / "mixed.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: '[../202607/mixed.md](../mixed.md)'\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\nprompt: 202607/prompts/mixed.md\ntier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert validation.ok
    assert validation.errors == []


def test_validate_reports_broken_canonical_href(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "broken.md"
    plan = root / "202607" / "broken.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "- **PLAN:** [../202607/broken.md](../missing.md)\n\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202607/prompts/broken.md](prompts/broken.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert not validation.ok
    issue = next(
        issue for issue in validation.errors if issue.code == "link-missing-target"
    )
    assert "../missing.md" in issue.message


def test_validate_reports_unresolvable_parent_section(tmp_path: Path) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "child.md"
    plan = root / "202607" / "child.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "- **PLAN:** [../202607/child.md](../child.md)\n\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202607/prompts/child.md](prompts/child.md)\n"
        "- **PARENT:** [202607/missing.md](missing.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert any(issue.code == "parent-missing-target" for issue in validation.errors)


def test_validate_rejects_malformed_markdown_like_link(tmp_path: Path) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "malformed.md"
    plan = root / "202607" / "malformed.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "- **PLAN:** [../202607/malformed.md] ../malformed.md\n\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\nprompt: 202607/prompts/malformed.md\ntier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert any(issue.code == "link-format" for issue in validation.errors)


def test_validate_accepts_redundant_mixed_transition(tmp_path: Path) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "mixed.md"
    plan = root / "202607" / "mixed.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: 202607/mixed.md\n---\n\n"
        "- **PLAN:** [../202607/mixed.md](../mixed.md)\n\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202607/prompts/mixed.md](prompts/mixed.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert validation.ok
    assert validation.errors == []


def test_validate_rejects_conflicting_mixed_representations(tmp_path: Path) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "mixed.md"
    plan = root / "202607" / "mixed.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: 202607/other.md\n---\n\n"
        "- **PLAN:** [../202607/mixed.md](../mixed.md)\n\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202607/prompts/mixed.md](prompts/mixed.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert any(issue.code == "link-conflict" for issue in validation.errors)


@pytest.mark.parametrize(
    ("prompt_content", "code"),
    [
        (
            "- **PLAN:** [../202607/invalid.md](../invalid.md)\n"
            "- **PLAN:** [../202607/invalid.md](../invalid.md)\n\n# Prompt\n",
            "link-format",
        ),
        (
            "- **PROMPT:** [202607/prompts/invalid.md](invalid.md)\n\n# Prompt\n",
            "link-kind",
        ),
        (
            "# Prompt\n\n- **PLAN:** [../202607/invalid.md](../invalid.md)\n",
            "link-placement",
        ),
    ],
)
def test_validate_rejects_duplicate_wrong_kind_and_misplaced_bullets(
    tmp_path: Path, prompt_content: str, code: str
) -> None:
    root = tmp_path / "repo--plans"
    prompt = root / "202607" / "prompts" / "invalid.md"
    plan = root / "202607" / "invalid.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(prompt_content, encoding="utf-8")
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202607/prompts/invalid.md](prompts/invalid.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    validation = validate_sdd_tree(str(root))

    assert any(issue.code == code for issue in validation.errors)


def test_validate_reports_invalid_yaml_frontmatter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nplan: [unterminated\n---\n# Bad\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "frontmatter-parse"


def test_validate_downgrades_allowlisted_legacy_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.sdd.links as links

    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "legacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nplan: sdd/plans/202605/missing.md\n---\n# Legacy prompt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        links,
        "LEGACY_INVALID_SDD_ERROR_ALLOWLIST",
        frozenset({"prompts/202605/legacy.md"}),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), json=True))

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == []
    assert payload["warnings"] == [
        {
            "severity": "warning",
            "code": "link-missing-target-legacy-allowed",
            "path": "prompts/202605/legacy.md",
            "message": "'plan' target does not exist: "
            "sdd/plans/202605/missing.md; "
            "legacy SDD validation error allowlisted",
        }
    ]


@pytest.mark.parametrize(
    "name",
    [
        "recover_uncommitted_audit_work_1.md",
        "sase_mobile_mvp_legend.md",
    ],
)
def test_validate_quarantines_retired_legend_prompt_links(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    root = tmp_path / "sdd"
    path = root / "plans" / "202605" / "prompts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nplan: sdd/legends/202605/{name}\n---\n# Legacy prompt\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), json=True))

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"] == []
    assert payload["warnings"][0]["code"] == ("link-missing-target-legacy-allowed")


def test_validate_does_not_allowlist_other_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.sdd.links as links

    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "new.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nplan: sdd/plans/202605/missing.md\n---\n# New prompt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        links,
        "LEGACY_INVALID_SDD_ERROR_ALLOWLIST",
        frozenset({"prompts/202605/legacy.md"}),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "link-missing-target"
    assert payload["warnings"] == []


def test_validate_does_not_resolve_legacy_plan_link_to_canonical_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "prompts" / "202605" / "linked.md"
    plan = root / "plans" / "202605" / "linked.md"
    prompt.parent.mkdir(parents=True)
    plan.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: sdd/tales/202605/linked.md\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\nprompt: sdd/prompts/202605/linked.md\ntier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_plan_links_command(make_args(path=str(root), quiet=True))

    assert excinfo.value.code == 1
    assert "target does not exist" in capsys.readouterr().err
