"""Tests for prompt-history metadata extraction."""

from __future__ import annotations

import pytest

import sase.history.prompt_metadata as prompt_metadata
import sase.xprompt._parsing as xprompt_parsing
from sase.history.prompt_metadata import (
    clean_prompt_preview,
    summarize_prompt_for_list,
    summarize_prompt_for_preview,
    summarize_prompt_for_search,
)


@pytest.fixture(autouse=True)
def _workflow_names(monkeypatch: pytest.MonkeyPatch):
    workflow_names = {"cd", "git"}
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: workflow_names,
    )
    monkeypatch.setattr(
        "sase.workspace_provider._registry.get_workflow_names",
        lambda: workflow_names,
    )
    prompt_metadata.known_workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    prompt_metadata.known_workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None


def test_summarize_prompt_for_list_extracts_columns_and_clean_preview() -> None:
    summary = summarize_prompt_for_list(
        "%id\n%m:opus #gh:steveyegge/beads #fork:agent #research Fix parser"
    )

    assert summary.project_prefix == "gh:"
    assert summary.project_ref_display == "beads"
    assert summary.xprompts == ("#fork", "#research")
    assert summary.directive_token == "%mi"
    assert summary.clean_preview == "Fix parser"


def test_summarize_prompt_for_list_handles_missing_project() -> None:
    summary = summarize_prompt_for_list("#research Investigate history metadata")

    assert summary.project_prefix == ""
    assert summary.project_ref_display == ""
    assert summary.xprompts == ("#research",)
    assert summary.clean_preview == "Investigate history metadata"


def test_summarize_prompt_for_list_uses_underscore_vcs_basename() -> None:
    summary = summarize_prompt_for_list("#gh_steveyegge/beads Fix parser")

    assert summary.project_prefix == "gh:"
    assert summary.project_ref_display == "beads"
    assert summary.xprompts == ()
    assert summary.clean_preview == "Fix parser"


def test_summarize_prompt_for_search_keeps_preview_when_workflows_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_workflows() -> frozenset[str]:
        raise RuntimeError("workflow metadata unavailable")

    monkeypatch.setattr("sase.workspace_provider.get_workflow_names", fail_workflows)
    prompt_metadata.known_workflow_names.cache_clear()

    summary = summarize_prompt_for_search("#research Investigate history metadata")

    assert summary.clean_preview == "Investigate history metadata"
    assert summary.xprompts == ()


def test_summarize_prompt_for_search_skips_literal_scan_without_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_scan(text: str, blocks: list[str]) -> str:
        raise AssertionError("plain search metadata should not protect literal zones")

    monkeypatch.setattr(prompt_metadata, "protect_fenced_blocks", fail_scan)

    summary = summarize_prompt_for_search(
        "Plain searchable title\n"
        "```python\n"
        "# a code comment is not an xprompt reference\n"
        "```\n"
    )

    assert summary.clean_preview == "Plain searchable title"
    assert summary.xprompts == ()


def test_clean_prompt_preview_ignores_control_tokens_inside_fences() -> None:
    prompt = "Show this:\n```\n#fork %id\n```\nThen #fork %id"

    summary = summarize_prompt_for_list(prompt)

    assert summary.xprompts == ("#fork",)
    assert summary.directive_token == "%i"
    assert summary.clean_preview == "Show this:"


def test_clean_prompt_preview_returns_empty_for_control_only_prompt() -> None:
    assert clean_prompt_preview("#gh:sase #fork %id") == ""


@pytest.mark.parametrize("directive", ["%name:legacy", "%n:legacy"])
def test_history_metadata_tolerates_deprecated_name_directives(
    directive: str,
) -> None:
    summary = summarize_prompt_for_list(f"{directive} #gh:sase Fix parser")

    assert summary.directive_token == "%n"
    assert summary.clean_preview == "Fix parser"


def test_summarize_prompt_for_preview_preserves_verbose_metadata() -> None:
    summary = summarize_prompt_for_preview(
        "%model:opus #gh:steveyegge/beads #fork(prev) #research:topic Fix"
    )

    assert summary.vcs_tag == "#gh:steveyegge/beads "
    assert summary.xprompts == ("#fork(prev)", "#research:topic")
    assert summary.directives == ("%model:opus",)


def test_effort_e_alias_is_summarized_as_effort() -> None:
    """A ``%e:`` span is recognized as the canonical ``%effort`` directive."""
    preview = summarize_prompt_for_preview("%e:xhigh\nReview the diff")
    assert preview.directives == ("%effort:xhigh",)

    list_summary = summarize_prompt_for_list("%e:xhigh Review the diff")
    assert list_summary.directive_token == "%e"
    assert list_summary.clean_preview == "Review the diff"


def test_auto_directive_is_summarized() -> None:
    """%auto is summarized as directive metadata."""
    summary = summarize_prompt_for_preview(
        "%auto %model:opus #gh:steveyegge/beads Fix parser"
    )

    assert summary.vcs_tag == "#gh:steveyegge/beads "
    assert summary.directives == ("%auto", "%model:opus")

    list_summary = summarize_prompt_for_list("%auto %model:opus #gh:sase Fix parser")
    assert list_summary.directive_token == "%ma"
