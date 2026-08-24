"""Add/edit form validation for the Memory panel."""

from __future__ import annotations

from textual.widgets import Input, Select, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.memory_panel_add import (
    MemoryNoteFormDraft,
    MemoryNoteFormModal,
)
from sase.memory.notes import AGENTS_PARENT
from tests.ace.tui.modals.memory_panel_actions_test_helpers import (
    UNSET,
    MemoryNoteFormApp,
    fill_form,
    plain_text,
)
from tests.ace.tui.modals.memory_panel_test_helpers import memory_note


async def test_form_parent_options_and_path_preview() -> None:
    notes = (
        memory_note("always", note_type="core"),
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md"),
    )
    modal = MemoryNoteFormModal(
        existing_notes=notes,
        scope_display_name="sase",
    )
    app = MemoryNoteFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = app.screen
        assert isinstance(form, MemoryNoteFormModal)
        parent = form.query_one("#memory-note-form-parent", Select)
        parent.value = "sase/memory/hub.md"
        assert parent.value == "sase/memory/hub.md"
        form.query_one("#memory-note-form-stem", Input).value = "hub.md"
        form._update_path_preview()
        assert "sase/memory/hub.md" in plain_text(
            form.query_one("#memory-note-form-path", Static).content
        )


async def test_add_form_refuses_each_validation_branch() -> None:
    existing = (memory_note("alpha"),)
    modal = MemoryNoteFormModal(
        existing_notes=existing,
        scope_display_name="sase",
        include_project_memory=True,
    )
    app = MemoryNoteFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await fill_form(app, stem="", description="")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.blocking))
        assert app.result is UNSET
        stem_error = plain_text(
            form.query_one("#memory-note-form-stem-error", Static).content
        )
        assert "required" in stem_error
        desc_error = plain_text(
            form.query_one("#memory-note-form-description-error", Static).content
        )
        assert "description" in desc_error

        form = await fill_form(app, stem="README", description="A note.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "README" in plain_text(
            form.query_one("#memory-note-form-stem-error", Static).content
        )

        form = await fill_form(app, stem="../escape", description="A note.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "traversal" in plain_text(
            form.query_one("#memory-note-form-stem-error", Static).content
        )

        form = await fill_form(app, stem="alpha", description="A colliding note.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "already exists" in plain_text(
            form.query_one("#memory-note-form-stem-error", Static).content
        )

        form = await fill_form(app, stem="sase", description="Generated collision.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "read-only" in plain_text(
            form.query_one("#memory-note-form-stem-error", Static).content
        )


async def test_add_form_refuses_illegal_parent_and_cycle() -> None:
    notes = (
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md", description="Child."),
    )
    modal = MemoryNoteFormModal(
        mode="edit",
        existing_notes=notes,
        scope_display_name="sase",
        initial_stem="hub",
        initial_type="reference",
        initial_parent=AGENTS_PARENT,
        initial_description="Hub.",
        current_relative_path="sase/memory/hub.md",
    )
    app = MemoryNoteFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        assert app.screen.query_one("#memory-note-form-stem", Input).disabled is True
        form = await fill_form(app, parent="sase/memory/child.md", description="Hub.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.parent))
        assert "cycle" in plain_text(
            form.query_one("#memory-note-form-parent-error", Static).content
        )


async def test_add_form_valid_submit_returns_draft() -> None:
    modal = MemoryNoteFormModal(scope_display_name="sase")
    app = MemoryNoteFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await fill_form(
            app, stem="beta", note_type="reference", description="The middle note."
        )
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.result, MemoryNoteFormDraft))
    assert app.result == MemoryNoteFormDraft(
        stem="beta",
        note_type="reference",
        parent=AGENTS_PARENT,
        description="The middle note.",
    )


async def test_add_form_suppresses_required_errors_until_submit() -> None:
    modal = MemoryNoteFormModal(scope_display_name="sase")
    app = MemoryNoteFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await fill_form(app, stem="tmp", description="x")
        form = await fill_form(app, stem="", description="")
        form._validate_now()
        stem_error = plain_text(
            form.query_one("#memory-note-form-stem-error", Static).content
        )
        desc_error = plain_text(
            form.query_one("#memory-note-form-description-error", Static).content
        )
        assert stem_error == ""
        assert desc_error == ""
