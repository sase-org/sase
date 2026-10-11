"""ACE PNG snapshots for pane-scoped mini-macro authoring."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agent_workflow import (
    _prompt_bar_mini_macro_location as location_mod,
)
from sase.ace.tui.modals.macro_location_modal import (
    MACRO_HOME_DIR_LABEL,
    MACRO_PROJECT_DIR_LABEL,
)
from sase.ace.tui.modals.mini_macro_name_modal import (
    MiniMacroNameModal,
    MiniMacroNameResult,
)
from sase.ace.tui.modals.mini_macro_save_confirm_modal import (
    MiniMacroSaveConfirmModal,
    MiniMacroSaveConfirmState,
)
from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroDestinationTarget,
    MiniMacroTargetCatalog,
)
from sase.ace.tui.modals.unified_macro_save_modal import UnifiedSaveLocation
from sase.ace.tui.modals.macro_location_modal import MacroLocation
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.macro.naming import SaveResolution
from sase.macro.save import SaveTargetFormat
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
    return Path.cwd() / "sase" / "macros" / "visual"


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
        location=MacroLocation("Project macros", str(path), "directory"),  # type: ignore[arg-type]
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
    workflow_kind: str = "macro",
    reason: str | None = None,
) -> MiniMacroDefinition:
    return MiniMacroDefinition(
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


def _destination(path: Path, name: str = "review") -> MiniMacroDestinationTarget:
    target = path / f"{name}.md"
    return MiniMacroDestinationTarget(
        name=name,
        location_path=str(path),
        path=str(target),
        display_path=f"~/sase/macros/{name}.md",
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
) -> MiniMacroNameResult:
    return MiniMacroNameResult(
        name=name,
        action=action,  # type: ignore[arg-type]
        destination=_destination(path, name),
        definition=None,
        existing_definition=None,
    )


async def _open_name_modal(
    page: AcePage,
    modal: MiniMacroNameModal,
    expected_verdict: str,
) -> None:
    page.app.push_screen(modal)
    await page.expect_modal("MiniMacroNameModal")
    await wait_for_svg_contains(page, "● Name")
    await wait_for_state(
        page,
        lambda: (
            isinstance(page.app.screen, MiniMacroNameModal)
            and not page.app.screen._pending_analyses
            and not page.app.screen._analysis_tasks
            and expected_verdict
            in page.app.screen.query_one(
                "#mini-macro-name-verdict",
                Static,
            )
            .render()
            .plain
        ),
        description="mini-macro name modal analysis ready",
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
        "Original agent prompt that stays outside the mini-macro save.",
    )
    origin_id = bar.active_text_area().id or ""
    assert bar.open_mini_macro_target_pane(
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
            bar._stack.selected_item.is_mini_macro_pane
            and bar.active_text_area().has_focus
        ),
        description="mini-macro pane focused",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_mini_macro_name_fresh_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    del tmp_path
    directory = _visual_directory()
    row = _location(directory)
    catalog = MiniMacroTargetCatalog(
        definitions=(
            _definition("review_checklist", directory / "review_checklist.md"),
            _definition("release_notes", directory / "release_notes.md"),
        ),
        destinations=(row,),
    )
    modal = MiniMacroNameModal(catalog, row, initial_name="re")

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_name_modal(page, modal, "Create #re")
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_name_fresh_completion_120x40",
            title="ACE mini-macro name panel - fresh completion",
        )


async def test_mini_macro_name_edit_existing_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    del tmp_path
    directory = _visual_directory()
    row = _location(directory, names=frozenset({"review"}))
    definition = _definition("review", directory / "review.md")
    modal = MiniMacroNameModal(
        MiniMacroTargetCatalog(definitions=(definition,), destinations=(row,)),
        row,
        initial_name="review",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_name_modal(page, modal, "Edit #review")
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_name_edit_existing_120x40",
            title="ACE mini-macro name panel - edit existing",
        )


async def test_mini_macro_name_incompatible_swarm_png_snapshot(
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
    modal = MiniMacroNameModal(
        MiniMacroTargetCatalog(definitions=(definition,), destinations=(row,)),
        row,
        initial_name="swarm",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_name_modal(page, modal, "Cannot open #swarm")
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_name_incompatible_swarm_120x40",
            title="ACE mini-macro name panel - incompatible swarm",
        )


@pytest.mark.parametrize(
    ("destination_exists", "snapshot_name", "title"),
    [
        (
            False,
            "mini_macro_pane_new_120x40",
            "ACE mini-macro pane - new",
        ),
        (
            True,
            "mini_macro_pane_clean_light_120x40",
            "ACE mini-macro pane - clean light",
        ),
    ],
)
async def test_mini_macro_pane_new_and_clean_png_snapshots(
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


async def test_mini_macro_pane_dirty_png_snapshot(
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
            "mini_macro_pane_dirty_120x40",
            title="ACE mini-macro pane - dirty",
        )


async def test_mini_macro_pane_stale_png_snapshot(
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
        mini = bar._stack.mini_macro_item
        assert mini is not None
        assert bar.mark_mini_macro_changed_on_disk(
            item_id=mini.item_id,
            changed=True,
        )
        await wait_for_svg_contains(page, "changed on disk")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_pane_stale_120x40",
            title="ACE mini-macro pane - changed on disk",
        )


async def test_mini_macro_scoped_frontmatter_png_snapshot(
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
                "macros:\n"
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
            "mini_macro_scoped_frontmatter_120x40",
            title="ACE mini-macro pane - scoped frontmatter",
        )


def _fixture_location_rows() -> tuple[UnifiedSaveLocation, UnifiedSaveLocation]:
    """Deterministic picker rows that never read the host config.

    Both paths shorten to fixed ``./``/``~/`` strings on every host, so the
    list, the footer preview, and the golden can never leak ``/home/<user>``
    or a per-run tmp path.
    """
    project_dir = Path.cwd() / "sase" / "macros" / "visual"
    home_dir = Path.home() / "sase" / "macros"
    return (
        UnifiedSaveLocation(
            location=MacroLocation(
                MACRO_PROJECT_DIR_LABEL, str(project_dir), "directory"
            ),
            group="Project",
            display_path="./sase/macros/visual",
            names=frozenset(),
            precedence=0,
            namespace="sase",
        ),
        UnifiedSaveLocation(
            location=MacroLocation(MACRO_HOME_DIR_LABEL, str(home_dir), "directory"),
            group="Home",
            display_path="~/sase/macros",
            names=frozenset(),
            precedence=10,
        ),
    )


def _fixture_catalog(
    rows: tuple[UnifiedSaveLocation, UnifiedSaveLocation],
    macro_file: Path,
) -> MiniMacroTargetCatalog:
    """One editable fixture definition with a host-independent display path."""
    return MiniMacroTargetCatalog(
        definitions=(
            MiniMacroDefinition(
                name="rev",
                workflow_kind="macro",  # type: ignore[arg-type]
                source_path=str(macro_file),
                display_path="~/sase/macros/rev.md",
                storage_format=SaveTargetFormat.MARKDOWN,
                entry_name=None,
                location_path=rows[0].location.path,
                precedence=0,
                compatibility="editable",  # type: ignore[arg-type]
                effective=True,
                read_path=str(macro_file),
                write_path=str(macro_file),
            ),
        ),
        destinations=tuple(rows),
    )


def _stub_mini_macro_loaders(
    monkeypatch: pytest.MonkeyPatch,
    rows: tuple[UnifiedSaveLocation, UnifiedSaveLocation],
    catalog: MiniMacroTargetCatalog,
) -> None:
    """Serve fixture rows and catalog the way the snippet tests stub theirs."""
    monkeypatch.setattr(
        location_mod, "_load_unified_save_rows", lambda _project: list(rows)
    )
    monkeypatch.setattr(location_mod, "_load_last_used_locations", lambda: {})
    monkeypatch.setattr(
        location_mod,
        "_load_mini_macro_catalog",
        lambda _project, _loaded: catalog,
    )


async def test_mini_macro_location_flow_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Picker appearance on the mini-macro location-first path.

    The loader seams serve fixture rows and one fixture definition, so the
    golden covers the flow's data path without depending on the host's own
    macro files. Capture waits for a loaded destination row, never the
    ``Finding destinations…`` placeholder.
    """
    patch_startup_loaders(monkeypatch)
    rows = _fixture_location_rows()
    macro_file = tmp_path / "rev.md"
    macro_file.write_text("# rev\n\nFixture body.\n", encoding="utf-8")
    _stub_mini_macro_loaders(monkeypatch, rows, _fixture_catalog(rows, macro_file))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await mount_prompt_bar(page, "Summarize the risky assumptions.")
        await page.press("escape")
        await page.press("g", "x")
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "where should it live?")
        await wait_for_svg_contains(page, "Project macros")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_location_flow_picker_120x40",
            title="ACE mini-macro location picker — fixture chord flow",
        )


async def test_mini_macro_location_flow_finder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Picker → finder live-flow on ``g x`` then ``e`` with fixture data.

    The finder shows only the fixture definition; neither screen may show
    any ``/home/<user>`` path.
    """
    patch_startup_loaders(monkeypatch)
    rows = _fixture_location_rows()
    macro_file = tmp_path / "rev.md"
    macro_file.write_text("# rev\n\nFixture body.\n", encoding="utf-8")
    _stub_mini_macro_loaders(monkeypatch, rows, _fixture_catalog(rows, macro_file))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await mount_prompt_bar(page, "Summarize the risky assumptions.")
        await page.press("escape")
        await page.press("g", "x")
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Project macros")
        await page.press("e")
        await page.expect_modal("ExistingDefinitionFinderModal")
        await wait_for_svg_contains(page, "Edit existing macro")
        await wait_for_svg_contains(page, "#rev")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_location_flow_finder_120x40",
            title="ACE mini-macro location picker — existing finder",
        )


async def test_mini_macro_save_diff_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    state = MiniMacroSaveConfirmState(
        name="review",
        display_path="~/sase/macros/review.md",
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
        page.app.push_screen(MiniMacroSaveConfirmModal(state))
        await page.expect_modal("MiniMacroSaveConfirmModal")
        await wait_for_svg_contains(page, "Save mini-macro #review")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "mini_macro_save_diff_120x40",
            title="ACE mini-macro save review - diff",
        )
