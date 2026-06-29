"""Rendering base class for the config edit modal."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static, TextArea

from sase.config import AppliedResult, ConfigField, ConfigSource, EditPlanResult

from .config_edit_helpers import (
    format_value,
    format_value_for_editor,
    list_strategy_banner,
    scope_label,
)
from .config_edit_types import (
    EditorKind,
    Stage,
    _ACCENT,
    _ERR_COLOR,
    _MOD_COLOR,
    _MUTED,
    _OK_COLOR,
    _WARN_COLOR,
)


class ConfigEditModalBase(ModalScreen["AppliedResult | None"]):
    """Shared rendering and widget wiring for ``ConfigEditModal``."""

    _field: ConfigField | None
    _stage: Stage
    _editor_kind: EditorKind
    _op_unset: bool
    _error: str | None
    _status: str | None
    _busy: bool
    _plan: EditPlanResult | None
    _bool_value: bool
    _enum_index: int
    _initial_value: Any

    def compose(self) -> ComposeResult:
        # Only the editor widget the field actually needs is mounted (so a
        # hidden Input/TextArea can't steal focus from key-driven editors), and
        # it is seeded here because a Screen's on_mount can fire early.
        seed = format_value_for_editor(self._editor_kind, self._initial_value)
        with Container(id="config-edit-container"):
            yield Label("", id="config-edit-title")
            yield Static("", id="config-edit-info", markup=False)
            yield Static("", id="config-edit-scope", markup=False)
            yield Static("", id="config-edit-banner", markup=False)
            yield Static("", id="config-edit-value", markup=False)
            if self._uses_input():
                yield Input(value=seed, id="config-edit-input")
            elif self._uses_textarea():
                yield TextArea(seed, id="config-edit-textarea", show_line_numbers=False)
            yield Static("", id="config-edit-error", markup=False)
            with VerticalScroll(id="config-edit-preview-scroll"):
                yield Static("", id="config-edit-preview", markup=False)
            yield Static("", id="config-edit-hints", markup=False)

    def _uses_input(self) -> bool:
        return self._editor_kind in ("int", "number", "string")

    def _uses_textarea(self) -> bool:
        return self._editor_kind in ("string_list", "yaml")

    def _focus_editor(self) -> None:
        """Focus the editor widget, or blur so the screen handles key bindings."""
        if self._stage != "edit" or self._op_unset:
            self.set_focus(None)
            return
        try:
            if self._uses_input():
                self.query_one("#config-edit-input", Input).focus()
            elif self._uses_textarea():
                self.query_one("#config-edit-textarea", TextArea).focus()
            else:
                self.set_focus(None)
        except Exception:
            self.set_focus(None)

    def _render_all(self) -> None:
        self._update("#config-edit-title", self._title())
        self._update("#config-edit-info", self._info_text())
        self._update("#config-edit-scope", self._scope_text())
        self._update("#config-edit-banner", self._banner_text())
        self._update("#config-edit-value", self._value_text())
        self._update("#config-edit-error", self._error_text())
        self._update("#config-edit-preview", self._preview_text())
        self._update("#config-edit-hints", self._hints())
        self._sync_visibility()

    def _update(self, selector: str, content: Text | str) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _sync_visibility(self) -> None:
        edit_stage = self._stage == "edit"
        show_input = edit_stage and not self._op_unset and self._uses_input()
        show_area = edit_stage and not self._op_unset and self._uses_textarea()
        for selector, visible in (
            ("#config-edit-input", show_input),
            ("#config-edit-textarea", show_area),
            ("#config-edit-preview-scroll", self._stage == "preview"),
        ):
            try:
                self.query_one(selector).display = visible
            except Exception:
                pass
        # The list-strategy banner is only meaningful for list fields.
        try:
            field = self._field
            is_list = field is not None and field.kind == "array"
            self.query_one("#config-edit-banner", Static).display = (
                edit_stage and is_list
            )
        except Exception:
            pass

    def _title(self) -> Text:
        text = Text()
        text.append("Edit  ", style="bold")
        if self._field is not None:
            text.append(self._field.path, style=f"bold {_ACCENT}")
        return text

    def _info_text(self) -> Text:
        text = Text()
        field = self._field
        if field is None:
            return text
        type_label = "/".join(field.types) if field.types else field.kind
        text.append("type: ", style=_MUTED)
        text.append(type_label or "—")
        if field.enum_values:
            text.append("  enum: ", style=_MUTED)
            text.append(", ".join(format_value(v) for v in field.enum_values))
        constraint = self._constraint_hint(field)
        if constraint:
            text.append(f"  {constraint}", style=_MUTED)
        text.append("\n")
        if field.has_default:
            text.append("default: ", style=_MUTED)
            text.append(format_value(field.default))
        if field.description:
            text.append(f"\n{field.description}", style=_MUTED)
        return text

    @staticmethod
    def _constraint_hint(field: ConfigField) -> str:
        constraints = field.constraints
        parts: list[str] = []
        if constraints.minimum is not None:
            parts.append(f"≥{constraints.minimum:g}")
        if constraints.maximum is not None:
            parts.append(f"≤{constraints.maximum:g}")
        if constraints.exclusive_minimum is not None:
            parts.append(f">{constraints.exclusive_minimum:g}")
        if constraints.exclusive_maximum is not None:
            parts.append(f"<{constraints.exclusive_maximum:g}")
        return f"[{', '.join(parts)}]" if parts else ""

    def _scope_text(self) -> Text:
        text = Text()
        text.append("scope: ", style=_MUTED)
        source = self._target_source()
        if source is None:
            text.append("no writable target available", style=_ERR_COLOR)
            return text
        text.append_text(scope_label(source))
        if source.path:
            text.append(f"\n       {source.path}", style=f"dim {_MUTED}")
        writable = self._writable_sources()
        if len(writable) > 1:
            text.append(f"   [ctrl+t: {len(writable)} targets]", style=f"dim {_MUTED}")
        return text

    def _banner_text(self) -> Text:
        source = self._target_source()
        if source is None or self._field is None or self._field.kind != "array":
            return Text("")
        return list_strategy_banner(source)

    def _value_text(self) -> Text:
        text = Text()
        if self._op_unset:
            text.append("reset to default", style=f"bold {_MOD_COLOR}")
            field = self._field
            text.append("  → ", style=_MUTED)
            if field is not None and field.has_default:
                text.append(format_value(field.default))
            else:
                text.append("(unset)", style=f"italic {_MUTED}")
            text.append("\n(removes the key from the chosen scope)", style=_MUTED)
            return text
        if self._editor_kind == "bool":
            text.append("value: ", style=_MUTED)
            text.append(
                "true" if self._bool_value else "false",
                style=f"bold {_OK_COLOR if self._bool_value else _MUTED}",
            )
            text.append("   [space: toggle]", style=f"dim {_MUTED}")
        elif self._editor_kind == "enum":
            field = self._field
            values = list(field.enum_values) if field is not None else []
            current = values[self._enum_index] if values else None
            text.append("value: ", style=_MUTED)
            text.append(format_value(current), style=f"bold {_ACCENT}")
            text.append("   [space: next option]", style=f"dim {_MUTED}")
        return text

    def _error_text(self) -> Text:
        if self._error:
            return Text(f"✗ {self._error}", style=_ERR_COLOR)
        if self._status:
            return Text(self._status, style=_MUTED)
        return Text("")

    def _preview_text(self) -> Text:
        if self._stage != "preview":
            return Text("")
        if self._busy and self._plan is None:
            return Text("Planning…", style=_MUTED)
        plan = self._plan
        if plan is None:
            return Text("")
        text = Text()
        text.append("Target file\n", style="bold")
        text.append(f"  {plan.target_path or '(none)'}", style=_ACCENT)
        if plan.used_chezmoi:
            text.append("  (chezmoi source)", style=_MUTED)
        text.append("\n\n")
        self._append_effective(plan, text)
        self._append_validation(plan, text)
        self._append_diff(plan, text)
        return text

    def _append_effective(self, plan: EditPlanResult, text: Text) -> None:
        preview = plan.effective_preview
        text.append("Effective value", style="bold")
        text.append("  (after merge)\n", style=_MUTED)
        text.append("  ")
        text.append(
            format_value(preview.before) if preview.has_before else "(unset)",
            style=_MUTED,
        )
        text.append("  →  ", style=_MUTED)
        text.append(
            format_value(preview.after) if preview.has_after else "(unset)",
            style=f"bold {_OK_COLOR if preview.changed else _MUTED}",
        )
        text.append("\n\n")

    def _append_validation(self, plan: EditPlanResult, text: Text) -> None:
        issues = [*plan.validation, *plan.diagnostics]
        if not issues:
            text.append("Validation: ", style="bold")
            text.append("ok\n\n", style=_OK_COLOR)
            return
        text.append("Validation\n", style="bold")
        for diagnostic in issues:
            color = _ERR_COLOR if diagnostic.severity == "error" else _WARN_COLOR
            text.append(f"  {diagnostic.severity}: ", style=color)
            text.append(diagnostic.message, style=_MUTED)
            if diagnostic.path:
                text.append(f" [{diagnostic.path}]", style=f"dim {_MUTED}")
            text.append("\n")
        text.append("\n")

    def _append_diff(self, plan: EditPlanResult, text: Text) -> None:
        text.append("Diff\n", style="bold")
        if not plan.text_diff.strip():
            text.append("  (no changes — value already effective)\n", style=_MUTED)
            return
        for line in plan.text_diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                style = _OK_COLOR
            elif line.startswith("-") and not line.startswith("---"):
                style = _ERR_COLOR
            elif line.startswith("@@"):
                style = _ACCENT
            else:
                style = _MUTED
            text.append(f"  {line}\n", style=style)

    def _hints(self) -> str:
        if self._stage == "preview":
            if self._busy:
                return "writing…"
            return "enter / ctrl+s: write   esc: back   "
        toggle = ""
        if self._editor_kind in ("bool", "enum"):
            toggle = "space: change  "
        reset = "ctrl+r: un-reset" if self._op_unset else "ctrl+r: reset"
        return (
            f"{toggle}ctrl+t: scope  ctrl+n: new overlay  {reset}  "
            "ctrl+s: preview  esc: cancel"
        )

    def _writable_sources(self) -> list[ConfigSource]:
        raise NotImplementedError

    def _target_source(self) -> ConfigSource | None:
        raise NotImplementedError
