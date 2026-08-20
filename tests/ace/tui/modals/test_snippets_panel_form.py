"""Add/edit form validation for the Snippets panel."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Static, TextArea

from sase.ace.testing import wait_for
from sase.ace.tui.modals.snippets_panel_add import (
    SnippetFormDraft,
    SnippetFormModal,
    _plan_snippet_form,
)
from sase.ace.tui.snippets_panel_catalog import SnippetDestination
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    project_ref,
    project_snapshot,
    snippet_entry,
)

_UNSET = object()


class _FormApp(App[None]):
    def __init__(self, modal: SnippetFormModal) -> None:
        super().__init__()
        self.modal = modal
        self.result: SnippetFormDraft | None | object = _UNSET

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal, self._capture)

    def _capture(self, result: SnippetFormDraft | None) -> None:
        self.result = result


def _destination(path: str = "/tmp/sase.yml") -> SnippetDestination:
    return SnippetDestination(
        label="Project",
        path=path,
        display_path=path,
        digest="abc",
        selectable=True,
    )


def test_plan_refuses_blank_and_invalid_triggers() -> None:
    dest = _destination()
    blank = _plan_snippet_form(
        trigger="  ", template="hello$0", destination=dest, catalog=None, mode="add"
    )
    assert blank.blocking
    assert any("nonblank" in item for item in blank.trigger_errors)

    invalid = _plan_snippet_form(
        trigger="bad-name!",
        template="hello$0",
        destination=dest,
        catalog=None,
        mode="add",
    )
    assert invalid.blocking
    assert any("invalid" in item for item in invalid.trigger_errors)


def test_plan_names_replace_versus_shadow() -> None:
    ref = project_ref("sase", "sase")
    existing = snippet_entry("todo", path="/tmp/sase.yml")
    catalog = project_snapshot(ref, (existing,)).catalog
    same = _plan_snippet_form(
        trigger="todo",
        template="NEW$0",
        destination=_destination("/tmp/sase.yml"),
        catalog=catalog,
        mode="add",
    )
    assert same.action == "replaced"
    assert same.force
    assert same.collision is not None
    assert "replaces" in same.collision

    shadow = _plan_snippet_form(
        trigger="todo",
        template="NEW$0",
        destination=_destination("/tmp/other.yml"),
        catalog=catalog,
        mode="add",
    )
    assert shadow.action == "shadowed"
    assert shadow.collision is not None
    assert "shadow" in shadow.collision


async def test_form_submit_returns_draft() -> None:
    modal = SnippetFormModal(
        destinations=(_destination(),),
        default_destination_path="/tmp/sase.yml",
        project_display_name="sase",
    )
    app = _FormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, SnippetFormModal))
        form = app.screen
        assert isinstance(form, SnippetFormModal)
        form.query_one("#snippets-form-trigger", Input).value = "todo"
        form.query_one("#snippets-form-template", TextArea).text = "TODO($1)$0"
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.result, SnippetFormDraft))
    assert app.result == SnippetFormDraft(
        trigger="todo",
        template="TODO($1)$0",
        target="/tmp/sase.yml",
        expected_digest="abc",
        force=False,
        mode="add",
    )
