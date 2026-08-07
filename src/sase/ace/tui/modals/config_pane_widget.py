"""Textual widget for the Config Center config pane."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Static, Tree
from textual.widgets.tree import TreeNode
from textual.worker import Worker, WorkerState

from ..actions.navigation.jump_hints import normalize_jump_key
from ..util.selection import restore_selection_by_identity
from .config_commit import ConfigCommitOffer
from .config_center_session import SelectionBookmark
from .config_pane_editing import ConfigPaneEditingMixin
from .config_pane_navigation import ConfigFilterInput, ConfigPaneNavigationMixin
from .config_pane_rendering import (
    render_detail,
    render_row_label,
    render_source_rail,
    visible_leaf_paths,
    visible_paths,
)
from .config_pane_view import ConfigPaneView, InputMode
from .pane_entry_jump import PaneEntryJumpMixin, apply_jump_hint_prefix


class ConfigPane(
    ConfigPaneEditingMixin, ConfigPaneNavigationMixin, PaneEntryJumpMixin, Vertical
):
    """Read-only, schema-driven config browser for the Config Center."""

    can_focus = False

    BINDINGS = [
        ("j", "cycle_cursor_down", "Down"),
        ("k", "cycle_cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("h", "collapse_tree", "Collapse"),
        ("l", "expand_tree", "Expand"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
        ("slash", "focus_filter", "Filter"),
        ("m", "toggle_modified", "Modified only"),
        ("colon", "jump_to_path", "Jump to path"),
        ("apostrophe", "jump_to_entry", "Jump"),
        ("r", "refresh", "Refresh"),
        ("e", "edit_field", "Edit"),
    ]

    def __init__(
        self,
        *,
        local_paths: tuple[str, ...] = (),
        project: str | None = None,
        auto_load: bool = True,
        bookmark: SelectionBookmark | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._local_paths = tuple(local_paths)
        self._project = project
        self._auto_load = auto_load
        self._view: ConfigPaneView | None = None
        self._error: str | None = None
        self._loading = auto_load
        self._filter_text = ""
        self._modified_only = False
        self._input_mode: InputMode = "filter"
        self._worker: Worker[Any] | None = None
        self._config_commit_offer_worker: Worker[ConfigCommitOffer | None] | None = None
        self._node_by_path: dict[str, TreeNode[str]] = {}
        self._bookmark = bookmark or SelectionBookmark()
        self._selected_path: str | None = self._bookmark.identity
        self._syncing_tree = False

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
                yield ConfigFilterInput(
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

    def on_unmount(self) -> None:
        self._cancel_config_commit_offer()

    def focus_default(self) -> None:
        """Focus the tree (browse-first) when the Config tab activates."""
        try:
            self.query_one("#config-tree", Tree).focus()
        except Exception:
            pass

    def on_key(self, event: events.Key) -> None:
        """Give hint-jump mode first refusal at keys the tree would consume."""
        if self._filter_input_has_focus():
            return
        if self.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        if event.key == "apostrophe":
            event.prevent_default()
            event.stop()
            self.action_jump_to_entry()

    def _filter_input_has_focus(self) -> bool:
        """Whether the filter/path input owns focus, so ``'`` stays text."""
        try:
            return self.query_one("#config-filter-input", ConfigFilterInput).has_focus
        except Exception:
            return False

    # -- entry jump --

    def _jump_nodes(self) -> list[TreeNode[str]]:
        """Currently visible tree rows in render order."""
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return []
        return [
            node
            for node in self._visible_tree_nodes(tree)
            if isinstance(node.data, str)
        ]

    def _jump_target_count(self) -> int:
        return len(self._jump_nodes())

    def _jump_current_index(self) -> int | None:
        selected = self._selected_path
        if selected is None:
            return None
        for index, node in enumerate(self._jump_nodes()):
            if node.data == selected:
                return index
        return None

    def _jump_select_index(self, index: int) -> None:
        nodes = self._jump_nodes()
        if not 0 <= index < len(nodes):
            return
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        self._move_cursor(tree, nodes[index])
        # The mixin drops the hints before selecting, so this strips them.
        self._jump_repaint()

    def _jump_repaint(self) -> None:
        self._repaint_tree_labels()
        self._update_static("#config-pane-hints", self._hints())

    def _repaint_tree_labels(self) -> None:
        """Re-label rows in place, so hints never disturb the fold state.

        ``_rebuild_tree`` re-expands every section, so painting hints through
        it would silently unfold whatever the user collapsed.
        """
        view = self._view
        if view is None:
            return
        hint_by_path: dict[str, str] = {}
        if self.jump_mode_active:
            for index, node in enumerate(self._jump_nodes()):
                hint = self.jump_hint_for(index)
                if hint is not None and isinstance(node.data, str):
                    hint_by_path[node.data] = hint
        for path, node in self._node_by_path.items():
            label = render_row_label(view, path)
            hint = hint_by_path.get(path)
            if hint is not None:
                label = apply_jump_hint_prefix(label, hint)
            node.set_label(label)

    # -- loading --

    def _start_load(self, *, force: bool) -> None:
        self._loading = True
        self._error = None
        self._sync_state_visibility()
        local_paths = self._local_paths
        project = self._project

        def task() -> Any:
            from . import config_pane as public_config_pane

            resolved_local_paths = local_paths
            if not resolved_local_paths and project is not None:
                from sase.content_layout import resolve_project_layout
                from sase.xprompt.loader import get_known_project_workspaces

                workspace = get_known_project_workspaces().get(project)
                if workspace is not None:
                    config = resolve_project_layout(workspace).config
                    read_path = config.resolve_read(f"project config for {project}")
                    if read_path is None or read_path == config.write_path:
                        resolved_local_paths = (str(config.write_path),)
            return public_config_pane._load_config_view(
                local_paths=resolved_local_paths, force=force
            )

        self._worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._config_commit_offer_worker:
            self._on_config_commit_offer_worker_state(event)
            return
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            self._view = getattr(result, "view", None)
            self._error = getattr(result, "error", None)
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
            self._update_static("#config-source-body", render_source_rail(view))
        else:
            self._update_static("#config-source-body", Text(""))
        self._rebuild_tree()
        self._sync_state_visibility()

    def _rebuild_tree(self) -> None:
        self._update_static("#config-pane-title", self._title_text())
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        prior_identity = self._bookmark.identity or self._selected_path
        prior_row = self._bookmark.row
        previous_paths = list(self._node_by_path)
        self._syncing_tree = True
        tree.clear()
        self._node_by_path = {}
        view = self._view
        if view is None:
            self._syncing_tree = False
            self._invalidate_jump_after_rebuild(previous_paths)
            self._update_detail(None)
            return
        try:
            shown = visible_paths(
                view, filter_text=self._filter_text, modified_only=self._modified_only
            )
            visible_sequence: list[str] = []
            first_leaf: str | None = None
            for field in view.field_model.fields:
                if field.path not in shown:
                    continue
                visible_sequence.append(field.path)
                parent_node = (
                    self._node_by_path.get(field.parent)
                    if field.parent is not None
                    else tree.root
                )
                if parent_node is None:
                    parent_node = tree.root
                label = render_row_label(view, field.path)
                if field.leaf:
                    node = parent_node.add_leaf(label, data=field.path)
                    if first_leaf is None:
                        first_leaf = field.path
                else:
                    node = parent_node.add(label, data=field.path, expand=True)
                self._node_by_path[field.path] = node
            self._invalidate_jump_after_rebuild(previous_paths)
            if not visible_sequence:
                if not any(field.leaf for field in view.field_model.fields):
                    self._bookmark.record(None, None)
                self._update_detail(None)
                return

            target: str | None
            if prior_identity is None and prior_row is None:
                target = first_leaf or visible_sequence[0]
            else:
                target_index = restore_selection_by_identity(
                    visible_sequence,
                    prior_identity=prior_identity,
                    prior_visual_row=prior_row,
                    identity_fn=lambda path: path,
                )
                target = visible_sequence[target_index]
            if target is not None:
                target_node = self._node_by_path.get(target)
                if target_node is not None:
                    # TreeNode line numbers are assigned lazily.  Building the
                    # public line cache first prevents move_cursor() from
                    # validating the target's initial -1 line back to row 0.
                    _ = tree.last_line
                    tree.move_cursor(target_node)
                self._update_detail(target)
            else:
                self._update_detail(None)
        finally:
            self._syncing_tree = False

    def _invalidate_jump_after_rebuild(self, previous_paths: list[str]) -> None:
        """Drop stale hints after the visible row set was rebuilt.

        Every rebuild path -- filter changes, ``m``, ``r``, and ``:`` path
        jumps -- funnels through ``_rebuild_tree``, so this is the one place
        the stale-data rule has to be applied.
        """
        current_paths = list(self._node_by_path)
        self.invalidate_jump_hints(
            identities_changed=previous_paths != current_paths,
            target_count=len(current_paths),
        )

    def _update_detail(self, path: str | None) -> None:
        self._selected_path = path
        if path is not None:
            self._bookmark.record(path, self._logical_row_for_path(path))
        view = self._view
        body = render_detail(view, path) if view is not None else Text("")
        self._update_static("#config-detail-body", body)

    def _logical_row_for_path(self, path: str) -> int | None:
        view = self._view
        if view is None:
            return None
        shown = visible_paths(
            view, filter_text=self._filter_text, modified_only=self._modified_only
        )
        row = 0
        for field in view.field_model.fields:
            if field.path not in shown:
                continue
            if field.path == path:
                return row
            row += 1
        return None

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
        if self._filter_text or self._modified_only:
            matching = len(
                visible_leaf_paths(
                    view,
                    filter_text=self._filter_text,
                    modified_only=self._modified_only,
                )
            )
            return (
                f"Configuration  [matching {matching} / {total} · {modified} modified]"
            )
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
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            return f"JUMP ' {action}  <esc> cancel"
        mod = "mod ✓" if self._modified_only else "mod"
        # Two jump keys share this line, so each names what it jumps by:
        # ``'`` paints hints over rows, ``:`` takes a dotted path.  Existing
        # segments are abbreviated to make room without dropping a key.
        return (
            f"j/k: move  h/l: fold  ^d/u,g/G: scroll  e: edit  "
            f"/: filter  ': hint  :: path  "
            f"m: {mod}  r: refresh  Esc: close"
        )


_ConfigFilterInput = ConfigFilterInput
