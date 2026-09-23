"""Tests for tag-aware VCS metadata extraction in agent completion rows."""

from __future__ import annotations

import pytest

from sase.ace.tui._agent_completion_prompt import (
    raw_vcs_tag_for_prompt,
    vcs_workflow_from_prompt,
)


def _tag_catalog() -> object:
    from sase.project_tags import ProjectTagCatalog
    from sase.project_tags.catalog import ProjectTagTarget

    return ProjectTagCatalog(
        targets=(
            ProjectTagTarget(
                key="sase",
                name="sase",
                tag="+sase",
                workflow_type="gh",
                vcs_ref="#gh:sase",
                provider_display="GitHub",
                state="enabled",
            ),
        ),
        accent_palette=(),
    )


def _patch_warm_catalog(
    monkeypatch: pytest.MonkeyPatch, catalog: object | None
) -> None:
    monkeypatch.setattr("sase.project_tags.peek_project_tag_catalog", lambda: catalog)
    if catalog is not None:
        monkeypatch.setattr(
            "sase.project_tags.catalog.load_project_tag_catalog",
            lambda *args, **kwargs: catalog,
        )


def test_workflow_from_tag_prompt_resolves_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_warm_catalog(monkeypatch, _tag_catalog())

    workflow = vcs_workflow_from_prompt("+sase do work")

    assert workflow is not None
    assert workflow.tag == "#gh:sase"
    assert workflow.workflow_type == "gh"
    assert workflow.project == "sase"


def test_raw_tag_for_tag_prompt_returns_canonical_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_warm_catalog(monkeypatch, _tag_catalog())

    assert raw_vcs_tag_for_prompt("+sase do work") == "#gh:sase"


def test_ref_prompts_still_resolve_when_catalog_is_cold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_warm_catalog(monkeypatch, None)

    workflow = vcs_workflow_from_prompt("#gh:sase do work")

    assert workflow is not None
    assert workflow.tag == "#gh:sase"
    assert raw_vcs_tag_for_prompt("#gh:sase do work") == "#gh:sase"


def test_tag_prompt_without_warm_catalog_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_warm_catalog(monkeypatch, None)

    assert vcs_workflow_from_prompt("+sase do work") is None
    assert raw_vcs_tag_for_prompt("+sase do work") == ""
