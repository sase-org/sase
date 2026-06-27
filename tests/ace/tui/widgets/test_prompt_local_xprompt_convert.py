"""Widget-level tests for the ``gX`` / ``Ctrl+G X`` local-xprompt conversion.

The prompt-local ``gX`` (NORMAL) / ``Ctrl+G X`` (INSERT) keymap turns the active
prompt pane into a local ``xprompts:`` helper stored in the bar's shared
frontmatter, then replaces that pane with an invocation of the helper.  These
tests drive the whole flow through the real name modal and assert the resulting
frontmatter and pane text, including the no-op / unchanged paths.
"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Input

from sase.ace.tui.modals.local_xprompt_name_modal import LocalXPromptNameModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.models import InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter


class _ConvertApp(App[None]):
    """Hosts a prompt bar and records notifications."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        initial_value: str = "",
        *,
        mode: str = "prompt",
        initial_xprompt_markdown: str | None = None,
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self._initial_xprompt_markdown = initial_xprompt_markdown
        self.notifications: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            initial_xprompt_markdown=self._initial_xprompt_markdown,
            id="prompt-input-bar",
        )

    def notify(self, message: str, **kwargs: Any) -> None:  # type: ignore[override]
        self.notifications.append((message, kwargs.get("severity", "information")))


async def _open_convert_modal(
    pilot: Any,
    app: _ConvertApp,
    *,
    via_ctrl_g: bool = False,
) -> LocalXPromptNameModal | None:
    """Trigger ``gX`` / ``Ctrl+G X`` and return the pushed name modal, if any."""
    if via_ctrl_g:
        # INSERT-mode Ctrl+G X.
        await pilot.press("ctrl+g", "X")
    else:
        # NORMAL-mode gX.
        await pilot.press("escape", "g", "X")
    await pilot.pause()
    await pilot.pause()
    screen = app.screen
    return screen if isinstance(screen, LocalXPromptNameModal) else None


async def _submit_name(pilot: Any, modal: LocalXPromptNameModal, name: str) -> None:
    """Type *name* into the modal and submit it."""
    modal.query_one("#local-xprompt-name-input", Input).value = name
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


# -- happy paths ------------------------------------------------------------


async def test_gx_converts_pane_and_adds_local_xprompt() -> None:
    app = _ConvertApp("Do the thing")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await _submit_name(pilot, modal, "rules")

        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert "_rules" in model.xprompts
        assert model.xprompts["_rules"].content == "Do the thing"
        assert model.xprompts["_rules"].inputs == []
        # No inputs -> bare reference, NORMAL-mode target preserved.
        assert bar.active_text() == "#_rules"
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_g_x_converts_pane_from_insert_mode() -> None:
    app = _ConvertApp("Do the thing")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Bar mounts in INSERT mode; reach the conversion via Ctrl+G X.
        assert bar.active_text_area()._vim_mode == "insert"

        modal = await _open_convert_modal(pilot, app, via_ctrl_g=True)
        assert modal is not None
        await _submit_name(pilot, modal, "rules")

        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert "_rules" in model.xprompts
        assert bar.active_text() == "#_rules"


async def test_gx_with_jinja_infers_text_inputs_and_named_arg_skeleton() -> None:
    app = _ConvertApp("Review {{ topic }} carefully")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await _submit_name(pilot, modal, "rules")

        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        helper = model.xprompts["_rules"]
        assert [arg.name for arg in helper.inputs] == ["topic"]
        assert helper.inputs[0].type is InputType.TEXT

        text_area = bar.active_text_area()
        # Named-argument invocation with snippet tabstops, left in INSERT mode.
        assert text_area.text == "#_rules(topic=)"
        assert text_area._vim_mode == "insert"
        assert text_area._snippet_tabstops  # remaining tabstop(s) pending


async def test_gx_does_not_infer_known_globals_as_inputs() -> None:
    app = _ConvertApp("Path is {{ root }}")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await _submit_name(pilot, modal, "rules")

        helper = PromptFrontmatter.parse(bar._stack.frontmatter).xprompts["_rules"]
        assert helper.inputs == []
        assert bar.active_text() == "#_rules"


# -- multi-pane + preservation ----------------------------------------------


async def test_gx_only_changes_active_pane_in_multi_pane_stack() -> None:
    app = _ConvertApp("first pane\n---\nsecond {{ topic }}")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert len(bar._stack) == 2
        # The bottom pane is active by default.

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await _submit_name(pilot, modal, "rules")

        bar._sync_state_from_widgets()
        texts = bar._stack.texts
        assert texts[0] == "first pane"
        assert texts[1] == "#_rules(topic=)"
        assert "_rules" in PromptFrontmatter.parse(bar._stack.frontmatter).xprompts


async def test_gx_preserves_existing_frontmatter_and_local_xprompts() -> None:
    markdown = (
        "---\nname: my prompt\nxprompts:\n  _existing: old helper\n---\nBrand new body"
    )
    app = _ConvertApp(initial_xprompt_markdown=markdown)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await _submit_name(pilot, modal, "fresh")

        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.name == "my prompt"
        assert model.xprompts["_existing"].content == "old helper"
        assert model.xprompts["_fresh"].content == "Brand new body"
        assert bar.active_text() == "#_fresh"


# -- no-op / unchanged paths ------------------------------------------------


async def test_gx_blank_pane_warns_and_makes_no_change() -> None:
    app = _ConvertApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is None  # no name modal pushed for a blank pane
        assert bar._stack.frontmatter == ""
        assert any(sev == "warning" for _msg, sev in app.notifications)


async def test_gx_invalid_jinja_warns_and_makes_no_change() -> None:
    app = _ConvertApp("Broken {{ unclosed")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is None
        assert bar._stack.frontmatter == ""
        assert bar.active_text() == "Broken {{ unclosed"
        assert any(sev == "warning" for _msg, sev in app.notifications)


async def test_gx_duplicate_name_is_rejected_without_overwrite() -> None:
    markdown = "---\nxprompts:\n  _rules: original helper\n---\nReplacement body"
    app = _ConvertApp(initial_xprompt_markdown=markdown)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await _submit_name(pilot, modal, "rules")  # normalizes to _rules (dup)

        # The modal stays open (no dismiss) and nothing was overwritten.
        assert isinstance(app.screen, LocalXPromptNameModal)
        helper = PromptFrontmatter.parse(bar._stack.frontmatter).xprompts["_rules"]
        assert helper.content == "original helper"


async def test_gx_cancel_leaves_everything_unchanged() -> None:
    app = _ConvertApp("Do the thing")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is not None
        await pilot.press("escape")  # cancel the modal
        await pilot.pause()
        await pilot.pause()

        assert not isinstance(app.screen, LocalXPromptNameModal)
        assert bar._stack.frontmatter == ""
        assert bar.active_text() == "Do the thing"


async def test_gx_in_feedback_mode_is_a_noop() -> None:
    app = _ConvertApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        modal = await _open_convert_modal(pilot, app)
        assert modal is None
        assert bar.active_text() == "plan note"
        assert bar._stack.frontmatter == ""
