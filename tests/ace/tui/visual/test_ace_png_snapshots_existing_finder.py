"""PNG snapshots for the existing macro and snippet definition finder."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.existing_definition_entries import (
    macro_existing_entries,
    snippet_existing_entries,
)
from sase.ace.tui.modals.existing_definition_finder_modal import (
    ExistingDefinitionFinderModal,
)
from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroTargetCatalog,
)
from sase.snippet.redefinition import SnippetDefinitionSite
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _macro(
    name: str,
    path: str,
    *,
    compatibility: str = "editable",
    effective: bool = True,
    precedence: int = 0,
    workflow_kind: str = "macro",
    shadowed_by: str | None = None,
) -> MiniMacroDefinition:
    return MiniMacroDefinition(
        name=name,
        workflow_kind=workflow_kind,  # type: ignore[arg-type]
        source_path=path,
        display_path=path,
        storage_format=None,
        entry_name=None,
        location_path=path,
        precedence=precedence,
        compatibility=compatibility,  # type: ignore[arg-type]
        origin_label=("read-only" if compatibility == "read_only" else None),
        incompatible_reason=(
            "skills must be edited from their source"
            if workflow_kind == "skill"
            else "macro swarms cannot be opened as mini targets"
            if compatibility == "incompatible"
            else None
        ),
        effective=effective,
        shadowed_by=shadowed_by,
    )


def _macro_entries():
    catalog = MiniMacroTargetCatalog(
        definitions=(
            _macro("review", "./sase/macros/review.md"),
            _macro(
                "review",
                "~/sase/macros/review.md",
                effective=False,
                precedence=10,
                shadowed_by="./sase/macros/review.md",
            ),
            _macro(
                "review_pr",
                "sase/default_macros/review_pr.md",
                compatibility="read_only",
                effective=False,
            ),
            _macro(
                "review_plugin",
                "plugins/sase_github/macros/review_plugin.md",
                compatibility="read_only",
                effective=False,
            ),
            _macro(
                "review_skill",
                "sase/skills/review_skill.md",
                compatibility="incompatible",
                effective=False,
                workflow_kind="skill",
            ),
            _macro(
                "review_swarm",
                "./sase/macros/review_swarm.md",
                compatibility="incompatible",
                effective=False,
            ),
        ),
        destinations=(),
    )
    return macro_existing_entries(catalog)


def _snippet_entries():
    return snippet_existing_entries(
        (
            SnippetDefinitionSite(
                trigger="todo",
                kind="user",
                path="~/.config/sase/sase.yml",
                display="~/.config/sase/sase.yml",
                template="TODO: {{ input }}",
                writable=True,
                active=False,
                shadowed_by="./sase/sase.yml",
                layer="user",
            ),
            SnippetDefinitionSite(
                trigger="todo",
                kind="project",
                path="./sase/sase.yml",
                display="./sase/sase.yml",
                template="Project TODO: {{ input }}",
                writable=True,
                active=True,
                shadowed_by=None,
                layer="project",
            ),
            SnippetDefinitionSite(
                trigger="tab",
                kind="default",
                path=None,
                display="built-in default_config.yml",
                template="Built-in snippet body",
                writable=False,
                active=True,
                shadowed_by=None,
                layer="default",
            ),
            SnippetDefinitionSite(
                trigger="gh",
                kind="plugin",
                path="plugins/sase_github/default_config.yml",
                display="plugin sase_github",
                template="GitHub snippet body",
                writable=False,
                active=True,
                shadowed_by=None,
                layer="plugin:sase_github",
            ),
            SnippetDefinitionSite(
                trigger="review",
                kind="macro",
                path=None,
                display="#review (macro snippet)",
                template="From the review macro",
                writable=False,
                active=True,
                shadowed_by=None,
                macro_name="review",
            ),
        )
    )


async def _open_finder(page: AcePage, modal: ExistingDefinitionFinderModal) -> None:
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    page.app.push_screen(modal)
    await page.expect_modal("ExistingDefinitionFinderModal")


async def test_existing_macro_finder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = ExistingDefinitionFinderModal(
        "macro",
        _macro_entries(),
        initial_query="rev",
        preview_loader=lambda _entry_id: (
            "---\ninput: review\n---\n\nReview this carefully."
        ),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_finder(page, modal)
        await wait_for_svg_contains(page, "Edit existing macro")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "existing_finder_macro_120x40",
            title="ACE existing-definition finder — macro statuses",
        )


async def test_existing_snippet_finder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = ExistingDefinitionFinderModal(
        "snippet", _snippet_entries(), initial_query="todo"
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_finder(page, modal)
        await wait_for_svg_contains(page, "TODO")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "existing_finder_snippet_120x40",
            title="ACE existing-definition finder — snippets",
        )


async def test_existing_finder_empty_match_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = ExistingDefinitionFinderModal(
        "macro", _macro_entries(), initial_query="zzzz"
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_finder(page, modal)
        await wait_for_svg_contains(page, "No macros match")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "existing_finder_macro_empty_match_120x40",
            title="ACE existing-definition finder — empty match",
        )
