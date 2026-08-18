"""Dedicated modal that collects one gate selection's typed inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from sase.ace.tui.widgets.typed_input_form import TypedInputForm
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.models import InputType, XPromptValidationError

from .gate_input_panel_model import (
    GateBranchInputError,
    GateInputDraft,
    GateInputRequest,
    collect_option_inputs,
)
from .gate_input_panel_sections import GateInputSection

_MODE_LABELS = {
    "insert": "INSERT",
    "normal": "NORMAL",
    "visual": "VISUAL",
    "visual_line": "V-LINE",
}


class _PanelVimModeMixin:
    """Route a panel editor's vim mode to the host screen when it wants it."""

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        try:
            setter = getattr(
                getattr(self, "screen", None), "_set_editor_mode_label", None
            )
        except Exception:
            setter = None
        if not callable(setter):
            super()._update_vim_mode_display(indicator)  # type: ignore[misc]
            return
        mode = _MODE_LABELS.get(getattr(self, "_vim_mode", ""), "")
        try:
            setter(mode, indicator)
        except Exception:
            super()._update_vim_mode_display(indicator)  # type: ignore[misc]


@dataclass(frozen=True)
class GateInputPanelResult:
    """Confirmed panel values for one branch selection."""

    option_inputs: dict[str, dict[str, Any]]
    feedback: str | None
    draft: GateInputDraft


class _NoteInput(_PanelVimModeMixin, VimTextArea):
    """Multi-line vim editor for the reviewer's note."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("tab_behavior", "focus")
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.show_line_numbers = False


class GateInputPanel(ModalScreen[GateInputPanelResult | None]):
    """Collect the typed inputs for one gate selection and submit or cancel."""

    BINDINGS = [
        Binding("tab", "next_input", "Next input", priority=True, show=False),
        Binding(
            "shift+tab", "previous_input", "Previous input", priority=True, show=False
        ),
        Binding("ctrl+s", "submit", "Submit", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    GateInputPanel {
        align: center middle;
    }
    GateInputPanel > #gate-input-container {
        width: 90%;
        max-width: 120;
        min-width: 56;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: double $accent;
        border-title-align: left;
        padding: 0 1;
    }
    GateInputPanel #gate-input-body {
        height: auto;
        max-height: 32;
        scrollbar-gutter: stable;
    }
    GateInputPanel .gate-input-section-title {
        height: auto;
        text-style: bold;
        margin-top: 1;
    }
    GateInputPanel .input-field-block {
        margin-bottom: 1;
    }
    GateInputPanel #gate-input-buttons {
        height: auto;
        align-horizontal: right;
    }
    GateInputPanel #gate-input-footer {
        height: auto;
        color: $text-muted;
        border-top: solid $secondary;
    }
    """

    def __init__(
        self,
        request: GateInputRequest,
        *,
        headline: str | None = None,
        kind: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__()
        self._request = request
        self._headline = headline or request.branch_label
        self._kind = kind
        self._request_id = request_id
        self._sections: list[GateInputSection] = []
        self._draft: GateInputDraft | None = None
        self._mode_label = ""
        self._mode_indicator = ""

    @property
    def draft(self) -> GateInputDraft:
        """Latest typed values, including a snapshot taken on cancel."""
        if self._draft is not None:
            return self._draft
        if self.is_mounted:
            return self.current_draft()
        return self._request.draft

    def current_draft(self) -> GateInputDraft:
        """Read the live widget state into a restoreable draft."""
        values: dict[str, str] = {}
        raw_text: dict[str, str] = {}
        for section in self._sections:
            values.update(section.values())
            if section.spec.raw_properties:
                raw_text[section.spec.option_id] = section.raw_text()
        feedback = self._request.draft.feedback
        if self._shows_note:
            feedback = self._note_text()
        elif self._request.feedback_field_owner is not None:
            feedback = values.get("feedback", feedback)
        return GateInputDraft(values=values, raw_text=raw_text, feedback=feedback)

    def compose(self) -> ComposeResult:
        options_by_id = {option.id: option for option in self._request.options}
        with Container(id="gate-input-container") as container:
            container.border_title = self._headline
            if self._kind and self._request_id:
                container.border_subtitle = f"{self._kind} gate · {self._request_id}"
            yield Static(self._header_text(), id="gate-input-header")
            with VerticalScroll(id="gate-input-body"):
                if self._request.conflict is not None:
                    yield Static(self._request.conflict, classes="gate-input-conflict")
                else:
                    for spec in self._request.sections:
                        section = GateInputSection(
                            spec,
                            options_by_id[spec.option_id],
                            draft_values=self._request.draft.values,
                            draft_raw_text=self._request.draft.raw_text.get(
                                spec.option_id
                            ),
                        )
                        self._sections.append(section)
                        yield section
                    if self._shows_note:
                        yield from self._compose_note()
            yield Static(self._progress_text(), id="gate-input-progress")
            with Horizontal(id="gate-input-buttons"):
                if self._request.conflict is None:
                    yield Button(
                        self._request.branch_label,
                        id="gate-input-submit",
                        variant="success",
                    )
                yield Button("Cancel", id="gate-input-cancel", variant="default")
            yield Static(self._footer_text(), id="gate-input-footer")

    def _compose_note(self) -> ComposeResult:
        mode = "required" if self._request.feedback_mode == "required" else "optional"
        yield Static(f"Note    {mode}", classes="gate-input-section-title")
        yield _NoteInput(self._request.draft.feedback, id="gate-input-note")

    def on_mount(self) -> None:
        self._refresh_submit_state()
        if not self._focus_first_invalid():
            self._focus_first()

    def on_typed_input_form_changed(self, event: TypedInputForm.Changed) -> None:
        self._refresh_submit_state()

    def on_typed_input_form_submitted(self, event: TypedInputForm.Submitted) -> None:
        event.stop()
        index = next(
            (
                offset
                for offset, section in enumerate(self._sections)
                if section.owns_form(event.control)
            ),
            len(self._sections) - 1,
        )
        next_index = index + 1
        if 0 <= next_index < len(self._sections):
            if self._sections[next_index].focus_first():
                return
        if self._shows_note:
            self.query_one("#gate-input-note", VimTextArea).focus()
            return
        self.action_submit()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._refresh_submit_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gate-input-submit":
            event.stop()
            self.action_submit()
        elif event.button.id == "gate-input-cancel":
            event.stop()
            self.action_cancel()

    def action_next_input(self) -> None:
        self._step_input_focus(1)

    def action_previous_input(self) -> None:
        self._step_input_focus(-1)

    def action_submit(self) -> None:
        if self._request.conflict is not None:
            return
        if not self._is_valid():
            self._focus_first_invalid()
            self.notify(
                "Fix the highlighted inputs before submitting", severity="warning"
            )
            return
        try:
            option_inputs = collect_option_inputs(
                self._request, self._typed_values(), self._raw_values()
            )
        except (GateBranchInputError, XPromptValidationError) as exc:
            self.notify(str(exc), severity="warning")
            self._focus_first_invalid()
            return
        draft = self.current_draft()
        self._draft = draft
        self.dismiss(
            GateInputPanelResult(
                option_inputs=option_inputs,
                feedback=self._result_feedback(),
                draft=draft,
            )
        )

    def action_cancel(self) -> None:
        if self.is_mounted:
            self._draft = self.current_draft()
        self.dismiss(None)

    def _set_editor_mode_label(self, mode: str, indicator: str = "") -> None:
        self._mode_label = mode
        self._mode_indicator = indicator
        try:
            self.query_one("#gate-input-footer", Static).update(
                self._footer_text(mode, indicator)
            )
        except Exception:
            pass

    def _control_ids(self) -> list[str]:
        ids: list[str] = []
        for section in self._sections:
            ids.extend(section.control_ids())
        if self._shows_note:
            ids.append("gate-input-note")
        if self._request.conflict is None:
            ids.append("gate-input-submit")
        ids.append("gate-input-cancel")
        return ids

    def _step_input_focus(self, delta: int) -> None:
        ids = self._control_ids()
        if not ids:
            return
        focused = self.focused
        focused_id = focused.id if focused is not None else None
        try:
            current = ids.index(focused_id or "")
        except ValueError:
            current = -1 if delta > 0 else 0
        for step in range(1, len(ids) + 1):
            target = self.query_one(f"#{ids[(current + delta * step) % len(ids)]}")
            if getattr(target, "disabled", False):
                continue
            target.focus()
            return

    def _focus_first(self) -> None:
        ids = self._control_ids()
        if ids:
            self.query_one(f"#{ids[0]}").focus()

    def _focus_first_invalid(self) -> bool:
        for section in self._sections:
            if not section.is_valid() and section.focus_first_invalid():
                return True
        if (
            self._shows_note
            and self._request.feedback_mode == "required"
            and not self._note_text().strip()
        ):
            self.query_one("#gate-input-note", VimTextArea).focus()
            return True
        return False

    def _is_valid(self) -> bool:
        if self._request.conflict is not None:
            return False
        if not all(section.is_valid() for section in self._sections):
            return False
        if (
            self._shows_note
            and self._request.feedback_mode == "required"
            and not self._note_text().strip()
        ):
            return False
        return True

    def _typed_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for section in self._sections:
            values.update(section.typed_values())
        return values

    def _raw_values(self) -> dict[str, str]:
        return {
            section.spec.option_id: section.raw_text()
            for section in self._sections
            if section.spec.raw_properties
        }

    def _result_feedback(self) -> str | None:
        if self._request.feedback_field_owner is not None:
            value = self._typed_values().get("feedback")
            if value is None:
                return None
            text = str(value).strip()
            return text or None
        if not self._shows_note:
            return None
        text = self._note_text().strip()
        return text or None

    def _note_text(self) -> str:
        try:
            return self.query_one("#gate-input-note", VimTextArea).text
        except Exception:
            return self._request.draft.feedback

    def _header_text(self) -> str:
        if len(self._request.sections) == 1:
            spec = self._request.sections[0]
            icon = f"{spec.icon} " if spec.icon else ""
            return f"{icon}{spec.label}"
        return self._request.branch_label

    def _progress_text(self) -> str:
        filled = 0
        total = 0
        for section in self._sections:
            section_filled, section_total = section.required_progress()
            filled += section_filled
            total += section_total
        if self._shows_note and self._request.feedback_mode == "required":
            total += 1
            if self._note_text().strip():
                filled += 1
        if total == 0:
            return ""
        if filled == total:
            return "all required filled"
        return f"{filled} of {total} required filled"

    def _refresh_submit_state(self) -> None:
        try:
            self.query_one("#gate-input-progress", Static).update(self._progress_text())
        except Exception:
            pass
        try:
            submit = self.query_one("#gate-input-submit", Button)
        except Exception:
            return
        submit.disabled = not self._is_valid()

    def _footer_text(self, mode: str = "", indicator: str = "") -> str:
        parts = ["<tab>/<shift+tab> field", "^s submit", "<esc> back"]
        if self._has_path_field():
            parts.append("^t complete path")
        chip = mode or self._mode_label
        suffix = indicator or self._mode_indicator
        if suffix:
            chip = f"{chip} {suffix}".strip()
        left = "   ".join(parts)
        if chip:
            return f"{left}      {chip}"
        return left

    def _has_path_field(self) -> bool:
        return any(
            field.type is InputType.PATH
            for section in self._request.sections
            for field in section.fields
        )

    @property
    def _shows_note(self) -> bool:
        return (
            self._request.conflict is None
            and self._request.feedback_mode != "disabled"
            and self._request.feedback_field_owner is None
        )


__all__ = ["GateInputPanel", "GateInputPanelResult"]
