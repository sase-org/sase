"""ACE TUI PNG snapshots for the Snippets panel in light and dark themes."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.snippets_panel import SnippetsPanel
from sase.ace.tui.modals.snippets_panel_add import SnippetFormModal
from sase.ace.tui.snippets_panel_catalog import SnippetDestination
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    install_fixed_load,
    project_ref,
    project_snapshot,
    snippet_call,
    snippet_entry,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _destination() -> SnippetDestination:
    return SnippetDestination(
        label="Project sase/sase.yml",
        path="/workspace/sase/sase.yml",
        display_path="sase/sase.yml",
        digest="abc",
        selectable=True,
    )


def _populated_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = project_ref("sase", "sase")
    greet = snippet_entry(
        "greet",
        raw="Hello $1, see #[todo]$0",
        composed="Hello $1, see TODO($2)$0",
        aliases=("Greet",),
        outbound=("todo",),
        inbound=("wrap",),
        calls=(snippet_call("todo", start=16, end=23),),
        path="/workspace/sase/sase.yml",
    )
    todo = snippet_entry(
        "todo",
        raw="TODO($1)$0",
        inbound=("greet",),
        path="/workspace/sase/sase.yml",
    )
    wrap = snippet_entry(
        "wrap",
        raw="#[greet] wrapped",
        outbound=("greet",),
        calls=(snippet_call("greet", start=0, end=8),),
        path="/workspace/sase/sase.yml",
    )
    install_fixed_load(
        monkeypatch,
        (ref,),
        {
            "sase": project_snapshot(
                ref,
                (greet, todo, wrap),
                destinations=(_destination(),),
                default_destination_path="/workspace/sase/sase.yml",
            )
        },
    )


def _empty_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = project_ref("gh_org__research", "Research")
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"gh_org__research": project_snapshot(ref, (), destinations=(_destination(),))},
    )


def _diagnostic_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = project_ref("sase", "sase")
    install_fixed_load(
        monkeypatch,
        (ref,),
        {
            "sase": project_snapshot(
                ref,
                (),
                diagnostics=("sase/sase.yml: ace.snippets.todo must be a string",),
                catalog=None,
            )
        },
    )


def _panel_ready(page: AcePage) -> bool:
    screen = page.app.screen
    return isinstance(screen, SnippetsPanel) and not screen._loading


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "snippets_panel_populated_dark_120x40",
            "ACE snippets panel - populated dark theme",
        ),
        (
            "textual-light",
            "snippets_panel_populated_light_120x40",
            "ACE snippets panel - populated light theme",
        ),
    ],
)
async def test_snippets_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _populated_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(SnippetsPanel(initial_trigger="greet"))
        await page.expect_modal("SnippetsPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await wait_for_svg_contains(page, "CALLS")
        await wait_for_svg_contains(page, "CALLED BY")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "snippets_panel_empty_dark_120x40",
            "ACE snippets panel - empty dark theme",
        ),
        (
            "textual-light",
            "snippets_panel_empty_light_120x40",
            "ACE snippets panel - empty light theme",
        ),
    ],
)
async def test_snippets_panel_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _empty_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(SnippetsPanel())
        await page.expect_modal("SnippetsPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await wait_for_svg_contains(page, "Research")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "snippets_panel_diagnostic_dark_120x40",
            "ACE snippets panel - diagnostic dark theme",
        ),
        (
            "textual-light",
            "snippets_panel_diagnostic_light_120x40",
            "ACE snippets panel - diagnostic light theme",
        ),
    ],
)
async def test_snippets_panel_diagnostic_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _diagnostic_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(SnippetsPanel())
        await page.expect_modal("SnippetsPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await wait_for_svg_contains(page, "failed to load")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "snippets_panel_relation_dark_120x40",
            "ACE snippets panel - relation-focused dark theme",
        ),
        (
            "textual-light",
            "snippets_panel_relation_light_120x40",
            "ACE snippets panel - relation-focused light theme",
        ),
    ],
)
async def test_snippets_panel_relation_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _populated_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(SnippetsPanel(initial_trigger="greet"))
        await page.expect_modal("SnippetsPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await page.press("tab")
        await wait_for_state(
            page,
            lambda: (
                isinstance(page.app.screen, SnippetsPanel)
                and page.app.screen._chip_cursor == 0
            ),
            description="focused first CALLS chip",
        )
        await wait_for_svg_contains(page, "todo")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "snippets_panel_add_dark_120x40",
            "ACE snippets panel - add form dark theme",
        ),
        (
            "textual-light",
            "snippets_panel_add_light_120x40",
            "ACE snippets panel - add form light theme",
        ),
    ],
)
async def test_snippets_panel_add_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _populated_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(SnippetsPanel(initial_trigger="greet"))
        await page.expect_modal("SnippetsPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await page.press("a")
        await wait_for_state(
            page,
            lambda: isinstance(page.app.screen, SnippetFormModal),
            description="add form",
        )
        await wait_for_svg_contains(page, "Add snippet")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "snippets_panel_delete_dark_120x40",
            "ACE snippets panel - delete impact dark theme",
        ),
        (
            "textual-light",
            "snippets_panel_delete_light_120x40",
            "ACE snippets panel - delete impact light theme",
        ),
    ],
)
async def test_snippets_panel_delete_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _populated_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(SnippetsPanel(initial_trigger="todo"))
        await page.expect_modal("SnippetsPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await page.press("d")
        await wait_for_state(
            page,
            lambda: isinstance(page.app.screen, ConfirmActionModal),
            description="delete confirm",
        )
        await wait_for_svg_contains(page, "Delete snippet")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
