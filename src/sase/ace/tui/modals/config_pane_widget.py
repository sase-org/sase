"""Textual widget for the Config Center config pane."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, Static, Tree
from textual.widgets.tree import TreeNode
from textual.worker import Worker, WorkerState

from sase.config import AppliedResult

from ..util.selection import restore_selection_by_identity
from .config_commit import (
    ConfigCommitOffer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from .config_center_session import SelectionBookmark
from .config_pane_rendering import (
    render_detail,
    render_row_label,
    render_source_rail,
    visible_leaf_paths,
    visible_paths,
)
from .config_pane_view import ConfigPaneView, InputMode


class ConfigFilterInput(Input):
    """Filter/jump input with pane-local escape handling.

    Brackets remain ordinary filter text; ``escape`` returns focus to the tree
    without leaving a stale filter. The Admin Center's priority ``Tab`` /
    ``Shift+Tab`` bindings handle main-tab navigation while this input is
    focused.
    """

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
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
        self._syncing_tree = True
        tree.clear()
        self._node_by_path = {}
        view = self._view
        if view is None:
            self._syncing_tree = False
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
        mod = "mod ✓" if self._modified_only else "mod"
        return (
            f"j/k: move  h/l: fold  g/G: top/bottom  ctrl+d/u: scroll  "
            f"↵/e: edit  /: filter  :: jump  "
            f"m: {mod}  r: refresh  Tab/Shift+Tab: tab  Esc: close"
        )

    # -- tree selection events --

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if self._syncing_tree:
            return
        data = event.node.data
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            tree = None
        if tree is not None and event.node is not tree.cursor_node:
            return
        if isinstance(data, str):
            self._update_detail(data)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter / click on a leaf opens its editor (sections just toggle)."""
        data = event.node.data
        if isinstance(data, str):
            view = self._view
            if view is not None:
                field = view.fields_by_path.get(data)
                if field is not None and field.leaf:
                    event.stop()
                    self._open_editor(data)

    # -- actions --

    def action_cursor_down(self) -> None:
        self._tree_action("action_cursor_down")

    def action_cursor_up(self) -> None:
        self._tree_action("action_cursor_up")

    def action_cycle_cursor_down(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        if tree.cursor_line == tree.last_line:
            first_node = tree.get_node_at_line(0)
            if first_node is not None:
                self._move_cursor(tree, first_node)
            return
        tree.action_cursor_down()

    def action_cycle_cursor_up(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        if tree.cursor_line == 0:
            last_node = tree.get_node_at_line(tree.last_line)
            if last_node is not None:
                self._move_cursor(tree, last_node)
            return
        tree.action_cursor_up()

    def _tree_action(self, name: str) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        getattr(tree, name)()

    def action_scroll_to_top(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        nodes = self._visible_tree_nodes(tree)
        if nodes:
            self._move_cursor(tree, nodes[0])

    def action_scroll_to_bottom(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        nodes = self._visible_tree_nodes(tree)
        if nodes:
            self._move_cursor(tree, nodes[-1])

    def action_collapse_tree(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        node = self._current_tree_node(tree)
        if node is None:
            return
        view = self._view
        data = node.data
        field = (
            view.fields_by_path.get(data)
            if view is not None and isinstance(data, str)
            else None
        )
        if field is not None and not field.leaf:
            node.collapse()
            self._update_detail(field.path)
            return
        parent = node.parent
        if parent is not None and isinstance(parent.data, str):
            self._move_cursor(tree, parent)

    def action_expand_tree(self) -> None:
        try:
            tree = self.query_one("#config-tree", Tree)
        except Exception:
            return
        node = self._current_tree_node(tree)
        if node is None:
            return
        view = self._view
        data = node.data
        field = (
            view.fields_by_path.get(data)
            if view is not None and isinstance(data, str)
            else None
        )
        if field is None or field.leaf:
            return
        if node.is_collapsed:
            node.expand()
            self._update_detail(field.path)
        elif node.children:
            self._move_cursor(tree, node.children[0])

    def _move_cursor(self, tree: Tree[str], node: TreeNode[str]) -> None:
        tree.move_cursor(node, animate=False)
        if isinstance(node.data, str):
            self._update_detail(node.data)

    def _current_tree_node(self, tree: Tree[str]) -> TreeNode[str] | None:
        if self._selected_path is not None:
            node = self._node_by_path.get(self._selected_path)
            if node is not None:
                return node
        return tree.cursor_node

    @staticmethod
    def _visible_tree_nodes(tree: Tree[str]) -> list[TreeNode[str]]:
        nodes: list[TreeNode[str]] = []

        def append_visible_children(parent: TreeNode[str]) -> None:
            for child in parent.children:
                nodes.append(child)
                if child.is_expanded:
                    append_visible_children(child)

        append_visible_children(tree.root)
        return nodes

    def action_scroll_detail_down(self) -> None:
        try:
            scroll = self.query_one("#config-detail-scroll", VerticalScroll)
        except Exception:
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_detail_up(self) -> None:
        try:
            scroll = self.query_one("#config-detail-scroll", VerticalScroll)
        except Exception:
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_focus_filter(self) -> None:
        self._input_mode = "filter"
        self._focus_input("/ filter")

    def action_jump_to_path(self) -> None:
        self._input_mode = "jump"
        self._focus_input(": jump to dotted path")

    def _focus_input(self, placeholder: str) -> None:
        try:
            field_input = self.query_one("#config-filter-input", ConfigFilterInput)
        except Exception:
            return
        field_input.placeholder = placeholder
        field_input.focus()

    def action_toggle_modified(self) -> None:
        self._modified_only = not self._modified_only
        self._rebuild_tree()
        self._update_static("#config-pane-hints", self._hints())
        self._sync_state_visibility()

    def action_refresh(self) -> None:
        from . import config_pane as public_config_pane

        public_config_pane._clear_view_cache()
        self._start_load(force=True)

    def action_edit_field(self) -> None:
        """Edit the selected leaf."""
        path = self._selected_path
        view = self._view
        if path is None or view is None:
            return
        field = view.fields_by_path.get(path)
        if field is None or not field.leaf:
            return
        self._open_editor(path)

    def _open_editor(self, path: str) -> None:
        view = self._view
        if view is None:
            return
        field = view.fields_by_path.get(path)
        if field is None or not field.leaf:
            return
        from sase.ace.tui.modals.config_edit_modal import ConfigEditModal

        self.app.push_screen(
            ConfigEditModal(view, field=field), self._on_edit_dismissed
        )

    def _on_edit_dismissed(self, result: Any) -> None:
        """After a successful write, refresh the inventory to show the change."""
        if not isinstance(result, AppliedResult):
            return
        self._notify_write_success(result)
        self.action_refresh()
        if tuple(result.key_path) == ("max_running_agents",):
            request_refresh = getattr(self.app, "request_agents_refresh", None)
            if callable(request_refresh):
                request_refresh("config")
        self._start_config_commit_offer(result)

    def _start_config_commit_offer(self, result: AppliedResult) -> None:
        """Discover a commit offer for the written path without blocking input."""
        self._cancel_config_commit_offer()
        target_path = result.path
        field_path = ".".join(result.key_path) or "configuration"
        verb = "Reset" if result.op == "unset" else "Update"
        subject = f"chore: {verb} config {field_path}"

        def task() -> ConfigCommitOffer | None:
            from . import config_pane as public_config_pane

            return public_config_pane._build_config_commit_offer(
                target_path,
                subject=subject,
            )

        self._config_commit_offer_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="config-pane-commit-offer",
        )

    def _on_config_commit_offer_worker_state(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._config_commit_offer_worker = None
        if event.state != WorkerState.SUCCESS or not self.is_mounted:
            return
        offer = event.worker.result
        if offer is None:
            return
        push_config_commit_prompt(
            self.app,
            offer,
            message="Commit and push your config field change?",
            on_confirm=self._submit_commit_task,
        )

    def _cancel_config_commit_offer(self) -> None:
        worker = self._config_commit_offer_worker
        self._config_commit_offer_worker = None
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def _submit_commit_task(self, offer: ConfigCommitOffer) -> None:
        submit_config_commit_task(
            self.app,
            offer,
            display_name=f"commit config {offer.rel_path}",
        )

    def _notify_write_success(self, result: AppliedResult) -> None:
        key_path = ".".join(result.key_path) if result.key_path else "(unknown)"
        target = result.path or "(unknown target)"
        message = f"wrote {key_path} → {target}"
        if result.used_chezmoi:
            message += " (chezmoi applied)"
        try:
            self.app.notify(message)
        except Exception:
            pass

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
            self.query_one("#config-filter-input", ConfigFilterInput).value = value
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
        self._bookmark.record(target, self._logical_row_for_path(target))
        self._rebuild_tree()
        self._update_static("#config-pane-hints", self._hints())
        self._sync_state_visibility()
        self.focus_default()

    @staticmethod
    def _match_path(view: ConfigPaneView | None, query: str) -> str | None:
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


_ConfigFilterInput = ConfigFilterInput
