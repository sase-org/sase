"""Navigation and filter handling for the Config Center config pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Input, Tree
from textual.widgets.tree import TreeNode

from .config_center_session import SelectionBookmark
from .config_pane_view import ConfigPaneView, InputMode

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .config_pane_widget import ConfigPane
else:
    _MixinBase = object


class ConfigFilterInput(Input):
    """Filter/jump input with pane-local escape handling.

    Brackets remain ordinary filter text unless this pane is nested in the
    Config hub, in which case they cycle Config sub-tabs. ``escape`` returns
    focus to the tree without leaving a stale filter. The Admin Center's
    priority ``Tab`` / ``Shift+Tab`` bindings handle main-tab navigation
    while this input is focused.
    """

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_bracket_key

        if handle_config_hub_bracket_key(self, event):
            return
        if event.key == "escape":
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                pane.cancel_input()

    def _pane(self) -> ConfigPane | None:
        from .config_pane_widget import ConfigPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ConfigPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ConfigPaneNavigationMixin(_MixinBase):
    """Tree navigation, filtering, and jump actions for ``ConfigPane``."""

    if TYPE_CHECKING:
        _bookmark: SelectionBookmark
        _filter_text: str
        _input_mode: InputMode
        _modified_only: bool
        _node_by_path: dict[str, TreeNode[str]]
        _selected_path: str | None
        _syncing_tree: bool
        _view: ConfigPaneView | None

        def _hints(self) -> str: ...

        def _logical_row_for_path(self, path: str) -> int | None: ...

        def _open_editor(self, path: str) -> None: ...

        def _rebuild_tree(self) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _sync_state_visibility(self) -> None: ...

        def _update_detail(self, path: str | None) -> None: ...

        def _update_static(self, selector: str, content: Text | str) -> None: ...

        def focus_default(self) -> None: ...

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
