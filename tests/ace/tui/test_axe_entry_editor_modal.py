"""Reusable AXE entry editor behavior and layout coverage."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

from textual.binding import Binding

from sase.ace.testing import AcePage
from sase.ace.tui.modals.axe_entry_editor_modal import (
    AxeEntryEditorModal,
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeEntryMutationRequest,
    AxeWritableScope,
)
from sase.ace.tui.modals.axe_entry_editor_rendering import _HOME, _display_path
from sase.ace.tui.modals.config_transaction_preview import (
    ConfigTransactionPreview,
    TransactionEffectivePreview,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.config.inventory import load_config_schema


_CHOP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script": {"type": "string", "minLength": 1, "description": "Executable."},
        "description": {"type": "string", "description": "What it does."},
        "enabled": {"type": "boolean", "default": True},
        "run_every": {"type": "string", "pattern": r"^\d+[smh]$"},
        "timeout": {"type": "string", "pattern": r"^\d+[smh]$"},
        "env": {"type": "object", "additionalProperties": True},
        "inhibit_if": {"oneOf": [{"type": "array"}, {"type": "object"}]},
        "trigger": {"oneOf": [{"type": "string"}, {"type": "object"}]},
        "once_per": {"oneOf": [{"type": "string"}, {"type": "object"}]},
        "for_each": {"type": "array", "items": {"type": "object"}},
        "vars": {"type": "object", "additionalProperties": True},
    },
}


def _seed(*, running: bool = False) -> AxeEntryEditorSeed:
    return AxeEntryEditorSeed(
        identity=AxeEntryIdentity(
            "chop",
            "checks",
            "lint",
            generated_instance="lint[project=sase]",
        ),
        schema=_CHOP_SCHEMA,
        writable_scopes=(
            AxeWritableScope("user", "/tmp/sase.yml", "user"),
            AxeWritableScope("overlay:test", "/tmp/sase_test.yml", "overlay"),
        ),
        effective_values={"script": "sase_lint", "enabled": True},
        raw_values={"script": "sase_lint"},
        inherited_values={"enabled": True},
        provenance={"script": "user", "enabled": "default"},
        generated_warning="Editing the base chop affects every generated instance.",
        running=running,
    )


def _preview() -> ConfigTransactionPreview:
    return ConfigTransactionPreview(
        target_path="/tmp/sase.yml",
        effective=TransactionEffectivePreview(True, "old", True, "new", True),
        diagnostics=(),
        warnings=("missing executable is checked by the caller",),
        text_diff="@@ -1 +1 @@\n-old\n+new\n",
    )


def test_bundled_lumberjack_and_chop_friendly_field_order() -> None:
    schema = load_config_schema()
    scope = (AxeWritableScope("user"),)
    lumberjack = AxeEntryEditorModal(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("lumberjack", "checks"),
            schema=schema,
            writable_scopes=scope,
            effective_values={"interval": 1},
        )
    )
    assert [field.name for field in lumberjack._form.fields] == [
        "interval",
        "chop_timeout",
        "env",
    ]
    assert lumberjack._form.field("env").editor_kind == "yaml"

    chop = AxeEntryEditorModal(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("chop", "checks", "lint"),
            schema=schema,
            writable_scopes=scope,
            effective_values={"script": "sase_lint"},
        )
    )
    assert [field.name for field in chop._form.fields] == [
        "script",
        "description",
        "enabled",
        "run_every",
        "timeout",
        "env",
        "inhibit_if",
        "trigger",
        "once_per",
        "for_each",
        "vars",
    ]
    assert all(
        chop._form.field(name).editor_kind == "yaml"
        for name in (
            "env",
            "inhibit_if",
            "trigger",
            "once_per",
            "for_each",
            "vars",
        )
    )


def test_new_seed_intentionally_touches_only_declared_initial_fields() -> None:
    modal = AxeEntryEditorModal(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("chop", "checks", "new"),
            schema=_CHOP_SCHEMA,
            writable_scopes=(AxeWritableScope("user"),),
            effective_values={"script": "sase_chop_new", "enabled": True},
            new_entry=True,
            initial_touched=("script",),
        )
    )
    assert [operation.key_path for operation in modal._form.operations()] == [
        ("script",)
    ]
    assert modal._mode == "cell"
    assert modal._title_text().plain.startswith("Add AXE chop")


def test_scope_path_collapses_home_and_preserves_both_ends() -> None:
    rendered = _display_path(
        f"{_HOME}/.config/sase/a-very-long-overlay-name/sase.yml",
        30,
    )
    assert len(rendered) <= 30
    assert rendered.startswith("~/")
    assert "…" in rendered
    assert rendered.endswith("sase.yml")


def test_scope_change_refreshes_target_contribution_without_touching_draft() -> None:
    seed = _seed()
    seed = replace(
        seed,
        raw_values_by_scope={
            "user": {"script": "sase_lint"},
            "overlay:test": {},
        },
    )
    modal = AxeEntryEditorModal(seed)
    modal._form = modal._form.set_value("script", "draft")
    modal.action_cycle_scope()
    assert modal._target == "overlay:test"
    assert not modal._form.field("script").has_target
    assert modal._form.field("script").draft_value == "draft"


def test_q_binding_maps_to_non_priority_editor_quit_action() -> None:
    binding = next(
        item
        for item in AxeEntryEditorModal.BINDINGS
        if isinstance(item, Binding) and item.key == "q"
    )

    assert binding.action == "quit_editor"
    assert binding.description == "Quit"
    assert binding.priority is False


async def test_real_mount_opens_existing_entry_in_unfocused_browse_mode() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.pause()

        assert "checks / lint" in (modal.query_one("#axe-editor-title").render().plain)
        assert modal.query_one("#axe-editor-scope-0").render().plain == "1 user"
        assert modal._mode == "browse"
        assert len(modal.query(".axe-editor-cell-editor")) == 0
        assert modal.focused is None


async def test_q_closes_browse_without_invoking_app_quit() -> None:
    dismissed: list[object] = []
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal, dismissed.append)
        await page.expect_modal("AxeEntryEditorModal")

        with patch.object(
            page.app,
            "action_quit",
            new_callable=AsyncMock,
        ) as app_quit:
            await page.press("q")
            await page.wait_for(lambda _screen: bool(dismissed))
            app_quit.assert_not_awaited()

        await page.expect_no_modal()
    assert dismissed == [None]


async def test_q_closes_preview_directly_instead_of_returning_to_edit() -> None:
    dismissed: list[object] = []
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal, dismissed.append)
        await page.expect_modal("AxeEntryEditorModal")
        modal._form = modal._form.set_value("script", "changed")
        modal.action_confirm()
        await page.wait_for(
            lambda _screen: modal._stage == "preview" and modal._plan is not None
        )

        await page.press("q")
        await page.wait_for(lambda _screen: bool(dismissed))

        assert modal._stage == "preview"
        await page.expect_no_modal()
    assert dismissed == [None]


async def test_q_is_insert_text_then_closes_cell_from_normal_mode() -> None:
    dismissed: list[object] = []
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal, dismissed.append)
        await page.expect_modal("AxeEntryEditorModal")
        await page.press("enter")
        await page.wait_for(lambda _screen: modal.focused is modal._cell_editor)
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)

        await page.press("q")
        await page.wait_for(lambda _screen: editor.text == "q")
        assert modal._mode == "cell"
        assert dismissed == []

        await page.press("escape")
        assert editor._vim_mode == "normal"
        await page.press("q")
        await page.wait_for(lambda _screen: bool(dismissed))
    assert dismissed == [None]


async def test_q_is_consumed_but_does_not_dismiss_while_busy() -> None:
    dismissed: list[object] = []
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal, dismissed.append)
        await page.expect_modal("AxeEntryEditorModal")
        modal._busy = True

        with patch.object(
            page.app,
            "action_quit",
            new_callable=AsyncMock,
        ) as app_quit:
            await page.press("q")
            await page.pause()
            app_quit.assert_not_awaited()

        assert dismissed == []
        assert page.state["modal"] == "AxeEntryEditorModal"


async def test_chop_sheet_shows_every_field_scope_warning_and_narrow_layout() -> None:
    async with AcePage(size=(70, 36)) as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.wait_for(lambda _screen: modal.has_class("-narrow"))
        assert modal.has_class("-narrow")
        assert modal.query_one("#axe-editor-basics-header").render().plain == "BASICS"
        assert modal.query_one("#axe-editor-advanced-header").render().plain == (
            "ADVANCED"
        )
        assert len(modal.query(".axe-editor-field")) == len(_CHOP_SCHEMA["properties"])
        assert modal.query_one("#axe-editor-badge-0").render().plain.strip() == "·user"
        assert "every generated instance" in (
            modal.query_one("#axe-editor-warning").render().plain
        )
        await page.click("#axe-editor-scope-1")
        assert modal._target == "overlay:test"
        description_index = next(
            index
            for index, field in enumerate(modal._form.fields)
            if field.name == "description"
        )
        await page.click(f"#axe-editor-field-{description_index}")
        assert modal._active_name == "description"
        assert not hasattr(modal, "action_add_property")


async def test_browse_navigation_works_on_open_and_after_committing_edit() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.pause()

        assert modal._active_name == "script"
        await page.press("down")
        assert modal._active_name == "description"
        await page.press("k")
        assert modal._active_name == "script"
        await page.press("j")
        assert modal._active_name == "description"
        await page.press("up")
        assert modal._active_name == "script"

        await page.press("enter")
        await page.wait_for(
            lambda _screen: len(modal.query(".axe-editor-cell-editor")) == 1
        )
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)
        editor.text = "sase_check"
        await page.wait_for(
            lambda _screen: modal._form.field("script").draft_value == "sase_check"
        )
        await page.press("enter")
        await page.wait_for(lambda _screen: modal._mode == "browse")
        await page.press("down")
        assert modal._active_name == "description"
        assert modal._form.field("script").draft_value == "sase_check"


async def test_escape_escalates_insert_normal_browse_close_with_draft_intact() -> None:
    dismissed: list[object] = []
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal, dismissed.append)
        await page.expect_modal("AxeEntryEditorModal")
        await page.press("enter")
        await page.wait_for(
            lambda _screen: len(modal.query(".axe-editor-cell-editor")) == 1
        )
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)
        await page.wait_for(lambda _screen: modal.focused is editor)
        editor.text = "sase_preserved"
        await page.press("escape")
        assert editor._vim_mode == "normal"
        assert modal._mode == "cell"
        await page.press("escape")
        await page.wait_for(lambda _screen: modal._mode == "browse")
        assert modal._form.field("script").draft_value == "sase_preserved"
        assert len(modal.query(".axe-editor-cell-editor")) == 0
        await page.press("escape")
        await page.wait_for(lambda _screen: bool(dismissed))
    assert dismissed == [None]


async def test_digits_scopes_bool_toggle_and_inherit_restore() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")

        await page.press("2")
        assert modal._target == "overlay:test"
        enabled_index = next(
            index
            for index, field in enumerate(modal._form.fields)
            if field.name == "enabled"
        )
        await page.click(f"#axe-editor-field-{enabled_index}")
        await page.press("space")
        assert modal._form.field("enabled").draft_value is False
        await page.press("ctrl+r")
        assert modal._form.field("enabled").reset
        await page.press("ctrl+r")
        enabled = modal._form.field("enabled")
        assert not enabled.touched
        assert enabled.draft_value is True


async def test_tab_and_shift_tab_commit_and_move_focused_cell() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.press("enter")
        await page.wait_for(
            lambda _screen: len(modal.query(".axe-editor-cell-editor")) == 1
        )
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)
        await page.wait_for(lambda _screen: modal.focused is editor)
        editor.text = "sase_tabbed"
        await page.press("tab")
        await page.wait_for(lambda _screen: modal._active_name == "description")
        assert modal._form.field("script").draft_value == "sase_tabbed"
        assert len(modal.query(".axe-editor-cell-editor")) == 1

        await page.wait_for(lambda _screen: modal.focused is modal._cell_editor)
        await page.press("shift+tab")
        await page.wait_for(lambda _screen: modal._active_name == "script")
        assert len(modal.query(".axe-editor-cell-editor")) == 1


async def test_ctrl_actions_reach_modal_while_cell_editor_is_focused() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.press("enter")
        await page.wait_for(
            lambda _screen: len(modal.query(".axe-editor-cell-editor")) == 1
        )
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)
        await page.wait_for(lambda _screen: modal.focused is editor)
        editor.text = "sase_ctrl"
        await page.press("ctrl+t")
        assert modal._target == "overlay:test"
        assert modal._mode == "cell"
        await page.press("ctrl+s")
        await page.wait_for(
            lambda _screen: modal._stage == "preview" and modal._plan is not None
        )
        assert modal._form.field("script").draft_value == "sase_ctrl"


async def test_ctrl_reset_and_multiline_escape_work_with_focused_editor() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.pause()

        await page.press("enter")
        await page.wait_for(lambda _screen: modal.focused is modal._cell_editor)
        await page.press("ctrl+r")
        await page.wait_for(lambda _screen: modal._mode == "browse")
        assert modal._form.field("script").reset
        assert len(modal.query(".axe-editor-cell-editor")) == 0

        await page.press("ctrl+r")
        env_index = next(
            index
            for index, field in enumerate(modal._form.fields)
            if field.name == "env"
        )
        await page.click(f"#axe-editor-value-text-{env_index}")
        await page.wait_for(lambda _screen: modal.focused is modal._cell_editor)
        editor = modal._cell_editor
        assert editor is not None
        editor.text = "A: one\n"
        await page.press("escape")
        assert editor._vim_mode == "normal"
        await page.press("escape")
        await page.wait_for(lambda _screen: modal._mode == "browse")
        assert modal._form.field("env").draft_value == {"A": "one"}


async def test_invalid_draft_surfaces_in_status_and_blocks_preview() -> None:
    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.pause()
        run_every_index = next(
            index
            for index, field in enumerate(modal._form.fields)
            if field.name == "run_every"
        )
        await page.click(f"#axe-editor-value-text-{run_every_index}")
        await page.wait_for(
            lambda _screen: len(modal.query(".axe-editor-cell-editor")) == 1
        )
        editor = modal.query_one(".axe-editor-cell-editor", SingleLineVimTextArea)
        await page.wait_for(lambda _screen: modal.focused is editor)
        editor.text = "eventually"
        await page.press("enter")
        await page.wait_for(lambda _screen: modal._mode == "browse")
        await page.press("ctrl+s")
        assert modal._stage == "edit"
        assert modal._plan is None
        assert "run_every" in modal.query_one("#axe-editor-status").render().plain


async def test_preview_back_retains_sparse_draft_and_running_primary_restarts() -> None:
    requests: list[AxeEntryMutationRequest] = []
    applied: list[object] = []
    result: list[object] = []

    def plan(request: AxeEntryMutationRequest) -> ConfigTransactionPreview:
        requests.append(request)
        return _preview()

    def apply(plan_value: object) -> str:
        applied.append(plan_value)
        return "written"

    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(running=True), plan=plan, apply=apply)
        page.app.push_screen(modal, result.append)
        await page.expect_modal("AxeEntryEditorModal")
        modal._form = modal._form.set_value("script", "sase_check")
        modal._render_all()
        modal.action_confirm()
        await page.wait_for(lambda _screen: modal._plan is not None)
        assert requests[0].operations[0].key_path == ("script",)
        modal.action_back()
        assert modal._form.field("script").draft_value == "sase_check"
        modal.action_confirm()
        await page.wait_for(lambda _screen: modal._plan is not None)
        modal.action_confirm()
        await page.wait_for(lambda _screen: bool(result))
    assert applied
    assert result[0].restart_requested is True  # type: ignore[attr-defined]


async def test_stopped_save_and_running_save_only_never_request_restart() -> None:
    for seed, save_only in ((_seed(), False), (_seed(running=True), True)):
        result: list[object] = []
        async with AcePage() as page:
            modal = AxeEntryEditorModal(
                seed,
                plan=lambda _request: _preview(),
                apply=lambda _plan: "written",
            )
            page.app.push_screen(modal, result.append)
            await page.expect_modal("AxeEntryEditorModal")
            modal._form = modal._form.set_value("script", "changed")
            modal.action_confirm()
            await page.wait_for(
                lambda _screen, current_modal=modal: current_modal._plan is not None
            )
            if save_only:
                modal.action_save_only()
            else:
                modal.action_confirm()
            await page.wait_for(
                lambda _screen, current_result=result: bool(current_result)
            )
        assert result[0].restart_requested is False  # type: ignore[attr-defined]
