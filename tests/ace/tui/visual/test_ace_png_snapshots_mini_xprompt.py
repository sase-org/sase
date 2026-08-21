"""ACE PNG snapshots for pane-scoped mini-xprompt authoring."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.mini_xprompt_name_modal import (
    MiniXPromptNameModal,
    MiniXPromptNameResult,
)
from sase.ace.tui.modals.mini_xprompt_save_confirm_modal import (
    MiniXPromptSaveConfirmModal,
    MiniXPromptSaveConfirmState,
)
from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    MiniXPromptDefinition,
    MiniXPromptDestinationTarget,
    MiniXPromptTargetCatalog,
)
from sase.ace.tui.modals.unified_xprompt_save_modal import UnifiedSaveLocation
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.naming import SaveResolution
from sase.xprompt.save import SaveTargetFormat
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


MINI_BODY = "Review the changed files and summarize the risky assumptions."
MINI_FRONTMATTER = "---\ndescription: Focused review helper\n---"


def _visual_directory() -> Path:
    return Path.cwd() / "sase" / "xprompts" / "visual"


def _display_path(path: Path) -> str:
    try:
        return f"./{path.relative_to(Path.cwd())}"
    except ValueError:
        return str(path)


def _location(
    path: Path,
    *,
    names: frozenset[str] = frozenset(),
    disabled_reason: str | None = None,
    precedence: int = 0,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=XPromptLocation("Project xprompts", str(path), "directory"),  # type: ignore[arg-type]
        group="Project",
        display_path=_display_path(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
    )


def _definition(
    name: str,
    path: Path,
    *,
    compatibility: str = "editable",
    workflow_kind: str = "xprompt",
    reason: str | None = None,
) -> MiniXPromptDefinition:
    return MiniXPromptDefinition(
        name=name,
        workflow_kind=workflow_kind,  # type: ignore[arg-type]
        source_path=str(path),
        display_path=_display_path(path),
        storage_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        location_path=str(path.parent),
        precedence=0,
        compatibility=compatibility,  # type: ignore[arg-type]
        incompatible_reason=reason,
        effective=True,
        read_path=str(path),
        write_path=str(path),
    )


def _destination(path: Path, name: str = "review") -> MiniXPromptDestinationTarget:
    target = path / f"{name}.md"
    return MiniXPromptDestinationTarget(
        name=name,
        location_path=str(path),
        path=str(target),
        display_path=f"~/sase/xprompts/{name}.md",
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        storage_name=name,
        read_path=str(target),
        write_path=str(target),
        apply_target=None,
        via_chezmoi=False,
        exists_here=target.exists(),
        resolution=SaveResolution(),
    )


def _name_result(
    path: Path,
    *,
    name: str = "review",
    action: str = "edit",
) -> MiniXPromptNameResult:
    return MiniXPromptNameResult(
        name=name,
        action=action,  # type: ignore[arg-type]
        destination=_destination(path, name),
        definition=None,
        existing_definition=None,
    )


async def _open_name_modal(
    page: AcePage,
    modal: MiniXPromptNameModal,
    expected_verdict: str,
) -> None:
    page.app.push_screen(modal)
    await page.expect_modal("MiniXPromptNameModal")
    await wait_for_svg_contains(page, "Open mini-xprompt")
    await wait_for_state(
        page,
        lambda: (
            isinstance(page.app.screen, MiniXPromptNameModal)
            and not page.app.screen._pending_analyses
            and not page.app.screen._analysis_tasks
            and expected_verdict
            in page.app.screen.query_one(
                "#mini-xprompt-name-verdict",
                Static,
            )
            .render()
            .plain
        ),
        description="mini-xprompt name modal analysis ready",
    )
    await wait_for_visual_idle(page)


async def _mount_with_mini_pane(
    page: AcePage,
    tmp_path: Path,
    *,
    destination_exists: bool,
    body: str = MINI_BODY,
    frontmatter: str = MINI_FRONTMATTER,
    action: str = "edit",
) -> PromptInputBar:
    bar = await mount_prompt_bar(
        page,
        "Original agent prompt that stays outside the mini-xprompt save.",
    )
    origin_id = bar.active_text_area().id or ""
    assert bar.open_mini_xprompt_target_pane(
        _name_result(tmp_path, action=action),
        origin_pane_id=origin_id,
        body=body,
        frontmatter=frontmatter,
        loaded_markdown=f"{frontmatter}\n\n{body}\n" if destination_exists else None,
        loaded_fingerprint=None,
        destination_exists=destination_exists,
    )
    await wait_for_state(
        page,
        lambda: (
            bar._stack.selected_item.is_mini_xprompt_pane
            and bar.active_text_area().has_focus
        ),
        description="mini-xprompt pane focused",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_mini_xprompt_name_fresh_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    del tmp_path
    directory = _visual_directory()
    row = _location(directory)
    catalog = MiniXPromptTargetCatalog(
        definitions=(
            _definition("review_checklist", directory / "review_checklist.md"),
            _definition("release_notes", directory / "release_notes.md"),
        ),
        destinations=(row,),
    )
    modal = MiniXPromptNameModal(catalog, initial_name="re")

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_name_modal(page, modal, "Create #re")
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_name_fresh_completion_120x40",
            title="ACE mini-xprompt name panel - fresh completion",
        )


async def test_mini_xprompt_name_edit_existing_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    del tmp_path
    directory = _visual_directory()
    row = _location(directory, names=frozenset({"review"}))
    definition = _definition("review", directory / "review.md")
    modal = MiniXPromptNameModal(
        MiniXPromptTargetCatalog(definitions=(definition,), destinations=(row,)),
        initial_name="review",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_name_modal(page, modal, "Edit #review")
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_name_edit_existing_120x40",
            title="ACE mini-xprompt name panel - edit existing",
        )


async def test_mini_xprompt_name_incompatible_swarm_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    del tmp_path
    directory = _visual_directory()
    row = _location(directory, names=frozenset({"swarm"}))
    definition = _definition(
        "swarm",
        directory / "swarm.md",
        compatibility="incompatible",
        reason="contains a top-level swarm separator",
    )
    modal = MiniXPromptNameModal(
        MiniXPromptTargetCatalog(definitions=(definition,), destinations=(row,)),
        initial_name="swarm",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_name_modal(page, modal, "Cannot open #swarm")
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_name_incompatible_swarm_120x40",
            title="ACE mini-xprompt name panel - incompatible swarm",
        )


@pytest.mark.parametrize(
    ("destination_exists", "snapshot_name", "title"),
    [
        (
            False,
            "mini_xprompt_pane_new_120x40",
            "ACE mini-xprompt pane - new",
        ),
        (
            True,
            "mini_xprompt_pane_clean_light_120x40",
            "ACE mini-xprompt pane - clean light",
        ),
    ],
)
async def test_mini_xprompt_pane_new_and_clean_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    destination_exists: bool,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        if destination_exists:
            page.app.theme = "textual-light"
        await _mount_with_mini_pane(
            page,
            tmp_path,
            destination_exists=destination_exists,
            action="edit" if destination_exists else "create",
        )
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_mini_xprompt_pane_dirty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        bar = await _mount_with_mini_pane(
            page,
            tmp_path,
            destination_exists=True,
        )
        bar.active_text_area().text = MINI_BODY + "\n\nAdd test notes before saving."
        bar._sync_state_from_widgets()
        bar.refresh_cursor_readouts()
        await wait_for_svg_contains(page, "●")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_pane_dirty_120x40",
            title="ACE mini-xprompt pane - dirty",
        )


async def test_mini_xprompt_pane_stale_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        bar = await _mount_with_mini_pane(
            page,
            tmp_path,
            destination_exists=True,
        )
        mini = bar._stack.mini_xprompt_item
        assert mini is not None
        assert bar.mark_mini_xprompt_changed_on_disk(
            item_id=mini.item_id,
            changed=True,
        )
        await wait_for_svg_contains(page, "changed on disk")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_pane_stale_120x40",
            title="ACE mini-xprompt pane - changed on disk",
        )


async def test_mini_xprompt_scoped_frontmatter_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        bar = await _mount_with_mini_pane(
            page,
            tmp_path,
            destination_exists=True,
            frontmatter=(
                "---\n"
                "description: Mini-local helper\n"
                "xprompts:\n"
                "  _mini: Use mini-only rules\n"
                "---"
            ),
        )
        bar.focus_frontmatter_panel()
        panel = bar.query_one("#frontmatter-panel", FrontmatterPanel)
        await wait_for_state(
            page,
            lambda: panel.has_focus and not panel.has_class("hidden"),
            description="mini scoped frontmatter panel focused",
        )
        await wait_for_svg_contains(page, "#review")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_scoped_frontmatter_120x40",
            title="ACE mini-xprompt pane - scoped frontmatter",
        )


async def test_mini_xprompt_save_diff_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    state = MiniXPromptSaveConfirmState(
        name="review",
        display_path="~/sase/xprompts/review.md",
        body="Review the changed files.\n\n- correctness\n- tests\n- risks",
        frontmatter="---\ndescription: Updated focused review\n---",
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        exists=True,
        existing_markdown=(
            "---\ndescription: Focused review\n---\n\n"
            "Review the changed files.\n\n- correctness\n"
        ),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(MiniXPromptSaveConfirmModal(state))
        await page.expect_modal("MiniXPromptSaveConfirmModal")
        await wait_for_svg_contains(page, "Save mini-xprompt #review")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_xprompt_save_diff_120x40",
            title="ACE mini-xprompt save review - diff",
        )
