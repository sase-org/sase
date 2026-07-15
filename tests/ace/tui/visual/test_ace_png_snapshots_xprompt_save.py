"""PNG snapshots for the unified xprompt/snippet save panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.unified_xprompt_save_modal import (
    UnifiedSaveLocation,
    UnifiedXPromptSaveModal,
)
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _location(
    label: str,
    path: str,
    group: str,
    *,
    names: frozenset[str] = frozenset(),
    location_type: str = "directory",
    precedence: int = 0,
    disabled_reason: str | None = None,
    will_create: bool = False,
    builtin: bool = False,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=XPromptLocation(label, path, location_type),  # type: ignore[arg-type]
        group=group,
        display_path=path,
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        will_create=will_create,
        builtin=builtin,
    )


def _xprompt_rows() -> list[UnifiedSaveLocation]:
    return [
        _location(
            "Project (sase)",
            "~/.config/sase/xprompts/sase",
            "Project",
            names=frozenset({"commit", "propose", "review"}),
        ),
        _location(
            "CWD .xprompts/",
            "./.xprompts",
            "CWD directories",
            names=frozenset({"lint", "test"}),
            precedence=1,
            will_create=True,
        ),
        _location(
            "Home ~/.xprompts/",
            "~/.xprompts",
            "Home directories",
            names=frozenset({"daily", "review"}),
            precedence=2,
        ),
        _location(
            "User sase.yml",
            "~/.config/sase/sase.yml",
            "Config files",
            names=frozenset({"plan", "review"}),
            location_type="config",
            precedence=10,
        ),
        _location(
            "Built-in xprompts/",
            "/opt/sase/xprompts",
            "Built-in (dev)",
            names=frozenset({"commit", "propose", "pr", "sync"}),
            precedence=50,
            builtin=True,
        ),
    ]


def _snippet_rows() -> list[UnifiedSaveLocation]:
    return [
        _location(
            "User sase.yml",
            "~/.config/sase/sase.yml",
            "Config files",
            names=frozenset({"sig", "todo"}),
            location_type="config",
        ),
        _location(
            "Local sase.yml",
            "./sase.yml",
            "Config files",
            names=frozenset({"fix"}),
            location_type="config",
            precedence=1,
        ),
    ]


async def _open(page: AcePage, modal: UnifiedXPromptSaveModal) -> None:
    page.app.push_screen(modal)
    await page.expect_modal("UnifiedXPromptSaveModal")
    await wait_for_svg_contains(page, "Destination")
    name = modal.query_one("#unified-save-name")
    await wait_for_state(
        page,
        lambda: name.has_focus and not modal._preview_tasks,
        description="xprompt save name focus and preview load",
    )
    await wait_for_visual_idle(page)


async def test_xprompt_save_create_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = UnifiedXPromptSaveModal(
        _xprompt_rows(),
        snippet_locations=_snippet_rows(),
        initial_name="code_review_swarm",
        frontmatter=PromptFrontmatter(tags=["review"]),
        body="Check correctness, tests, and maintainability.",
        snippet_body="Check the selected concern.",
        pane_count=3,
    )
    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open(page, modal)
        ace_png_visual.assert_page_png(
            page,
            "xprompt_save_create_120x40",
            title="ACE unified xprompt save create verdict",
        )


async def test_xprompt_save_collision_armed_diff_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.unified_xprompt_save_modal.load_definition",
        lambda *_args: "---\ndescription: Old review prompt\n---\n\nOld checklist\n",
    )
    modal = UnifiedXPromptSaveModal(
        _xprompt_rows(),
        snippet_locations=_snippet_rows(),
        initial_name="review",
        frontmatter=PromptFrontmatter(description="Review the draft carefully"),
        body="New review checklist\n\n- correctness\n- tests\n- clarity",
        snippet_body="Review this pane",
        pane_count=2,
    )
    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open(page, modal)
        identity = modal._identity()
        assert identity is not None
        modal._existing_cache[identity] = (
            "---\ndescription: Old review prompt\n---\n\nOld checklist\n"
        )
        modal.action_save()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "xprompt_save_collision_armed_diff_120x40",
            title="ACE unified xprompt save armed overwrite diff",
        )


async def test_xprompt_save_snippet_mode_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = UnifiedXPromptSaveModal(
        _xprompt_rows(),
        snippet_locations=_snippet_rows(),
        initial_name="review",
        body="Pane one\n---\nPane two\n---\nPane three",
        snippet_body="Review only the selected pane$0",
        pane_count=3,
    )
    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open(page, modal)
        modal.action_toggle_mode()
        modal.query_one("#unified-save-name").value = "review_pane"  # type: ignore[attr-defined]
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "xprompt_save_snippet_mode_120x40",
            title="ACE unified save panel snippet mode",
        )


async def test_xprompt_save_no_writable_locations_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    rows = [
        _location(
            "Built-in xprompts/",
            "/opt/sase/xprompts",
            "Built-in (dev)",
            names=frozenset({"commit", "propose"}),
            disabled_reason="read-only",
            builtin=True,
        )
    ]
    modal = UnifiedXPromptSaveModal(
        rows,
        initial_name="review",
        body="Nothing can be written from this environment.",
    )
    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open(page, modal)
        ace_png_visual.assert_page_png(
            page,
            "xprompt_save_no_writable_locations_120x40",
            title="ACE unified xprompt save no writable locations",
        )
