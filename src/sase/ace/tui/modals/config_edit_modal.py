"""Edit / validate / write flow for the Config Center's Config tab (Phase 5).

Phase 4 made the Config tab a read-only browser. This module adds the editing
half: a modal that answers the panel's fourth question — *where will my edit go,
will it validate, and when does it take effect* — and then performs a safe,
reversible, source-preserving write.

:class:`ConfigEditModal` is a two-stage modal:

- **edit** — pick a writable **scope** (user base / an existing or freshly
  created overlay / a selected local file), choose a **value** with a typed
  editor generated from the field's schema (boolean toggle, enum option cycle,
  validated number, string input, string-list lines, or a raw-YAML escape hatch
  for complex shapes), or **reset to default** (delete the key from the scope).
  A banner states the list merge consequence (replace vs. append) for the chosen
  scope.
- **preview** — the planned per-file text diff, the effective-merge preview
  (computed by the Rust backend, never re-implemented here), and the candidate
  validation. Writing is blocked while the candidate has schema errors or there
  is nothing to change.

All heavy work runs off the Textual event loop: planning (Rust call + reading
the target file) runs in a worker, and the source-preserving write (plus a
scoped ``chezmoi apply`` for chezmoi-managed targets) runs in a tracked worker.
The modal dismisses with the :class:`~sase.config.AppliedResult` on a successful
write, or ``None`` on cancel.

A second entry point, :meth:`ConfigEditModal.for_migration`, reuses the preview/
write stage for the one-key ``sibling_repos`` → ``linked_repos`` migration.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static, TextArea
from textual.worker import Worker, WorkerState

from sase.config import (
    AppliedResult,
    ConfigEditError,
    ConfigEditOp,
    ConfigField,
    ConfigInventory,
    ConfigSource,
    EditPlanResult,
    apply_chezmoi,
    apply_config_edit,
    default_target_layer,
    inventory_with_new_overlay,
    plan_config_edit,
    plan_repo_key_migration,
)


if TYPE_CHECKING:
    from sase.ace.tui.modals.config_pane import ConfigPaneView


EditorKind = Literal["bool", "enum", "int", "number", "string", "string_list", "yaml"]
Stage = Literal["edit", "preview"]
Mode = Literal["field", "migration"]

_OK_COLOR = "#5FAF5F"
_ERR_COLOR = "#FF8787"
_WARN_COLOR = "#FFAF5F"
_ACCENT = "#00D7AF"
_MUTED = "#888888"
_MOD_COLOR = "#FFD700"


# --- Pure schema / value helpers (no Textual app required) -----------------


def _deref(schema_root: dict[str, Any], node: Any, _depth: int = 0) -> Any:
    """Resolve a local ``$ref`` against *schema_root* (best-effort)."""
    if not isinstance(node, dict) or _depth > 16:
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        target: Any = schema_root
        for part in ref[2:].split("/"):
            if not isinstance(target, dict):
                return node
            target = target.get(part)
            if target is None:
                return node
        return _deref(schema_root, target, _depth + 1)
    return node


def _schema_node_for_path(schema_root: dict[str, Any], path: str) -> Any:
    """Walk ``properties`` to the schema node for the dotted *path*, or None."""
    node: Any = schema_root
    for segment in path.split("."):
        node = _deref(schema_root, node)
        if not isinstance(node, dict):
            return None
        props = node.get("properties")
        if not isinstance(props, dict):
            return None
        node = props.get(segment)
        if node is None:
            return None
    return node


def _array_item_type(schema_root: dict[str, Any], path: str) -> str | None:
    """The declared ``items.type`` for the array field at *path*, if any."""
    node = _schema_node_for_path(schema_root, path)
    if node is None:
        return None
    node = _deref(schema_root, node)
    items = node.get("items") if isinstance(node, dict) else None
    if not isinstance(items, dict):
        return None
    items = _deref(schema_root, items)
    item_type = items.get("type") if isinstance(items, dict) else None
    return item_type if isinstance(item_type, str) else None


def _looks_like_string_list(value: Any) -> bool:
    """True when *value* is a non-empty list of plain strings."""
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) for item in value)
    )


def _editor_kind_for(
    field: ConfigField, schema_root: dict[str, Any], current_value: Any
) -> EditorKind:
    """Pick the typed editor for *field*.

    Enums always use the option cycle. Scalars map to bool / int / number /
    string by their JSON-Schema type(s). Arrays of strings get the line editor;
    every other array, open map, or mixed shape falls back to the raw-YAML
    escape hatch.
    """
    if field.enum_values:
        return "enum"
    if field.kind == "scalar":
        types = set(field.types)
        if types == {"boolean"}:
            return "bool"
        if "string" not in types and types & {"integer", "number"}:
            return "number" if "number" in types else "int"
        return "string"
    if field.kind == "array":
        item_type = _array_item_type(schema_root, field.path)
        if item_type == "string":
            return "string_list"
        if item_type is None and _looks_like_string_list(current_value):
            return "string_list"
        return "yaml"
    return "yaml"


def _yaml_dumps(value: Any) -> str:
    """Dump *value* as block YAML for the raw-YAML editor."""
    from ruamel.yaml import YAML

    handler = YAML()
    handler.default_flow_style = False
    handler.width = 4096
    buffer = io.StringIO()
    handler.dump(value, buffer)
    return buffer.getvalue()


def _yaml_loads(text: str) -> Any:
    """Parse YAML *text* into plain Python types for the wire."""
    from ruamel.yaml import YAML

    handler = YAML(typ="safe")
    loaded = handler.load(io.StringIO(text))
    # Normalize to plain JSON-able types (the binding is JSON in/out).
    return json.loads(json.dumps(loaded)) if loaded is not None else None


def _format_value_for_editor(kind: EditorKind, value: Any) -> str:
    """Render *value* as the initial text for a *kind* editor."""
    if kind in ("int", "number", "string"):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        return str(value)
    if kind == "string_list":
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return ""
    if kind == "yaml":
        if value is None:
            return ""
        return _yaml_dumps(value)
    return ""


def _parse_editor_value(
    kind: EditorKind, text: str, field: ConfigField
) -> tuple[Any, str | None]:
    """Parse editor *text* for *kind*; return ``(value, error_or_None)``."""
    if kind == "int":
        stripped = text.strip()
        try:
            return _check_constraints(int(stripped), field)
        except ValueError:
            return None, f"'{stripped}' is not an integer"
    if kind == "number":
        stripped = text.strip()
        try:
            return _check_constraints(float(stripped), field)
        except ValueError:
            return None, f"'{stripped}' is not a number"
    if kind == "string":
        return _check_constraints(text, field)
    if kind == "string_list":
        items = [line.strip() for line in text.splitlines() if line.strip()]
        return items, None
    if kind == "yaml":
        try:
            return _yaml_loads(text), None
        except Exception as exc:  # ruamel raises a variety of parse errors
            return None, f"invalid YAML: {exc}"
    return None, "unsupported editor"


def _check_constraints(value: Any, field: ConfigField) -> tuple[Any, str | None]:
    """Apply the field's numeric/length constraints, returning an error if any."""
    constraints = field.constraints
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if constraints.minimum is not None and value < constraints.minimum:
            return None, f"must be ≥ {constraints.minimum}"
        if constraints.maximum is not None and value > constraints.maximum:
            return None, f"must be ≤ {constraints.maximum}"
        if (
            constraints.exclusive_minimum is not None
            and value <= constraints.exclusive_minimum
        ):
            return None, f"must be > {constraints.exclusive_minimum}"
        if (
            constraints.exclusive_maximum is not None
            and value >= constraints.exclusive_maximum
        ):
            return None, f"must be < {constraints.exclusive_maximum}"
    if isinstance(value, str):
        if constraints.min_length is not None and len(value) < constraints.min_length:
            return None, f"must be at least {constraints.min_length} char(s)"
        if constraints.max_length is not None and len(value) > constraints.max_length:
            return None, f"must be at most {constraints.max_length} char(s)"
    return value, None


def _format_value(value: Any) -> str:
    """Compact display rendering of a config value."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _list_strategy_banner(source: ConfigSource) -> Text:
    """Banner describing how a list write merges for *source*."""
    text = Text()
    if source.list_strategy == "replace":
        text.append("⚠ list replace: ", style=f"bold {_WARN_COLOR}")
        text.append(
            f"a list here replaces lower layers entirely ({source.name}).",
            style=_MUTED,
        )
    else:
        text.append("list append: ", style=f"bold {_OK_COLOR}")
        text.append(
            f"a list here is concatenated after lower layers ({source.name}).",
            style=_MUTED,
        )
    return text


def _scope_label(source: ConfigSource) -> Text:
    """One-line label for a writable scope row."""
    text = Text()
    text.append(source.name, style=f"bold {_ACCENT}")
    suffix = " · new" if not source.exists else ""
    text.append(f"  ({source.list_strategy}{suffix})", style=_MUTED)
    return text


def _initial_target(
    inventory: ConfigInventory, field: ConfigField, view: ConfigPaneView
) -> str | None:
    """Default writable target: where the field is already set, else policy.

    Prefers the highest-priority *writable* layer that currently contributes to
    the field (so "edit where it lives" is the default). Otherwise falls back to
    the research defaulting rules, forcing an explicit choice for list fields.
    """
    state = view.state_by_path.get(field.path)
    if state is not None:
        writable = {s.name for s in inventory.sources if s.writable}
        for contribution in reversed(state.contributions):
            if contribution.layer in writable:
                return contribution.layer
    force_explicit = field.kind == "array"
    target = default_target_layer(inventory, force_explicit=force_explicit)
    if target is not None:
        return target
    writable_sources = [s for s in inventory.sources if s.writable]
    return writable_sources[0].name if writable_sources else None


# --- Overlay-name sub-modal ------------------------------------------------


class _OverlayNameModal(ModalScreen[str | None]):
    """Prompt for a new overlay name; dismiss with the name or ``None``."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Create"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="overlay-name-container"):
            yield Label("New overlay", id="overlay-name-title")
            yield Label(
                "name → ~/.config/sase/sase_<name>.yml",
                id="overlay-name-help",
            )
            yield Input(placeholder="work", id="overlay-name-input")
            yield Static("enter / ctrl+s create · esc cancel", id="overlay-name-hints")

    def on_mount(self) -> None:
        # A Screen's on_mount can fire before its children are mounted.
        self.call_after_refresh(self._focus_input)

    def _focus_input(self) -> None:
        try:
            self.query_one("#overlay-name-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one("#overlay-name-input", Input).value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# --- Main edit modal -------------------------------------------------------


class ConfigEditModal(ModalScreen["AppliedResult | None"]):
    """Edit a single config field (or run the repo-key migration) and write it."""

    # Focus is managed explicitly (``_focus_editor``); the hidden Input/TextArea
    # must not steal focus from the screen, which would break the key-driven
    # bool/enum editors and the preview-stage bindings.
    AUTO_FOCUS = None

    BINDINGS = [
        ("escape", "back", "Back/Cancel"),
        ("ctrl+s", "confirm", "Confirm"),
        ("enter", "confirm", "Confirm"),
        ("space", "toggle_value", "Toggle"),
        ("ctrl+t", "cycle_scope", "Scope"),
        ("ctrl+n", "new_overlay", "New overlay"),
        ("ctrl+r", "toggle_reset", "Reset to default"),
    ]

    def __init__(
        self,
        view: ConfigPaneView,
        *,
        field: ConfigField | None = None,
        mode: Mode = "field",
    ) -> None:
        super().__init__()
        self._view = view
        self._inventory: ConfigInventory = view.inventory
        self._mode: Mode = mode
        self._field = field
        self._stage: Stage = "edit"
        self._editor_kind: EditorKind = "string"
        self._op_unset = False
        self._error: str | None = None
        self._status: str | None = None
        self._busy = False
        self._plan: EditPlanResult | None = None
        self._plan_worker: Worker[Any] | None = None
        self._apply_worker: Worker[Any] | None = None
        # Scope + value state (field mode).
        self._target: str | None = None
        self._enum_index = 0
        self._bool_value = False
        self._initial_value: Any = None
        if mode == "field" and field is not None:
            self._init_field_state(field)

    @classmethod
    def for_migration(cls, view: ConfigPaneView) -> ConfigEditModal:
        """Build the modal for the ``sibling_repos`` → ``linked_repos`` migration."""
        field = view.fields_by_path.get("linked_repos")
        return cls(view, field=field, mode="migration")

    # -- field-mode initialization --

    def _init_field_state(self, field: ConfigField) -> None:
        state = self._view.state_by_path.get(field.path)
        if state is not None and state.has_effective:
            current = state.effective_value
        elif field.has_default:
            current = field.default
        else:
            current = None
        self._editor_kind = _editor_kind_for(field, self._inventory.schema, current)
        self._target = _initial_target(self._inventory, field, self._view)
        if self._editor_kind == "bool":
            self._bool_value = bool(current)
        elif self._editor_kind == "enum":
            values = list(field.enum_values)
            self._enum_index = values.index(current) if current in values else 0
        self._initial_value = current

    # -- composition --

    def compose(self) -> ComposeResult:
        # Only the editor widget the field actually needs is mounted (so a hidden
        # Input/TextArea can't steal focus from the key-driven bool/enum editors
        # or the preview-stage screen bindings), and it is seeded with the
        # initial value here — a Screen's on_mount can fire before its composed
        # children are mounted, so querying them there is unreliable.
        seed = _format_value_for_editor(self._editor_kind, self._initial_value)
        with Container(id="config-edit-container"):
            yield Label("", id="config-edit-title")
            yield Static("", id="config-edit-info", markup=False)
            yield Static("", id="config-edit-scope", markup=False)
            yield Static("", id="config-edit-banner", markup=False)
            yield Static("", id="config-edit-value", markup=False)
            if self._mode == "field" and self._uses_input():
                yield Input(value=seed, id="config-edit-input")
            elif self._mode == "field" and self._uses_textarea():
                yield TextArea(seed, id="config-edit-textarea", show_line_numbers=False)
            yield Static("", id="config-edit-error", markup=False)
            with VerticalScroll(id="config-edit-preview-scroll"):
                yield Static("", id="config-edit-preview", markup=False)
            yield Static("", id="config-edit-hints", markup=False)

    def on_mount(self) -> None:
        # Defer first render/focus until composed children are mounted.
        self.call_after_refresh(self._initialize)

    def _initialize(self) -> None:
        if self._mode == "migration":
            self._begin_migration()
        self._render_all()
        self._focus_editor()

    # -- editor widget wiring --

    def _uses_input(self) -> bool:
        return self._editor_kind in ("int", "number", "string")

    def _uses_textarea(self) -> bool:
        return self._editor_kind in ("string_list", "yaml")

    def _focus_editor(self) -> None:
        """Focus the editor widget, or blur so the screen handles key bindings."""
        if self._stage != "edit" or self._mode == "migration" or self._op_unset:
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

    # -- rendering --

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
        if self._mode == "migration":
            text.append("Migrate  ", style="bold")
            text.append("sibling_repos → linked_repos", style=f"bold {_ACCENT}")
            return text
        text.append("Edit  ", style="bold")
        if self._field is not None:
            text.append(self._field.path, style=f"bold {_ACCENT}")
        return text

    def _info_text(self) -> Text:
        text = Text()
        if self._mode == "migration":
            text.append(
                "Fold the deprecated sibling_repos list into linked_repos and "
                "remove it.",
                style=_MUTED,
            )
            return text
        field = self._field
        if field is None:
            return text
        type_label = "/".join(field.types) if field.types else field.kind
        text.append("type: ", style=_MUTED)
        text.append(type_label or "—")
        if field.enum_values:
            text.append("  enum: ", style=_MUTED)
            text.append(", ".join(_format_value(v) for v in field.enum_values))
        constraint = self._constraint_hint(field)
        if constraint:
            text.append(f"  {constraint}", style=_MUTED)
        text.append("\n")
        if field.has_default:
            text.append("default: ", style=_MUTED)
            text.append(_format_value(field.default))
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
        text.append_text(_scope_label(source))
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
        return _list_strategy_banner(source)

    def _value_text(self) -> Text:
        text = Text()
        if self._mode == "migration":
            return text
        if self._op_unset:
            text.append("reset to default", style=f"bold {_MOD_COLOR}")
            field = self._field
            text.append("  → ", style=_MUTED)
            if field is not None and field.has_default:
                text.append(_format_value(field.default))
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
            text.append(_format_value(current), style=f"bold {_ACCENT}")
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
            _format_value(preview.before) if preview.has_before else "(unset)",
            style=_MUTED,
        )
        text.append("  →  ", style=_MUTED)
        text.append(
            _format_value(preview.after) if preview.has_after else "(unset)",
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
        if self._mode == "migration":
            return "enter / ctrl+s: preview   esc: cancel"
        toggle = ""
        if self._editor_kind in ("bool", "enum"):
            toggle = "space: change  "
        reset = "ctrl+r: un-reset" if self._op_unset else "ctrl+r: reset"
        return (
            f"{toggle}ctrl+t: scope  ctrl+n: new overlay  {reset}  "
            "ctrl+s: preview  esc: cancel"
        )

    # -- scope helpers --

    def _writable_sources(self) -> list[ConfigSource]:
        return [s for s in self._inventory.sources if s.writable]

    def _target_source(self) -> ConfigSource | None:
        if self._target is None:
            return None
        return self._inventory.source(self._target)

    # -- actions --

    def action_cycle_scope(self) -> None:
        if self._stage != "edit" or self._busy:
            return
        writable = self._writable_sources()
        if len(writable) <= 1:
            return
        names = [s.name for s in writable]
        try:
            index = names.index(self._target) if self._target in names else -1
        except ValueError:
            index = -1
        self._target = names[(index + 1) % len(names)]
        self._error = None
        self._render_all()

    def action_new_overlay(self) -> None:
        if self._stage != "edit" or self._busy:
            return

        def _on_name(name: str | None) -> None:
            if not name:
                return
            try:
                inventory, layer_name = inventory_with_new_overlay(
                    self._inventory, name
                )
            except Exception as exc:
                self._error = f"could not create overlay: {exc}"
                self._render_all()
                return
            self._inventory = inventory
            self._target = layer_name
            self._error = None
            self._render_all()

        self.app.push_screen(_OverlayNameModal(), _on_name)

    def action_toggle_reset(self) -> None:
        if self._stage != "edit" or self._mode == "migration" or self._busy:
            return
        self._op_unset = not self._op_unset
        self._error = None
        self._render_all()
        self._focus_editor()

    def action_toggle_value(self) -> None:
        if self._stage != "edit" or self._op_unset or self._busy:
            return
        if self._editor_kind == "bool":
            self._bool_value = not self._bool_value
            self._render_all()
        elif self._editor_kind == "enum":
            field = self._field
            count = len(field.enum_values) if field is not None else 0
            if count:
                self._enum_index = (self._enum_index + 1) % count
                self._render_all()

    def action_back(self) -> None:
        if self._busy:
            return
        if self._stage == "preview" and self._mode == "field":
            self._stage = "edit"
            self._plan = None
            self._error = None
            self._status = None
            self._render_all()
            self._focus_editor()
            return
        self.dismiss(None)

    def action_confirm(self) -> None:
        if self._busy:
            return
        if self._stage == "edit":
            self._start_plan()
        else:
            self._start_apply()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "config-edit-input" and self._stage == "edit":
            self._start_plan()

    # -- planning --

    def _current_op(self) -> tuple[ConfigEditOp | None, str | None]:
        """Resolve the edit operation from the editor state, or an error."""
        if self._op_unset:
            return ConfigEditOp.unset(), None
        kind = self._editor_kind
        field = self._field
        if field is None:
            return None, "no field to edit"
        if kind == "bool":
            return ConfigEditOp.set_value(self._bool_value), None
        if kind == "enum":
            values = list(field.enum_values)
            if not values:
                return None, "no enum values"
            return ConfigEditOp.set_value(values[self._enum_index]), None
        if self._uses_input():
            raw = self.query_one("#config-edit-input", Input).value
        else:
            raw = self.query_one("#config-edit-textarea", TextArea).text
        value, error = _parse_editor_value(kind, raw, field)
        if error is not None:
            return None, error
        return ConfigEditOp.set_value(value), None

    def _start_plan(self) -> None:
        if self._mode == "migration":
            return
        if self._target is None:
            self._error = "no writable target — create an overlay (ctrl+n)"
            self._render_all()
            return
        op, error = self._current_op()
        if op is None or error is not None:
            self._error = error
            self._render_all()
            return
        self._error = None
        self._status = None
        self._busy = True
        self._stage = "preview"
        self._plan = None
        self.set_focus(None)
        self._render_all()
        inventory = self._inventory
        path = self._field.path if self._field is not None else ""
        target = self._target

        def task() -> EditPlanResult:
            return plan_config_edit(inventory, path, target, op)

        self._plan_worker = self.run_worker(task, thread=True, exclusive=True)

    def _begin_migration(self) -> None:
        self._stage = "preview"
        self._busy = True
        self._plan = None
        inventory = self._inventory

        def task() -> EditPlanResult | None:
            return plan_repo_key_migration(inventory)

        self._plan_worker = self.run_worker(task, thread=True, exclusive=True)

    # -- applying --

    def _start_apply(self) -> None:
        plan = self._plan
        if plan is None:
            return
        if not plan.is_valid:
            self._error = "fix validation errors before writing"
            self._render_all()
            return
        if not plan.text_diff.strip():
            self._error = "nothing to write — no change"
            self._render_all()
            return
        self._busy = True
        self._error = None
        self._render_all()

        def task() -> tuple[AppliedResult, str | None]:
            result = apply_config_edit(plan)
            note: str | None = None
            if result.used_chezmoi:
                proc = apply_chezmoi(result.path)
                if proc.returncode != 0:
                    detail = proc.stderr.strip() or f"exit {proc.returncode}"
                    note = f"chezmoi apply failed: {detail}"
            return result, note

        self._apply_worker = self.run_worker(task, thread=True, exclusive=True)

    # -- worker results --

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._plan_worker:
            self._on_plan_worker(event)
        elif event.worker is self._apply_worker:
            self._on_apply_worker(event)

    def _on_plan_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            result = event.worker.result
            if result is None:
                self._error = "nothing to migrate (sibling_repos is not set)"
                self._plan = None
                if self._mode == "migration":
                    self.dismiss(None)
                    return
                self._stage = "edit"
                self._render_all()
                self._focus_editor()
                return
            self._plan = result
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "could not plan edit")
            if self._mode == "migration":
                self._render_all()
            else:
                self._stage = "edit"
                self._render_all()
                self._focus_editor()

    def _on_apply_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            outcome = event.worker.result
            if not isinstance(outcome, tuple):
                self.dismiss(None)
                return
            result, note = outcome
            if note is not None:
                # The file was written, but chezmoi propagation failed; keep the
                # modal open so the user can retry or apply chezmoi manually.
                self._error = note
                self._render_all()
                return
            self.dismiss(result)
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "write failed")
            self._render_all()

    @staticmethod
    def _worker_error(event: Worker.StateChanged, fallback: str) -> str:
        error = event.worker.error
        if isinstance(error, ConfigEditError):
            return str(error)
        return str(error) if error else fallback
