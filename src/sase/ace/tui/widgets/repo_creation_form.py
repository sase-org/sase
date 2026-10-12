"""Standalone provider-driven repository creation form for the New Project flow.

The widget intentionally has no production wizard entry point yet. Provider
fields are rendered in declaration order, while all availability, dependency,
and exclusion decisions come from the Rust project-onboarding evaluator.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Checkbox, RadioButton, RadioSet, Static, TextArea

from sase.core.project_onboarding_facade import evaluate_repo_creation_form
from sase.workspace_provider._hookspec import RepoCreationField, RepoCreationForm

from ..modals.new_project_rendering import clean_source_text
from .repo_creation_form_controls import (
    RepoCreationLineEditor,
    RepoCreationSearchPicker,
    RepoCreationTextEditor,
    bool_is_true,
    boolean_spellings,
    choice_label,
    search_button_text,
)
from .single_line_vim_text_area import SingleLineVimTextArea
from .vim_text_area import VimTextArea


class RepoCreationFormWidget(VerticalScroll):
    """Render provider fields and expose the Rust lenient evaluation result."""

    class Changed(Message):
        """Raw provider values changed; the host can read the latest evaluation."""

        @property
        def control(self) -> RepoCreationFormWidget:
            sender = self._sender
            assert isinstance(sender, RepoCreationFormWidget)
            return sender

    DEFAULT_CSS = """
    RepoCreationFormWidget {
        height: 1fr;
        padding: 0 1;
    }
    .repo-creation-form-heading {
        text-style: bold;
        color: $secondary;
        margin: 1 0 0 0;
    }
    .repo-creation-form-message {
        height: auto;
        color: $text-muted;
    }
    .repo-creation-form-capability {
        height: auto;
        text-style: bold;
    }
    .repo-creation-form-errors {
        color: $error;
        height: auto;
    }
    .repo-creation-form-field {
        height: auto;
        margin-bottom: 1;
    }
    .repo-creation-form-field-label {
        text-style: bold;
        color: $secondary;
    }
    .repo-creation-form-description,
    .repo-creation-form-status,
    .repo-creation-form-choice-reason {
        color: $text-muted;
        height: auto;
    }
    .repo-creation-form-status {
        color: $warning;
    }
    .repo-creation-form-choice-reason {
        margin-left: 2;
    }
    .repo-creation-form-choice-set {
        layout: horizontal;
        height: auto;
        max-height: 7;
        border: none;
        padding: 0;
        background: transparent;
    }
    .repo-creation-form-choice-set > RadioButton {
        width: auto;
        max-width: 1fr;
        padding-right: 2;
    }
    .repo-creation-form-bool {
        width: auto;
        height: 1;
        border: none;
        padding: 0;
    }
    .repo-creation-form-search {
        width: 100%;
        height: 3;
        content-align: left middle;
        padding: 0 1;
    }
    #repo-creation-form-advanced-toggle {
        width: 100%;
        height: 1;
        border: none;
        padding: 0 1;
        content-align: left middle;
    }
    """

    def __init__(
        self,
        form: RepoCreationForm,
        values: dict[str, str] | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._form = form
        self._fields = tuple(form.fields)
        self._fields_by_name = {field.name: field for field in self._fields}
        self._raw_values = {field.name: str(field.default) for field in self._fields}
        if values:
            for name, value in values.items():
                if name in self._fields_by_name:
                    self._raw_values[name] = str(value)
        self._advanced_expanded = False
        self._synchronizing = False
        self._evaluation: dict[str, Any] = {}
        self._evaluate()

    @property
    def form(self) -> RepoCreationForm:
        """Provider form rendered by this widget."""
        return self._form

    @property
    def raw_values(self) -> dict[str, str]:
        """Copy of the full raw value map, including unavailable field values."""
        return dict(self._raw_values)

    @property
    def values(self) -> dict[str, str]:
        """Alias for :attr:`raw_values`."""
        return self.raw_values

    @property
    def evaluation(self) -> dict[str, Any]:
        """Latest lenient Rust evaluation."""
        return dict(self._evaluation)

    @property
    def effective_options(self) -> dict[str, str]:
        """Canonical provider options returned by the Rust evaluator."""
        raw = self._evaluation.get("effective_options")
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items()}

    @property
    def can_create(self) -> bool | None:
        """Provider capability; ``None`` means unknown, not denied."""
        return self._form.can_create

    @property
    def message(self) -> str:
        """Provider-supplied capability message, cleaned for display."""
        return clean_source_text(self._form.message)

    @property
    def remedy_argv(self) -> tuple[str, ...]:
        """Provider-supplied remediation command, retained as argv tokens."""
        return tuple(clean_source_text(item) for item in self._form.remedy_argv)

    def compose(self) -> ComposeResult:
        capability = {
            True: "Creation capability: available",
            False: "Creation capability: unavailable",
            None: "Creation capability: unknown",
        }[self._form.can_create]
        yield Static(
            Text(capability),
            id="repo-creation-form-capability",
            classes="repo-creation-form-capability",
        )
        if self._form.message:
            yield Static(
                Text(clean_source_text(self._form.message)),
                id="repo-creation-form-message",
                classes="repo-creation-form-message",
            )
        if self._form.remedy_argv:
            remedy = " ".join(
                clean_source_text(item) for item in self._form.remedy_argv
            )
            yield Static(
                Text(f"Remedy: {remedy}"),
                id="repo-creation-form-remedy",
                classes="repo-creation-form-message",
            )
        yield Static(
            "", id="repo-creation-form-errors", classes="repo-creation-form-errors"
        )

        last_group: str | None = None
        advanced_toggle_added = False
        for index, field in enumerate(self._fields):
            group = field.group
            if group != last_group:
                yield Static(
                    Text("ADVANCED" if group == "advanced" else "BASICS"),
                    classes="repo-creation-form-heading",
                )
                last_group = group
            if group == "advanced" and not advanced_toggle_added:
                yield Button(
                    self._advanced_toggle_text(),
                    id="repo-creation-form-advanced-toggle",
                    variant="default",
                )
                advanced_toggle_added = True
            yield self._compose_field(index, field)

    def set_values(self, values: dict[str, str]) -> None:
        """Reconcile values without replacing the text in a focused editor."""
        updated = dict(self._raw_values)
        for name, value in values.items():
            if name in self._fields_by_name:
                updated[name] = str(value)
        if self.is_mounted:
            focused = self.app.focused
            if isinstance(focused, (SingleLineVimTextArea, VimTextArea)):
                field_name = self._field_name_from_id(focused.id)
                if field_name is not None:
                    updated[field_name] = self._editor_text(focused)
        self._synchronizing = True
        try:
            if self.is_mounted:
                for index, field in enumerate(self._fields):
                    if updated[field.name] == self._raw_values[field.name]:
                        continue
                    if self._is_focused_field(field.name):
                        continue
                    self._set_control_value(index, field, updated[field.name])
            self._raw_values = updated
        finally:
            self._synchronizing = False
        self._recompute_and_notify()

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_evaluation_view)

    def on_key(self, event: events.Key) -> None:
        if event.character != "a":
            return
        focused = self.app.focused
        if isinstance(focused, (SingleLineVimTextArea, VimTextArea)):
            return
        event.prevent_default()
        event.stop()
        self._toggle_advanced()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self._synchronizing:
            return
        field_name = self._field_name_from_id(event.control.id)
        if field_name is not None:
            self._record_value(field_name, self._editor_text(event.control))

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._synchronizing:
            return
        field_name = self._field_name_from_id(event.checkbox.id)
        if field_name is None:
            return
        current = self._raw_values.get(field_name, "")
        true_value, false_value = boolean_spellings(current)
        self._record_value(field_name, true_value if event.value else false_value)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if self._synchronizing:
            return
        field_name = self._field_name_from_id(event.radio_set.id)
        if field_name is None or not 0 <= event.index < len(
            self._fields_by_name[field_name].choices
        ):
            return
        self._record_value(
            field_name,
            self._fields_by_name[field_name].choices[event.index].value,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repo-creation-form-advanced-toggle":
            self._toggle_advanced()
            return
        field_name = self._field_name_from_id(event.button.id)
        if field_name is None:
            return
        field = self._fields_by_name[field_name]
        if field.kind != "search":
            return
        picker = RepoCreationSearchPicker(
            field.label,
            field.choices,
            current=self._raw_values.get(field.name, ""),
        )
        index = self._field_index(field.name)
        self.app.push_screen(picker, lambda value: self._search_selected(index, value))

    def _compose_field(self, index: int, field: RepoCreationField) -> Vertical:
        header = clean_source_text(field.label)
        if field.required:
            header += " *"
        children: list[Any] = [
            Static(Text(header), classes="repo-creation-form-field-label")
        ]
        if field.description:
            children.append(
                Static(
                    Text(clean_source_text(field.description)),
                    classes="repo-creation-form-description",
                )
            )
        value_id = f"repo-creation-form-value-{index}"
        value = self._raw_values.get(field.name, "")
        if field.kind == "line":
            control: Any = RepoCreationLineEditor(
                value,
                placeholder=clean_source_text(field.placeholder),
                id=value_id,
            )
        elif field.kind == "text":
            control = RepoCreationTextEditor(
                value,
                placeholder=clean_source_text(field.placeholder),
                id=value_id,
            )
        elif field.kind == "bool":
            control = Checkbox(
                Text(clean_source_text(field.label)),
                value=bool_is_true(value),
                id=value_id,
                classes="repo-creation-form-bool",
            )
        elif field.kind == "choice":
            buttons = tuple(
                RadioButton(
                    choice_label(choice),
                    value=choice.value == value,
                    disabled=bool(choice.disabled_reason),
                )
                for choice in field.choices
            )
            control = RadioSet(
                *buttons,
                id=value_id,
                classes="repo-creation-form-choice-set",
                compact=True,
            )
        elif field.kind == "search":
            control = Button(
                search_button_text(value),
                id=value_id,
                classes="repo-creation-form-search",
                variant="default",
            )
        else:
            control = Static(
                Text(f"Unsupported field kind: {clean_source_text(field.kind)}")
            )
        children.append(control)
        for choice in field.choices:
            if choice.disabled_reason:
                label = clean_source_text(choice.label or choice.value)
                reason = clean_source_text(choice.disabled_reason)
                children.append(
                    Static(
                        Text(f"{label}: unavailable · {reason}"),
                        classes="repo-creation-form-choice-reason",
                    )
                )
        status = Static(
            "",
            id=f"repo-creation-form-status-{index}",
            classes="repo-creation-form-status",
        )
        status.display = False
        children.append(status)
        block = Vertical(
            *children,
            id=f"repo-creation-form-field-{index}",
            classes="repo-creation-form-field",
        )
        if field.group == "advanced":
            block.display = False
        return block

    def _set_control_value(
        self, index: int, field: RepoCreationField, value: str
    ) -> None:
        control_id = f"repo-creation-form-value-{index}"
        if field.kind in {"line", "text"}:
            control = self.query_one(f"#{control_id}")
            if isinstance(control, (SingleLineVimTextArea, VimTextArea)):
                self._set_editor_text(control, value)
        elif field.kind == "bool":
            self.query_one(f"#{control_id}", Checkbox).value = bool_is_true(value)
        elif field.kind == "choice":
            radio_set = self.query_one(f"#{control_id}", RadioSet)
            for choice_index, choice in enumerate(field.choices):
                button = radio_set.query(RadioButton)[choice_index]
                button.value = choice.value == value
        elif field.kind == "search":
            self.query_one(f"#{control_id}", Button).label = search_button_text(value)

    def _record_value(self, name: str, value: str) -> None:
        if self._synchronizing or self._raw_values.get(name) == value:
            return
        self._raw_values[name] = value
        self._recompute_and_notify()

    def _search_selected(self, index: int, value: str | None) -> None:
        if value is None:
            return
        field = self._fields[index]
        self._raw_values[field.name] = value
        if self.is_mounted:
            self.query_one(
                f"#repo-creation-form-value-{index}", Button
            ).label = search_button_text(value)
        self._recompute_and_notify()

    def _recompute_and_notify(self) -> None:
        self._evaluate()
        if self.is_mounted:
            self._refresh_evaluation_view()
        self.post_message(self.Changed())

    def _evaluate(self) -> None:
        try:
            self._evaluation = evaluate_repo_creation_form(
                asdict(self._form), self._raw_values, "lenient"
            )
        except Exception as exc:
            self._evaluation = {
                "valid": False,
                "fields": [],
                "effective_options": {},
                "errors": [
                    {
                        "field": "",
                        "code": "evaluation_unavailable",
                        "message": f"Could not evaluate provider options: {exc}",
                    }
                ],
            }

    def _refresh_evaluation_view(self) -> None:
        if not self.is_mounted:
            return
        evaluated = {
            str(item.get("name") or ""): item
            for item in self._evaluation.get("fields", [])
            if isinstance(item, dict)
        }
        errors_by_field: dict[str, list[str]] = {}
        global_errors: list[str] = []
        for error in self._evaluation.get("errors", []):
            if not isinstance(error, dict):
                continue
            message = clean_source_text(error.get("message", ""))
            field_name = str(error.get("field") or "")
            if not message:
                continue
            if field_name:
                errors_by_field.setdefault(field_name, []).append(message)
            else:
                global_errors.append(message)
        self.query_one("#repo-creation-form-errors", Static).update(
            Text("\n".join(global_errors))
        )
        for index, field in enumerate(self._fields):
            result = evaluated.get(field.name, {})
            available = bool(result.get("available", not field.disabled_reason))
            reason = clean_source_text(
                result.get("reason") or field.disabled_reason or ""
            )
            messages = errors_by_field.get(field.name, [])
            status_text = "\n".join([item for item in (reason, *messages) if item])
            status = self.query_one(f"#repo-creation-form-status-{index}", Static)
            status.update(Text(status_text))
            status.display = bool(status_text)
            control = self.query_one(f"#repo-creation-form-value-{index}")
            control.disabled = not available
            if field.kind == "choice":
                for choice_index, choice in enumerate(field.choices):
                    button = self.query_one(f"#{control.id}", RadioSet).query(
                        RadioButton
                    )[choice_index]
                    button.disabled = (not available) or bool(choice.disabled_reason)
        self._apply_advanced_visibility()

    def _apply_advanced_visibility(self) -> None:
        if not self.is_mounted:
            return
        advanced_count = sum(field.group == "advanced" for field in self._fields)
        toggle = (
            self.query_one("#repo-creation-form-advanced-toggle", Button)
            if advanced_count
            else None
        )
        if toggle is not None:
            toggle.label = self._advanced_toggle_text()
        for index, field in enumerate(self._fields):
            if field.group == "advanced":
                self.query_one(
                    f"#repo-creation-form-field-{index}"
                ).display = self._advanced_expanded

    def _advanced_toggle_text(self) -> Text:
        count = sum(field.group == "advanced" for field in self._fields)
        state = "expanded" if self._advanced_expanded else "collapsed"
        return Text(f"Advanced ({count} fields) · {state} · press a")

    def _toggle_advanced(self) -> None:
        self._advanced_expanded = not self._advanced_expanded
        self._apply_advanced_visibility()

    def _field_index(self, name: str) -> int:
        return next(
            index for index, field in enumerate(self._fields) if field.name == name
        )

    def _field_name_from_id(self, widget_id: str | None) -> str | None:
        if not widget_id or not widget_id.startswith("repo-creation-form-value-"):
            return None
        try:
            index = int(widget_id.rsplit("-", 1)[1])
        except ValueError:
            return None
        return self._fields[index].name if 0 <= index < len(self._fields) else None

    def _is_focused_field(self, name: str) -> bool:
        focused = self.app.focused
        return self._field_name_from_id(getattr(focused, "id", None)) == name

    @staticmethod
    def _editor_text(editor: Any) -> str:
        return str(getattr(editor, "text", ""))

    @staticmethod
    def _set_editor_text(editor: Any, value: str) -> None:
        if editor.text != value:
            editor.text = value
            lines = value.splitlines() or [""]
            editor.move_cursor((len(lines) - 1, len(lines[-1])))


__all__ = ["RepoCreationFormWidget"]
