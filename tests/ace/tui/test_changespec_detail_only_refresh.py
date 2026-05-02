"""Tests for the Phase 2 ChangeSpec j/k hot path: detail-only refresh and
single-row patching. Acceptance criteria from
``sdd/plans/202604/tui_perf_overhaul_1.md`` Phase 2.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.css.query import NoMatches as _NoMatches

from sase.ace.testing import make_changespec
from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.ace.tui.actions.marking import MarkingMixin
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.util.debounce import DetailPanelDebouncer


class _Timer:
    def stop(self) -> None:
        return


class _RecordingList:
    """Stand-in for ChangeSpecList that records hot-path calls."""

    def __init__(self) -> None:
        self.update_list_calls = 0
        self.update_highlight_calls: list[int] = []
        self.clear_options_calls = 0
        self.patch_calls: list[tuple[int, str, bool, bool]] = []
        self.patch_returns: bool = True

    def update_list(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.update_list_calls += 1
        self.clear_options_calls += 1

    def update_highlight(self, idx: int) -> None:
        self.update_highlight_calls.append(idx)

    def clear_options(self) -> None:
        self.clear_options_calls += 1

    def patch_changespec_row(
        self,
        idx: int,
        cs: Any,
        *,
        selected: bool,
        marked: bool,
        hint: str | None = None,
    ) -> bool:
        del hint
        self.patch_calls.append((idx, cs.name, selected, marked))
        return self.patch_returns


class _RecordingDetail:
    def __init__(self) -> None:
        self.update_display_calls = 0
        self.update_display_with_hints_calls = 0
        self.show_empty_calls = 0

    def update_display(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.update_display_calls += 1

    def update_display_with_hints(
        self, *args: Any, **kwargs: Any
    ) -> tuple[dict[int, str], dict[int, int], dict[int, str], None]:
        del args, kwargs
        self.update_display_with_hints_calls += 1
        return {}, {}, {}, None

    def show_empty(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.show_empty_calls += 1


class _RecordingAncestors:
    def __init__(self) -> None:
        self.update_relationships_calls = 0
        self.clear_calls = 0

    def update_relationships(
        self, *args: Any, **kwargs: Any
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        del args, kwargs
        self.update_relationships_calls += 1
        return {}, {}, {}

    def update_relationships_from_index(
        self, *args: Any, **kwargs: Any
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        del args, kwargs
        self.update_relationships_calls += 1
        return {}, {}, {}

    def clear(self) -> None:
        self.clear_calls += 1


class _RecordingFooter:
    def __init__(self) -> None:
        self.update_bindings_calls = 0
        self.show_empty_calls = 0

    def update_bindings(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.update_bindings_calls += 1

    def show_empty(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.show_empty_calls += 1


class _RecordingSearchPanel:
    def update_query(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


class _FakeApp(ChangeSpecMixin, MarkingMixin):
    """Minimal app exercising the changespecs display + marking flow."""

    def __init__(self, count: int = 5) -> None:
        from sase.ace.query import parse_query

        self.changespecs = [make_changespec(name=f"feat_{i}") for i in range(count)]
        self._all_changespecs = list(self.changespecs)
        self.current_idx = 0
        self.current_tab = "changespecs"
        self.parsed_query = parse_query('"feature"')
        self.canonical_query_string = '"feature"'
        self.query_string = '"feature"'
        self.hide_reverted = True
        self.hide_submitted = True
        self.marked_indices: set[int] = set()
        self.refresh_interval = 0
        self._countdown_remaining = 0
        self._hidden_reverted_count = 0
        self._query_reverted_count = 0
        self._hidden_submitted_count = 0
        self._query_submitted_count = 0
        self._hint_mode_active = False
        self._hint_mode_hints_for: str | None = None
        self._hint_mappings: dict[int, str] = {}
        self._hook_hint_to_idx: dict[int, int] = {}
        self._hint_to_entry_id: dict[int, str] = {}
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._ancestor_keys: dict[str, str] = {}
        self._children_keys: dict[str, str] = {}
        self._sibling_keys: dict[str, str] = {}

        self.hooks_collapsed = FoldLevel.COLLAPSED
        self.commits_collapsed = FoldLevel.COLLAPSED
        self.mentors_collapsed = FoldLevel.COLLAPSED
        self.timestamps_collapsed = FoldLevel.COLLAPSED
        self.deltas_collapsed = FoldLevel.COLLAPSED

        self.list_widget = _RecordingList()
        self.detail_widget = _RecordingDetail()
        self.ancestors_panel = _RecordingAncestors()
        self.footer_widget = _RecordingFooter()
        self.search_panel = _RecordingSearchPanel()

        self._w_changespec_list: Any = self.list_widget
        self._w_changespec_detail: Any = self.detail_widget
        self._w_ancestors_children: Any = self.ancestors_panel
        self._w_footer: Any = self.footer_widget
        self._w_search_query_panel: Any = self.search_panel
        self._w_changespec_info_panel: Any = None  # info panel falls through

        self.scheduled: list[tuple[float, Callable[[], None]]] = []
        self._changespec_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.notifications: list[tuple[str, str]] = []

    def query_one(self, selector: str, _type: Any = None) -> Any:
        del selector, _type
        raise _NoMatches()

    def set_timer(self, delay: float, callback: Callable[[], None]) -> _Timer:
        self.scheduled.append((delay, callback))
        return _Timer()

    def notify(self, msg: str, *, severity: str = "information") -> None:
        self.notifications.append((msg, severity))

    def _update_cls_tab_count(self) -> None:
        return


def test_debounced_refresh_50_idx_changes_zero_update_list() -> None:
    """50 j/k navigations must produce zero ``update_list`` calls."""
    app = _FakeApp(count=10)

    for _ in range(50):
        app._refresh_changespecs_display_debounced()

    assert app.list_widget.update_list_calls == 0
    assert app.list_widget.clear_options_calls == 0
    # update_highlight runs once per nav event.
    assert len(app.list_widget.update_highlight_calls) == 50


def test_debounced_refresh_does_not_call_clear_options() -> None:
    """Pure j/k navigation must never clear the OptionList."""
    app = _FakeApp()
    app._refresh_changespecs_display_debounced()
    assert app.list_widget.clear_options_calls == 0


def test_detail_only_refresh_skips_update_list() -> None:
    """``_refresh_changespec_detail_only`` updates detail/ancestors/footer only."""
    app = _FakeApp()
    app._refresh_changespec_detail_only()

    assert app.list_widget.update_list_calls == 0
    assert app.detail_widget.update_display_calls == 1
    assert app.ancestors_panel.update_relationships_calls == 1
    assert app.footer_widget.update_bindings_calls == 1


def test_full_refresh_still_calls_update_list() -> None:
    """``_refresh_display`` is the list-shape path and still rebuilds."""
    app = _FakeApp()
    app._refresh_display()

    assert app.list_widget.update_list_calls == 1
    assert app.detail_widget.update_display_calls == 1
    assert app.ancestors_panel.update_relationships_calls == 1
    assert app.footer_widget.update_bindings_calls == 1


def test_mark_toggle_calls_patch_changespec_row_once_no_clear_options() -> None:
    """Toggling mark on one visible row patches once, never clears options."""
    app = _FakeApp(count=3)
    app.current_idx = 0

    app._toggle_mark_changespec()

    assert len(app.list_widget.patch_calls) == 1
    idx, name, selected, marked = app.list_widget.patch_calls[0]
    assert idx == 0
    assert name == "feat_0"
    assert selected is True
    assert marked is True
    # Auto-nav advances the cursor afterwards but must not clear options.
    assert app.list_widget.clear_options_calls == 0
    assert app.list_widget.update_list_calls == 0


def test_mark_toggle_falls_back_to_full_refresh_on_patch_failure() -> None:
    """When the widget rejects the patch (width grew, etc.) fall back."""
    app = _FakeApp(count=3)
    app.list_widget.patch_returns = False

    app._toggle_mark_changespec()

    assert len(app.list_widget.patch_calls) == 1
    # Fallback fires update_list exactly once.
    assert app.list_widget.update_list_calls == 1
