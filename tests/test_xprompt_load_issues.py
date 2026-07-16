"""Tests for xprompt load-issue collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.xprompt.load_issues import collect_xprompt_load_issues, record_load_issue
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.loader_sources import load_xprompt_from_file
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_models import WorkflowValidationError


def test_inactive_load_issue_collector_is_noop() -> None:
    record_load_issue("source", "boom", kind="config")


def test_active_collector_records_and_dedupes_by_source_and_error() -> None:
    with collect_xprompt_load_issues() as issues:
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

    with collect_xprompt_load_issues() as issues:
        workflow = _load_workflow_from_file(workflow_file)

    assert workflow is None
    assert len(issues) == 1
    assert issues[0].source == str(workflow_file)
    assert "expected" in issues[0].error or "while parsing" in issues[0].error


def test_removed_agent_family_kind_raises_migration_error(tmp_path: Path) -> None:
    definition = tmp_path / "family.yml"
    definition.write_text("kind: agent_family\nroles: {}\n", encoding="utf-8")

    with pytest.raises(
        WorkflowValidationError,
        match=r"no longer supported.*%n\(parent, suffix\).*LaunchApproval",
    ):
        _load_workflow_from_file(definition)


def test_bad_markdown_frontmatter_records_and_keeps_body_fallback(
    tmp_path: Path,
) -> None:
    xprompt_file = tmp_path / "review.md"
    xprompt_file.write_text("---\nname: [\n---\nBody #text", encoding="utf-8")

    with collect_xprompt_load_issues() as issues:
        xprompt = load_xprompt_from_file(xprompt_file)

    assert xprompt is not None
    assert xprompt.name == "review"
    assert xprompt.content == "---\nname: [\n---\nBody #text"
    assert len(issues) == 1
    assert issues[0].source == str(xprompt_file)
    assert "invalid YAML frontmatter" in issues[0].error


def test_skipped_config_entries_record_issues() -> None:
    entries = {
        "bad_content": {"content": ["not", "string"]},
        "bad_value": ["not", "mapping"],
    }

    with collect_xprompt_load_issues() as issues:
        parsed = parse_xprompt_entries(entries, "config")

    assert parsed == {}
    assert [issue.error for issue in issues] == [
        "skipped xprompt entry 'bad_content': content must be a string",
        "skipped xprompt entry 'bad_value': value must be a string or mapping",
    ]
