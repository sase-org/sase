"""Tests for macro load-issue collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.macro.load_issues import collect_macro_load_issues, record_load_issue
from sase.macro.loader_parsing import parse_macro_entries
from sase.macro.loader_sources import load_macro_from_file
from sase.macro.workflow_loader import _load_workflow_from_file
from sase.macro.workflow_models import WorkflowValidationError


def test_inactive_load_issue_collector_is_noop() -> None:
    record_load_issue("source", "boom", kind="config")


def test_active_collector_records_and_dedupes_by_source_and_error() -> None:
    with collect_macro_load_issues() as issues:
        record_load_issue("source", "boom", kind="config")
        record_load_issue("source", "boom", kind="workflow")
        record_load_issue("source", "other", kind="workflow")

    assert [(issue.source, issue.error, issue.kind) for issue in issues] == [
        ("source", "boom", "config"),
        ("source", "other", "workflow"),
    ]


def test_broken_workflow_yaml_records_issue(tmp_path: Path) -> None:
    workflow_file = tmp_path / "bad.yml"
    workflow_file.write_text("steps:\n  - name: bad\n    bash: [", encoding="utf-8")

    with collect_macro_load_issues() as issues:
        workflow = _load_workflow_from_file(workflow_file)

    assert workflow is None
    assert len(issues) == 1
    assert issues[0].source == str(workflow_file)
    assert "expected" in issues[0].error or "while parsing" in issues[0].error


def test_removed_legacy_agent_family_kind_raises_migration_error(
    tmp_path: Path,
) -> None:
    definition = tmp_path / "legacy_agent_family.yml"
    # legacy agent-family spelling: the removed workflow kind is still detected.
    definition.write_text("kind: agent_family\nroles: {}\n", encoding="utf-8")

    with pytest.raises(
        WorkflowValidationError,
        match=r"kind: agent_family is no longer supported.*%i\(suffix, session=parent\).*LaunchApproval",
    ):
        _load_workflow_from_file(definition)


def test_bad_markdown_frontmatter_records_and_keeps_body_fallback(
    tmp_path: Path,
) -> None:
    macro_file = tmp_path / "review.md"
    macro_file.write_text("---\nname: [\n---\nBody #text", encoding="utf-8")

    with collect_macro_load_issues() as issues:
        macro_def = load_macro_from_file(macro_file)

    assert macro_def is not None
    assert macro_def.name == "review"
    assert macro_def.content == "---\nname: [\n---\nBody #text"
    assert len(issues) == 1
    assert issues[0].source == str(macro_file)
    assert "invalid YAML frontmatter" in issues[0].error


def test_unquoted_yaml_boolean_enum_choice_skips_macro_with_core_message(
    tmp_path: Path,
) -> None:
    macro_file = tmp_path / "bad_enum.md"
    macro_file.write_text(
        "---\n"
        "name: bad_enum\n"
        "input:\n"
        "  mode:\n"
        "    type: enum\n"
        "    choices: [yes, no]\n"
        "---\n"
        "Body\n",
        encoding="utf-8",
    )

    with collect_macro_load_issues() as issues:
        macro_def = load_macro_from_file(macro_file)

    assert macro_def is None
    assert len(issues) == 1
    assert issues[0].kind == "input_type"
    assert "choice arrived as a boolean and must be quoted" in issues[0].error


def test_skipped_config_entries_record_issues() -> None:
    entries = {
        "bad_content": {"content": ["not", "string"]},
        "bad_value": ["not", "mapping"],
    }

    with collect_macro_load_issues() as issues:
        parsed = parse_macro_entries(entries, "config")

    assert parsed == {}
    assert [issue.error for issue in issues] == [
        "skipped macro entry 'bad_content': content must be a string",
        "skipped macro entry 'bad_value': value must be a string or mapping",
    ]
