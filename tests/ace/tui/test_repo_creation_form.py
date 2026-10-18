"""Behavior tests for the standalone provider-driven repository form."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from sase.ace.tui.widgets.repo_creation_form import RepoCreationFormWidget
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.workspace_provider._hookspec import (
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
)


def _form(
    fields: tuple[RepoCreationField, ...], *, can_create: bool | None = True
) -> RepoCreationForm:
    return RepoCreationForm(
        workflow_type="gh",
        namespace="sase-org",
        fields=fields,
        can_create=can_create,
        message="Owner capability is provider-supplied.",
        remedy_argv=("gh", "auth", "login"),
    )


def _template_form(*, template: str = "") -> RepoCreationForm:
    return _form(
        (
            RepoCreationField(
                name="description", label="Description", kind="line", default="A repo"
            ),
            RepoCreationField(
                name="details", label="Details", kind="text", default="First line"
            ),
            RepoCreationField(
                name="visibility",
                label="Visibility",
                kind="choice",
                default="private",
                choices=(
                    RepoCreationChoice(value="public", label="Public"),
                    RepoCreationChoice(value="private", label="Private"),
                    RepoCreationChoice(
                        value="internal",
                        label="Internal",
                        disabled_reason="Internal repositories are unavailable to this owner.",
                    ),
                ),
            ),
            RepoCreationField(
                name="readme", label="README", kind="bool", default="YES"
            ),
            RepoCreationField(
                name="gitignore",
                label="gitignore",
                kind="search",
                default="Python",
                choices=(
                    RepoCreationChoice(value="Python", label="Python"),
                    RepoCreationChoice(value="Node", label="Node.js"),
                ),
            ),
            RepoCreationField(
                name="license",
                label="License",
                kind="search",
                default="MIT",
                choices=(
                    RepoCreationChoice(value="MIT"),
                    RepoCreationChoice(value="Apache-2.0"),
                ),
            ),
            RepoCreationField(
                name="team",
                label="Team",
                kind="search",
                default="developers",
                choices=(RepoCreationChoice(value="developers"),),
            ),
            RepoCreationField(
                name="template",
                label="Template",
                kind="line",
                group="advanced",
                default=template,
                excludes=("readme", "gitignore", "license", "team"),
            ),
            RepoCreationField(
                name="include_all_branches",
                label="Include all branches",
                kind="bool",
                group="advanced",
                requires=("template",),
            ),
            RepoCreationField(
                name="homepage",
                label="Homepage",
                kind="line",
                group="advanced",
            ),
        )
    )


class _FormApp(App[None]):
    def __init__(self, form: RepoCreationForm, values: dict[str, str] | None = None):
        super().__init__()
        self._form = form
        self._values = values
        self.change_events = 0

    def compose(self) -> ComposeResult:
        yield RepoCreationFormWidget(self._form, self._values)

    def on_repo_creation_form_widget_changed(
        self, _event: RepoCreationFormWidget.Changed
    ) -> None:
        self.change_events += 1


async def test_provider_form_renders_all_field_kinds_and_preserves_bool_spelling() -> (
    None
):
    app = _FormApp(_template_form())
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        assert isinstance(
            app.query_one("#repo-creation-form-value-0"), SingleLineVimTextArea
        )
        assert isinstance(app.query_one("#repo-creation-form-value-1"), VimTextArea)
        assert isinstance(app.query_one("#repo-creation-form-value-2"), RadioSet)
        assert isinstance(app.query_one("#repo-creation-form-value-3"), Checkbox)
        assert isinstance(app.query_one("#repo-creation-form-value-4"), Button)
        assert form.raw_values["readme"] == "YES"
        assert app.query_one(
            "#repo-creation-form-capability", Static
        ).render().plain == ("Creation capability: available")
        assert form.message == "Owner capability is provider-supplied."
        assert form.remedy_argv == ("gh", "auth", "login")
        assert (
            "Owner capability"
            in app.query_one("#repo-creation-form-message", Static).render().plain
        )
        assert (
            "gh auth login"
            in app.query_one("#repo-creation-form-remedy", Static).render().plain
        )

        checkbox = app.query_one("#repo-creation-form-value-3", Checkbox)
        checkbox.focus()
        await pilot.press("space")
        await pilot.pause()
        assert form.raw_values["readme"] == "NO"

        details = app.query_one("#repo-creation-form-value-1", VimTextArea)
        details.text = "Updated details"
        await pilot.pause()
        assert form.raw_values["details"] == "Updated details"

        visibility = app.query_one("#repo-creation-form-value-2", RadioSet)
        await pilot.click(visibility.query(RadioButton)[0])
        await pilot.pause()
        assert form.raw_values["visibility"] == "public"


async def test_search_picker_accepts_typed_values_and_cancel_preserves_current() -> (
    None
):
    app = _FormApp(_template_form(), {"license": "MIT"})
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        app.query_one("#repo-creation-form-value-5", Button).press()
        await pilot.pause()
        picker = app.screen
        assert picker.__class__.__name__ == "RepoCreationSearchPicker"
        search = picker.query_one(Input)
        search.value = "Apache-2.0"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert form.raw_values["license"] == "Apache-2.0"

        app.query_one("#repo-creation-form-value-5", Button).press()
        await pilot.pause()
        search = app.screen.query_one(Input)
        search.value = "Customer/Policy"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert form.raw_values["license"] == "Customer/Policy"

        app.query_one("#repo-creation-form-value-5", Button).press()
        await pilot.pause()
        app.screen.query_one(Input).value = "not selected"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert form.raw_values["license"] == "Customer/Policy"


async def test_advanced_fields_collapse_without_dropping_values() -> None:
    app = _FormApp(_template_form(), {"template": "sase-org/base"})
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        advanced = app.query_one("#repo-creation-form-field-7")
        assert not advanced.display
        toggle = app.query_one("#repo-creation-form-advanced-toggle", Button)
        toggle.press()
        await pilot.pause()
        assert advanced.display
        editor = app.query_one("#repo-creation-form-value-7", SingleLineVimTextArea)
        editor.text = "sase-org/new-template"
        await pilot.pause()
        toggle.press()
        await pilot.pause()
        toggle.press()
        await pilot.pause()
        assert editor.text == "sase-org/new-template"
        assert form.raw_values["template"] == "sase-org/new-template"


async def test_advanced_hotkey_toggles_outside_editors_only() -> None:
    app = _FormApp(_template_form())
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        editor = app.query_one("#repo-creation-form-value-0", SingleLineVimTextArea)
        editor.focus()
        await pilot.press("a")
        await pilot.pause()
        assert not form.query_one("#repo-creation-form-field-7").display

        app.query_one("#repo-creation-form-value-3", Checkbox).focus()
        await pilot.press("a")
        await pilot.pause()
        assert form.query_one("#repo-creation-form-field-7").display


async def test_rust_evaluation_enforces_template_exclusions_and_requires() -> None:
    app = _FormApp(_template_form())
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        assert {"readme", "gitignore", "license", "team"} <= set(form.effective_options)
        fields = {item["name"]: item for item in form.evaluation["fields"]}
        assert not fields["include_all_branches"]["available"]
        assert (
            "requires template" in fields["include_all_branches"]["reason"].casefold()
        )

        form.set_values({"template": "sase-org/base"})
        await pilot.pause()
        for index in (3, 4, 5, 6):
            assert app.query_one(f"#repo-creation-form-value-{index}").disabled
        assert "template" in form.evaluation["fields"][3]["reason"].casefold()
        assert "readme" not in form.effective_options
        assert "gitignore" not in form.effective_options
        assert "license" not in form.effective_options
        assert "team" not in form.effective_options
        assert not app.query_one("#repo-creation-form-status-8", Static).display
        fields = {item["name"]: item for item in form.evaluation["fields"]}
        assert fields["include_all_branches"]["available"]

        form.set_values({"template": ""})
        await pilot.pause()
        for index in (3, 4, 5, 6):
            assert not app.query_one(f"#repo-creation-form-value-{index}").disabled


async def test_value_reconciliation_preserves_focused_editor_and_emits_one_change() -> (
    None
):
    app = _FormApp(_template_form())
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        editor = app.query_one("#repo-creation-form-value-0", SingleLineVimTextArea)
        editor.focus()
        editor.text = "currently edited"
        await pilot.pause()
        initial_events = app.change_events

        form.set_values(
            {"description": "stale external value", "details": "new details"}
        )
        await pilot.pause()
        assert editor.has_focus
        assert editor.text == "currently edited"
        assert form.raw_values["description"] == "currently edited"
        assert form.raw_values["details"] == "new details"
        assert app.change_events == initial_events + 1


async def test_static_field_restrictions_and_disabled_internal_choice_stay_visible() -> (
    None
):
    form_spec = _form(
        (
            RepoCreationField(
                name="visibility",
                label="Visibility",
                kind="choice",
                default="private",
                choices=(
                    RepoCreationChoice(value="private", label="Private"),
                    RepoCreationChoice(
                        value="internal",
                        label="Internal",
                        disabled_reason="Requires an enterprise plan.",
                    ),
                ),
            ),
            RepoCreationField(
                name="bare_dir",
                label="Bare path",
                kind="line",
                disabled_reason="This provider does not permit changing the path.",
            ),
        ),
        can_create=None,
    )
    app = _FormApp(form_spec)
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        radio_set = app.query_one("#repo-creation-form-value-0", RadioSet)
        internal = radio_set.query(RadioButton)[1]
        assert internal.disabled
        form_widget = app.query_one(RepoCreationFormWidget)
        assert any(
            "Requires an enterprise plan" in widget.render().plain
            for widget in form_widget.query(Static)
        )
        assert form.raw_values["visibility"] == "private"
        assert app.query_one(
            "#repo-creation-form-value-1", SingleLineVimTextArea
        ).disabled
        assert (
            "does not permit"
            in app.query_one("#repo-creation-form-status-1", Static).render().plain
        )
        assert form.can_create is None
        assert (
            "unknown"
            in app.query_one("#repo-creation-form-capability", Static).render().plain
        )


async def test_stale_controls_ready_after_detach_does_not_query_missing_controls() -> (
    None
):
    """Owner-switch remount used to raise NoMatches on #repo-creation-form-errors."""
    app = _FormApp(_template_form())
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        assert form._controls_ready
        form.remove_children()
        await pilot.pause()
        form._controls_ready = True
        form.set_values({"description": "after detach"})
        assert form.raw_values["description"] == "after detach"
        assert not form._controls_ready


async def test_remount_rearms_controls_ready_and_applies_pending_values() -> None:
    app = _FormApp(_template_form())
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(RepoCreationFormWidget)
        await form.remove()
        assert not form._controls_ready
        await app.mount(form)
        form.set_values({"description": "before compose refresh"})
        await pilot.pause()
        assert form._controls_ready
        editor = app.query_one("#repo-creation-form-value-0", SingleLineVimTextArea)
        assert editor.text == "before compose refresh"
        assert form.raw_values["description"] == "before compose refresh"
