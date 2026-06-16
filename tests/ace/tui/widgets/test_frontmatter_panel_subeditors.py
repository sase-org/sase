"""Structured ``input`` / ``xprompts`` sub-editing in the Frontmatter Panel (Phase 4).

Covers navigating into the unfolded sub-trees and the ``a`` / ``e`` / ``d``
(and ``enter``) routing into the sub-form modals, with the results applied back
onto the panel model and persisted onto the prompt stack's frontmatter string.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, TextArea

from sase.ace.tui.modals.input_item_modal import InputItemModal
from sase.ace.tui.modals.xprompt_item_modal import XPromptItemModal
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.models import InputType


class _PromptBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value, id="prompt-input-bar")


async def _open_panel(pilot: object, app: _PromptBarApp) -> FrontmatterPanel:
    bar = app.query_one(PromptInputBar)
    bar.focus_frontmatter_panel()
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    return app.query_one(FrontmatterPanel)


# --- navigation into sub-items ---------------------------------------------


async def test_jk_navigates_into_input_subtree() -> None:
    """``j`` steps from the ``input`` header into its sub-items."""
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        panel = await _open_panel(pilot, app)

        assert panel._selected_nav() == ("field", "input")
        await pilot.press("j")
        await pilot.pause()
        assert panel._selected_nav() == ("input", "service")


# --- add via header / picker -----------------------------------------------


async def test_add_input_item_via_header_modal() -> None:
    """``a`` on the ``input`` header opens the modal; saving adds the item."""
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = await _open_panel(pilot, app)

        await pilot.press("a")  # header selected -> add item
        await pilot.pause()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, InputItemModal)
        modal.query_one("#input-item-name", Input).value = "dry_run"
        modal.query_one("#input-item-type", Input).value = "bool"
        modal.query_one("#input-item-default", Input).value = "false"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()
        await pilot.pause()

        names = [arg.name for arg in panel.model.inputs]
        assert names == ["service", "dry_run"]
        dry_run = panel.model.get_input("dry_run")
        assert dry_run is not None and dry_run.default is False
        assert "dry_run" in bar._stack.frontmatter


async def test_begin_add_structured_field_opens_modal() -> None:
    """Picking ``xprompts`` from the add-property flow opens its sub-form."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = await _open_panel(pilot, app)

        # ``xprompts`` is offered by the core-schema picker now.
        assert "xprompts" in [name for name, _ in panel.addable_properties()]

        panel.begin_add("xprompts")
        await pilot.pause()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, XPromptItemModal)
        modal.query_one("#xprompt-item-name", Input).value = "_rules"
        modal.query_one("#xprompt-item-content", TextArea).text = "Follow the checklist"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()
        await pilot.pause()

        assert "_rules" in panel.model.xprompts
        assert "_rules" in bar._stack.frontmatter
        # The freshly authored helper is immediately usable for completion.
        assert [e.name for e in bar.local_xprompt_assist_entries()] == ["_rules"]


# --- edit / delete sub-items -----------------------------------------------


async def test_edit_input_subitem_updates_model() -> None:
    """``e`` on a sub-item edits it through the modal and persists the change."""
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = await _open_panel(pilot, app)

        await pilot.press("j")  # select the ``service`` sub-item
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, InputItemModal)
        # Prefilled from the existing input.
        assert modal.query_one("#input-item-name", Input).value == "service"
        modal.query_one("#input-item-type", Input).value = "line"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()
        await pilot.pause()

        service = panel.model.get_input("service")
        assert service is not None and service.type is InputType.LINE
        assert "service" in bar._stack.frontmatter


async def test_delete_input_subitem_removes_only_that_item() -> None:
    """``d`` on a sub-item deletes just that input, keeping the rest."""
    app = _PromptBarApp("---\ninput:\n  a: word\n  b: int\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        panel = await _open_panel(pilot, app)

        await pilot.press("j")  # select sub-item ``a``
        await pilot.pause()
        assert panel._selected_nav() == ("input", "a")
        await pilot.press("d")
        await pilot.pause()

        assert [arg.name for arg in panel.model.inputs] == ["b"]


async def test_delete_last_input_removes_whole_field() -> None:
    """Deleting the only input item drops the ``input`` field entirely."""
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = await _open_panel(pilot, app)

        await pilot.press("j")  # select the single sub-item
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        assert panel.model.inputs == []
        assert "input" not in panel.model.present_fields()
        assert "input" not in bar._stack.frontmatter
