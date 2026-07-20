"""Tests for shared prompt-stash preview rendering."""

from __future__ import annotations

from sase.ace.tui.modals._prompt_stash_preview import (
    _build_prompt_stash_frontmatter,
    _build_prompt_stash_metadata,
    _build_prompt_stash_preview,
)
from sase.core.prompt_stash_wire import PromptStashEntryWire
from tests._project_display_case import ProjectDisplayCase


def _entry(**overrides: object) -> PromptStashEntryWire:
    values: dict[str, object] = {
        "id": "stash-1",
        "created_at": "2026-06-16T10:00:00",
        "text": "#review %wait:planner",
        "frontmatter": "---\nxprompts:\n  helper: Do work\n---",
        "project": "sase",
        "source": "all",
        "pinned": True,
    }
    values.update(overrides)
    return PromptStashEntryWire(**values)  # type: ignore[arg-type]


def test_preview_includes_frontmatter_body_and_metadata() -> None:
    preview = _build_prompt_stash_preview(_entry(), prompt_count=3)

    assert preview.frontmatter is not None
    assert "xprompts:" in preview.frontmatter.plain
    assert preview.body.plain == "#review %wait:planner"
    assert "Project:    sase" in preview.metadata.plain
    assert "Workflows:  #review" in preview.metadata.plain
    assert "Directives: %wait:planner" in preview.metadata.plain
    assert "Prompts:    3" in preview.metadata.plain
    assert "Pinned:     yes" in preview.metadata.plain
    assert "Source:     all" in preview.metadata.plain


def test_frontmatter_is_absent_when_stash_has_none() -> None:
    assert _build_prompt_stash_frontmatter("") is None


def test_metadata_uses_placeholders_and_omits_single_prompt_count() -> None:
    metadata = _build_prompt_stash_metadata(
        _entry(text="plain", frontmatter="", project=None, source="", pinned=False),
        prompt_count=1,
    ).plain

    assert "Project:    —" in metadata
    assert "Source:     —" in metadata
    assert "Pinned:     no" in metadata
    assert "Prompts:" not in metadata


def test_metadata_projects_canonical_project_from_supplied_snapshot(
    project_display_case: ProjectDisplayCase,
) -> None:
    canonical = project_display_case.project_key
    entry = _entry(project=canonical)

    metadata = _build_prompt_stash_metadata(
        entry,
        prompt_count=1,
        project_display_snapshot=project_display_case.snapshot,
    ).plain

    assert f"Project:    {project_display_case.project_label}" in metadata
    assert canonical not in metadata
    assert entry.project == canonical
