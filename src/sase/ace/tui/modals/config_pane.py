"""Config tab pane for the Config Center modal (read-only browse + inspect).

Phase 4 fills the Config tab with a schema-driven, read-only browser wired to
the Rust-backed Python config backend (:func:`sase.config.build_config_inventory`
and :func:`sase.config.config_field_model`). It answers three of the panel's
four questions for any field — *what value is effective, why (provenance), and
where it lives* — leaving editing/writes to Phase 5.

Three regions:

- **Source rail** — one row per config layer (built-in, plugins, user base,
  overlays, selected local) with loaded/missing/invalid/read-only badges, the
  layer's list strategy, and key count.
- **Field tree** — the schema flattened into sections → nested objects → leaf
  fields. ``/`` filters by dotted path + description, ``m`` toggles
  modified-only, ``:`` jumps to a path, ``r`` refreshes. Each leaf row carries
  a modified marker and its winning-layer badge.
- **Detail / provenance pane** — description, type, default, effective value,
  the full provenance stack in priority order with the winning layer marked
  (the ``git config --show-origin`` analogue), and field/source diagnostics.

The inventory is built off the Textual event loop in a worker (it parses the
schema, scans layers, and calls into Rust); the UI shows a loading state first,
then populates. Results are cached by the config stat-token so re-opening the
Config Center is instant when nothing changed; ``r`` forces a fresh read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, Static, Tree
from textual.widgets.tree import TreeNode
from textual.worker import Worker, WorkerState

from sase.config import (
    ConfigField,
    ConfigFieldModel,
    ConfigFieldState,
    ConfigInventory,
    ConfigSource,
    build_config_inventory,
    config_field_model,
)
from sase.config.core import current_config_token

# Layer kinds that a user can actually write to. A field touched by any of
# these is "modified" relative to the shipped built-in / plugin defaults.
_MUTABLE_KINDS: frozenset[str] = frozenset({"user", "overlay", "local"})

# Short, colored badge per source kind, reused by the tree rows, the source
# rail, and the provenance stack so a layer reads the same everywhere.
_KIND_LABEL: dict[str, str] = {
    "builtin": "built-in",
    "plugin": "plugin",
    "user": "user",
    "overlay": "overlay",
    "local": "local",
    "other": "other",
}
_KIND_COLOR: dict[str, str] = {
    "builtin": "#888888",
    "plugin": "#AF87FF",
    "user": "#00D7AF",
    "overlay": "#87D7FF",
    "local": "#5FAF5F",
    "other": "#888888",
}

_MODIFIED_COLOR = "#FFD700"
_DEPRECATED_COLOR = "#FF8787"
_MUTED = "#888888"

InputMode = Literal["filter", "jump"]


# --- Pure data view -------------------------------------------------------


@dataclass(frozen=True)
class _ConfigPaneView:
    """Joined, lookup-friendly view over the field model and inventory.

    The field model supplies the ordered tree structure and per-field schema
    metadata (type, description, default, enum, deprecation); the inventory
    supplies effective values and the per-field provenance stack. They are
    keyed 1:1 by dotted ``path``.
    """

    field_model: ConfigFieldModel
    inventory: ConfigInventory
    fields_by_path: dict[str, ConfigField]
    state_by_path: dict[str, ConfigFieldState]
    kind_by_layer: dict[str, str]

    @classmethod
    def build(
        cls, field_model: ConfigFieldModel, inventory: ConfigInventory
    ) -> _ConfigPaneView:
        return cls(
            field_model=field_model,
            inventory=inventory,
            fields_by_path={f.path: f for f in field_model.fields},
            state_by_path={s.path: s for s in inventory.fields},
            kind_by_layer={s.name: s.kind for s in inventory.sources},
        )

    # -- per-field derivations --

    def winning_layer(self, path: str) -> str | None:
        """Return the highest-priority contributing layer for *path*."""
        state = self.state_by_path.get(path)
        if state is None:
            return None
        for contribution in state.contributions:
            if contribution.winning:
                return contribution.layer
        return None

    def is_modified(self, path: str) -> bool:
        """True when a writable (user/overlay/local) layer set this field."""
        state = self.state_by_path.get(path)
        if state is None:
            return False
        return any(
            self.kind_by_layer.get(c.layer) in _MUTABLE_KINDS
            for c in state.contributions
        )

    def modified_paths(self) -> set[str]:
        """All leaf paths a writable layer contributed to."""
        return {
            field.path
            for field in self.field_model.fields
            if field.leaf and self.is_modified(field.path)
        }

    def deprecation_replacement(self, path: str) -> str | None:
        """Replacement key for *path*, from the schema or the inventory policy.

        A key can be deprecated by the schema (``deprecated: true``) or by the
        runtime deprecation policy surfaced through the inventory field state;
        either source supplies the suggested replacement.
        """
        field = self.fields_by_path.get(path)
        if field is not None and field.deprecated_replacement:
            return field.deprecated_replacement
        state = self.state_by_path.get(path)
        if state is not None and state.deprecated_replacement:
            return state.deprecated_replacement
        return None

    def is_deprecated(self, path: str) -> bool:
        """True when the schema or the deprecation policy flags *path*."""
        field = self.fields_by_path.get(path)
        if field is not None and field.deprecated:
            return True
        state = self.state_by_path.get(path)
        return state is not None and state.deprecated_replacement is not None


# --- Pure rendering helpers (no Textual app required) ---------------------


def _format_value(value: Any) -> str:
    """Render a config value for display (compact JSON for non-strings)."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _kind_badge(kind: str) -> Text:
    """A small colored badge for a source kind."""
    return Text(_KIND_LABEL.get(kind, kind), style=_KIND_COLOR.get(kind, _MUTED))


def _ancestor_paths(path: str) -> list[str]:
    """Dotted ancestor paths of *path*, outermost first (excludes *path*)."""
    parts = path.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts) - 1)]


def _visible_leaf_paths(
    view: _ConfigPaneView, *, filter_text: str = "", modified_only: bool = False
) -> list[str]:
    """Leaf paths passing the active filter + modified-only toggle, in order."""
    query = filter_text.strip().casefold()
    modified = view.modified_paths() if modified_only else None
    result: list[str] = []
    for field in view.field_model.fields:
        if not field.leaf:
            continue
        if modified is not None and field.path not in modified:
            continue
        if query:
            haystack = f"{field.path}\n{field.description}".casefold()
            if query not in haystack:
                continue
        result.append(field.path)
    return result


def _visible_paths(
    view: _ConfigPaneView, *, filter_text: str = "", modified_only: bool = False
) -> set[str]:
    """Every path to show: the visible leaves plus their ancestor sections."""
    leaves = _visible_leaf_paths(
        view, filter_text=filter_text, modified_only=modified_only
    )
    shown: set[str] = set(leaves)
    for leaf in leaves:
        shown.update(_ancestor_paths(leaf))
    return shown


def _render_row_label(view: _ConfigPaneView, path: str) -> Text:
    """Tree row label: name + modified marker + winning-layer badge."""
    field = view.fields_by_path.get(path)
    if field is None:
        return Text(path)
    text = Text()
    if not field.leaf:
        # Section / nested object container.
        text.append(field.name, style="bold")
        return text
    if view.is_modified(path):
        text.append("● ", style=_MODIFIED_COLOR)
    else:
        text.append("  ")
    name_style = f"{_DEPRECATED_COLOR} strike" if view.is_deprecated(path) else ""
    text.append(field.name, style=name_style)
    winning = view.winning_layer(path)
    if winning is not None:
        kind = view.kind_by_layer.get(winning, "other")
        text.append("  ")
        text.append(
            _KIND_LABEL.get(kind, kind), style=f"dim {_KIND_COLOR.get(kind, _MUTED)}"
        )
    return text


def _render_source_rail(view: _ConfigPaneView) -> Text:
    """Render the source-rail body: one block per config layer."""
    text = Text()
    sources: tuple[ConfigSource, ...] = view.inventory.sources
    if not sources:
        return Text("No config layers discovered.", style=f"italic {_MUTED}")
    for index, source in enumerate(sources):
        if index:
            text.append("\n")
        text.append(_source_status_marker(source))
        text.append(" ")
        text.append(source.name, style="bold")
        text.append("\n  ")
        text.append(_kind_badge(source.kind))
        text.append("  ", style=_MUTED)
        for badge in _source_badges(source):
            text.append_text(badge)
            text.append(" ")
        text.append(
            f"\n  {source.list_strategy} · {source.key_count} keys", style=_MUTED
        )
        if source.path:
            text.append(f"\n  {_abbreviate_path(source.path)}", style=f"dim {_MUTED}")
        if source.error:
            text.append(f"\n  ! {source.error}", style=_DEPRECATED_COLOR)
    return text


def _source_status_marker(source: ConfigSource) -> Text:
    """A leading status glyph for a source row."""
    if source.error:
        return Text("✗", style=_DEPRECATED_COLOR)
    if not source.exists:
        return Text("○", style=_MUTED)
    return Text("●", style=_KIND_COLOR.get(source.kind, "#00D7AF"))


def _source_badges(source: ConfigSource) -> list[Text]:
    """State badges for a source row (loaded/missing/invalid/read-only)."""
    badges: list[Text] = []
    if source.error:
        badges.append(Text("invalid", style=_DEPRECATED_COLOR))
    elif not source.exists:
        badges.append(Text("missing", style=_MUTED))
    else:
        badges.append(Text("loaded", style="#5FAF5F"))
    if not source.writable:
        badges.append(Text("read-only", style=_MUTED))
    if source.deprecated_keys:
        badges.append(
            Text(f"{len(source.deprecated_keys)} deprecated", style=_DEPRECATED_COLOR)
        )
    if source.unsupported_keys:
        badges.append(
            Text(f"{len(source.unsupported_keys)} unsupported", style=_DEPRECATED_COLOR)
        )
    return badges


def _abbreviate_path(path: str) -> str:
    """Shorten a filesystem path against ``$HOME`` for display."""
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        return path
    if home and path.startswith(home):
        return "~" + path[len(home) :]
    return path


def _render_detail(view: _ConfigPaneView, path: str | None) -> Text:
    """Render the detail / provenance body for the selected *path*."""
    if path is None:
        return Text(
            "Select a field to inspect its value and provenance.",
            style=f"italic {_MUTED}",
        )
    field = view.fields_by_path.get(path)
    if field is None:
        return Text(path)
    text = Text()
    text.append(field.path, style="bold #00D7AF")
    text.append("\n")
    if not field.leaf:
        _render_section_detail(view, field, text)
    else:
        _render_leaf_detail(view, field, text)
    _render_field_diagnostics(view, path, text)
    return text


def _render_section_detail(
    view: _ConfigPaneView, field: ConfigField, text: Text
) -> None:
    children = [
        child for child in view.field_model.fields if child.parent == field.path
    ]
    text.append("section", style=_MUTED)
    text.append(f" · {len(children)} field(s)\n")
    if field.description:
        text.append(f"\n{field.description}\n", style=_MUTED)


def _render_leaf_detail(view: _ConfigPaneView, field: ConfigField, text: Text) -> None:
    type_label = "/".join(field.types) if field.types else field.kind
    text.append("type: ", style=_MUTED)
    text.append(type_label or "—")
    if field.enum_values:
        text.append("  enum: ", style=_MUTED)
        text.append(", ".join(_format_value(v) for v in field.enum_values))
    if view.is_deprecated(field.path):
        text.append("  ")
        text.append("DEPRECATED", style=f"bold {_DEPRECATED_COLOR}")
        replacement = view.deprecation_replacement(field.path)
        if replacement:
            text.append(f" → {replacement}", style=_DEPRECATED_COLOR)
    text.append("\n")
    if field.description:
        text.append(f"\n{field.description}\n", style=_MUTED)

    state = view.state_by_path.get(field.path)
    text.append("\ndefault:   ", style=_MUTED)
    if field.has_default:
        text.append(_format_value(field.default))
    else:
        text.append("(none)", style=f"italic {_MUTED}")
    text.append("\neffective: ", style=_MUTED)
    if state is not None and state.has_effective:
        text.append(_format_value(state.effective_value), style="bold")
    else:
        text.append("(unset)", style=f"italic {_MUTED}")
    text.append("\n")

    _render_provenance(view, field.path, text)


def _render_provenance(view: _ConfigPaneView, path: str, text: Text) -> None:
    state = view.state_by_path.get(path)
    text.append("\nProvenance", style="bold")
    text.append("  (low → high priority)\n", style=_MUTED)
    if state is None or not state.contributions:
        text.append("  no layer sets this field\n", style=f"italic {_MUTED}")
        return
    for contribution in state.contributions:
        kind = view.kind_by_layer.get(contribution.layer, "other")
        marker = "▶" if contribution.winning else " "
        style = "bold" if contribution.winning else _MUTED
        text.append(
            f"  {marker} ", style=_MODIFIED_COLOR if contribution.winning else _MUTED
        )
        text.append(
            contribution.layer, style=f"{style} {_KIND_COLOR.get(kind, _MUTED)}"
        )
        text.append("  ")
        text.append(_format_value(contribution.raw_value), style=style)
        text.append("\n")


def _render_field_diagnostics(view: _ConfigPaneView, path: str, text: Text) -> None:
    diagnostics = [d for d in view.inventory.diagnostics if d.path == path]
    if not diagnostics:
        return
    text.append("\nDiagnostics\n", style="bold")
    for diagnostic in diagnostics:
        color = _DEPRECATED_COLOR if diagnostic.severity == "error" else "#FFAF5F"
        text.append(f"  {diagnostic.severity}: ", style=color)
        text.append(diagnostic.message, style=_MUTED)
        if diagnostic.layer:
            text.append(f" [{diagnostic.layer}]", style=f"dim {_MUTED}")
        text.append("\n")


# --- Worker data + module cache -------------------------------------------


@dataclass(frozen=True)
class _LoadResult:
    """The outcome of a (possibly cached) inventory load."""

    view: _ConfigPaneView | None
    error: str | None
    token: Any


# Process-wide inventory cache keyed by (stat-token, local_paths). Re-opening
# the Config Center reuses this when nothing on disk changed; ``r`` forces a
# rebuild by bypassing the cache.
_cache_key: tuple[Any, tuple[str, ...]] | None = None
_cache_result: _LoadResult | None = None


def _load_config_view(
    *,
    local_paths: tuple[str, ...] = (),
    force: bool = False,
) -> _LoadResult:
    """Build (or reuse) the joined config view. Safe to call off-thread."""
    global _cache_key, _cache_result
    try:
        token = current_config_token()
    except Exception:  # pragma: no cover - token is best-effort
        token = None
    key = (token, tuple(local_paths))
    if (
        not force
        and token is not None
        and _cache_key == key
        and _cache_result is not None
    ):
        return _cache_result
    try:
        field_model = config_field_model()
        inventory = build_config_inventory(local_paths=local_paths)
        result = _LoadResult(
            view=_ConfigPaneView.build(field_model, inventory),
            error=None,
            token=token,
        )
    except Exception as exc:  # surfaced as the pane error state
        result = _LoadResult(view=None, error=str(exc), token=token)
    _cache_key = key
    _cache_result = result
    return result


def _clear_view_cache() -> None:
    """Drop the cached view (used by ``r`` and by tests)."""
    global _cache_key, _cache_result
    _cache_key = None
    _cache_result = None


# --- Widgets --------------------------------------------------------------


class _ConfigFilterInput(Input):
    """Filter/jump input that yields ``[`` / ``]`` to the host tab strip.

    Like the XPrompts pane's filter, ``[`` / ``]`` must reach the Config
    Center so tab switching works while typing; ``escape`` returns focus to
    the tree without leaving a stale filter.
    """

    def on_key(self, event: events.Key) -> None:
        if event.key in ("left_square_bracket", "right_square_bracket"):
            host = self.screen
            prev_tab = getattr(host, "action_prev_center_tab", None)
            next_tab = getattr(host, "action_next_center_tab", None)
            if callable(prev_tab) and callable(next_tab):
                event.stop()
                event.prevent_default()
                (prev_tab if event.key == "left_square_bracket" else next_tab)()
        elif event.key == "escape":
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                pane.cancel_input()

    def _pane(self) -> ConfigPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ConfigPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ConfigPane(Vertical):
    """Read-only, schema-driven config browser for the Config Center."""

    can_focus = False

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("slash", "focus_filter", "Filter"),
        ("m", "toggle_modified", "Modified only"),
        ("colon", "jump_to_path", "Jump to path"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        *,
        local_paths: tuple[str, ...] = (),
        auto_load: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._local_paths = tuple(local_paths)
        self._auto_load = auto_load
        self._view: _ConfigPaneView | None = None
        self._error: str | None = None
        self._loading = auto_load
        self._filter_text = ""
        self._modified_only = False
        self._input_mode: InputMode = "filter"
        self._worker: Worker[Any] | None = None
        self._node_by_path: dict[str, TreeNode[str]] = {}
        self._selected_path: str | None = None

    # -- composition --

    def compose(self) -> ComposeResult:
        yield Label(self._title_text(), id="config-pane-title")
        with Horizontal(id="config-pane-panels"):
            with Vertical(id="config-source-rail"):
                yield Label("Sources", classes="config-region-header")
                with VerticalScroll(id="config-source-scroll"):
                    yield Static("", id="config-source-body", markup=False)
            with Vertical(id="config-field-tree"):
                yield Label("Fields", classes="config-region-header")
                yield _ConfigFilterInput(
                    placeholder="/ filter   : jump", id="config-filter-input"
                )
                yield Static(
                    self._status_message(), id="config-field-status", markup=False
                )
                tree: Tree[str] = Tree("config", id="config-tree")
                tree.show_root = False
                tree.guide_depth = 2
                yield tree
            with Vertical(id="config-detail"):
                yield Label("Detail", classes="config-region-header")
                with VerticalScroll(id="config-detail-scroll"):
                    yield Static("", id="config-detail-body", markup=False)
        yield Static(self._hints(), id="config-pane-hints", markup=False)

    def on_mount(self) -> None:
        self._sync_state_visibility()
        if self._auto_load:
            self._start_load(force=False)

    def focus_default(self) -> None:
        """Focus the tree (browse-first) when the Config tab activates."""
        try:
            self.query_one("#config-tree", Tree).focus()
        except Exception:
            pass

    # -- loading --

    def _start_load(self, *, force: bool) -> None:
        self._loading = True
        self._error = None
        self._sync_state_visibility()
        local_paths = self._local_paths

        def task() -> _LoadResult:
            return _load_config_view(local_paths=local_paths, force=force)

        self._worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            if isinstance(result, _LoadResult):
                self._view = result.view
                self._error = result.error
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._error = (
                str(event.worker.error) if event.worker.error else "load failed"
            )
            self._render_all()

    # -- rendering --

    def _render_all(self) -> None:
        self._update_static("#config-pane-title", self._title_text())
        self._update_static("#config-pane-hints", self._hints())
        view = self._view
        if view is not None:
            self._update_static("#config-source-body", _render_source_rail(view))
        else:
            self._update_static("#config-source-body", Text(""))
        self._rebuild_tree()
        self._sync_state_visibility()

    def _rebuild_tree(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        tree.clear()
        self._node_by_path = {}
        view = self._view
        if view is None:
            self._update_detail(None)
            return
        shown = _visible_paths(
            view, filter_text=self._filter_text, modified_only=self._modified_only
        )
        first_leaf: str | None = None
        for field in view.field_model.fields:
            if field.path not in shown:
                continue
            parent_node = (
                self._node_by_path.get(field.parent)
                if field.parent is not None
                else tree.root
            )
            if parent_node is None:
                parent_node = tree.root
            label = _render_row_label(view, field.path)
            if field.leaf:
                node = parent_node.add_leaf(label, data=field.path)
                if first_leaf is None:
                    first_leaf = field.path
            else:
                node = parent_node.add(label, data=field.path, expand=True)
            self._node_by_path[field.path] = node
        # Restore the prior selection if it is still visible, else first leaf.
        target = (
            self._selected_path
            if self._selected_path in self._node_by_path
            else first_leaf
        )
        if target is not None:
            target_node = self._node_by_path.get(target)
            if target_node is not None:
                tree.move_cursor(target_node)
            self._update_detail(target)
        else:
            self._update_detail(None)

    def _update_detail(self, path: str | None) -> None:
        self._selected_path = path
        view = self._view
        body = _render_detail(view, path) if view is not None else Text("")
        self._update_static("#config-detail-body", body)

    def _update_static(self, selector: str, content: Text | str) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _sync_state_visibility(self) -> None:
        """Show the tree when populated, else the status placeholder."""
        has_rows = bool(self._node_by_path)
        try:
            status = self.query_one("#config-field-status", Static)
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        status.update(self._status_message())
        show_status = self._loading or self._error is not None or not has_rows
        status.display = show_status
        tree.display = not show_status

    # -- dynamic text --

    def _title_text(self) -> str:
        view = self._view
        if view is None:
            return "Configuration"
        total = sum(1 for f in view.field_model.fields if f.leaf)
        modified = len(view.modified_paths())
        return f"Configuration  [{total} fields · {modified} modified]"

    def _status_message(self) -> str:
        if self._loading:
            return "Loading configuration…"
        if self._error is not None:
            return f"Could not load configuration:\n{self._error}"
        if self._view is None:
            return "Configuration unavailable."
        if not self._node_by_path and (self._filter_text or self._modified_only):
            return "No fields match the current filter."
        if not any(f.leaf for f in self._view.field_model.fields):
            return "No configuration fields in schema."
        return ""

    def _hints(self) -> str:
        mod = "modified ✓" if self._modified_only else "modified"
        return (
            f"j/k: move  /: filter  :: jump  m: {mod}  r: refresh  "
            "[ / ]: switch tab  Esc: close"
        )

    # -- tree selection events --

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if isinstance(data, str):
            self._update_detail(data)

    # -- actions --

    def action_cursor_down(self) -> None:
        self._tree_action("action_cursor_down")

    def action_cursor_up(self) -> None:
        self._tree_action("action_cursor_up")

    def _tree_action(self, name: str) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        getattr(tree, name)()

    def action_focus_filter(self) -> None:
        self._input_mode = "filter"
        self._focus_input("/ filter")

    def action_jump_to_path(self) -> None:
        self._input_mode = "jump"
        self._focus_input(": jump to dotted path")

    def _focus_input(self, placeholder: str) -> None:
        try:
            field_input = self.query_one("#config-filter-input", _ConfigFilterInput)
        except Exception:
            return
        field_input.placeholder = placeholder
        field_input.focus()

    def action_toggle_modified(self) -> None:
        self._modified_only = not self._modified_only
        self._selected_path = None
        self._rebuild_tree()
        self._update_static("#config-pane-hints", self._hints())
        self._sync_state_visibility()

    def action_refresh(self) -> None:
        _clear_view_cache()
        self._start_load(force=True)

    def cancel_input(self) -> None:
        """Drop any in-progress filter and return focus to the tree."""
        if self._input_mode == "filter" and self._filter_text:
            self._filter_text = ""
            self._set_input_value("")
            self._rebuild_tree()
            self._sync_state_visibility()
        self.focus_default()

    def _set_input_value(self, value: str) -> None:
        try:
            self.query_one("#config-filter-input", _ConfigFilterInput).value = value
        except Exception:
            pass

    # -- input events --

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "config-filter-input":
            return
        if self._input_mode != "filter":
            return
        self._filter_text = event.value
        self._rebuild_tree()
        self._sync_state_visibility()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "config-filter-input":
            return
        if self._input_mode == "jump":
            self._do_jump(event.value)
        else:
            # Keep the filter applied; hand control back to the tree.
            self.focus_default()

    def _do_jump(self, query: str) -> None:
        """Select the first field whose path matches *query*, clearing filters."""
        view = self._view
        target = self._match_path(view, query)
        self._set_input_value("")
        self._input_mode = "filter"
        if target is None:
            self.focus_default()
            return
        # Jump operates on the full tree so any target is reachable.
        self._filter_text = ""
        self._modified_only = False
        self._selected_path = target
        self._rebuild_tree()
        self._update_static("#config-pane-hints", self._hints())
        self._sync_state_visibility()
        self.focus_default()

    @staticmethod
    def _match_path(view: _ConfigPaneView | None, query: str) -> str | None:
        if view is None:
            return None
        needle = query.strip().casefold()
        if not needle:
            return None
        leaves = [f.path for f in view.field_model.fields if f.leaf]
        for path in leaves:
            if path.casefold() == needle:
                return path
        for path in leaves:
            if path.casefold().startswith(needle):
                return path
        for path in leaves:
            if needle in path.casefold():
                return path
        return None
