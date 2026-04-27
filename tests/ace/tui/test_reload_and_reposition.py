"""Tests for _reload_and_reposition base name fallback logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.changespec import ChangeSpecMixin


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


class FakeApp(ChangeSpecMixin):
    """Minimal stand-in for AceApp with just what _reload_and_reposition needs."""

    def __init__(self, changespecs: list[MagicMock]) -> None:
        self.changespecs: list = changespecs  # type: ignore[assignment]
        self.current_idx: int = 0
        self.current_tab = "changespecs"
        self.parsed_query = MagicMock()
        self.query_string = ""
        self.hide_reverted = False
        self.hide_submitted = False
        self._all_changespecs: list = changespecs  # type: ignore[assignment]
        self.marked_indices: set[int] = set()
        self._changespecs_last_idx: int = 0
        self._changespecs_last_name: str | None = None
        self._query_reverted_count = 0
        self._query_submitted_count = 0
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0

    def _update_cls_tab_count(self) -> None:
        pass

    def _refresh_display(self) -> None:
        pass

    @property
    def canonical_query_string(self) -> str:
        return ""


@pytest.fixture
def _patch_loaders():
    """Patch find_all_changespecs and _filter_changespecs to return controlled data."""
    fake_changespecs: list[MagicMock] = []

    def _set(cs_list: list[MagicMock]) -> None:
        fake_changespecs.clear()
        fake_changespecs.extend(cs_list)

    with (
        patch.object(
            ChangeSpecMixin,
            "_filter_changespecs",
            side_effect=lambda _all_cs: fake_changespecs,
        ),
        patch(
            "sase.ace.changespec.find_all_changespecs",
            side_effect=lambda: fake_changespecs,
        ),
    ):
        yield _set


def test_exact_name_match(_patch_loaders) -> None:  # type: ignore[no-untyped-def]
    """Exact name match still works -- no fallback needed."""
    cs_list = [_make_cs("alpha"), _make_cs("beta"), _make_cs("gamma")]
    _patch_loaders(cs_list)

    app = FakeApp(cs_list)
    app._reload_and_reposition(current_name="beta")
    assert app.current_idx == 1


def test_fallback_suffix_stripped(_patch_loaders) -> None:  # type: ignore[no-untyped-def]
    """Draft->Ready strips suffix: current_name='foo_1', disk has 'foo'."""
    cs_list = [_make_cs("alpha"), _make_cs("foo"), _make_cs("gamma")]
    _patch_loaders(cs_list)

    app = FakeApp(cs_list)
    app._reload_and_reposition(current_name="foo_1")
    assert app.current_idx == 1
    assert app.changespecs[app.current_idx].name == "foo"


def test_fallback_suffix_appended(_patch_loaders) -> None:  # type: ignore[no-untyped-def]
    """Ready->Draft appends suffix: current_name='foo', disk has 'foo_1'."""
    cs_list = [_make_cs("alpha"), _make_cs("foo_1"), _make_cs("gamma")]
    _patch_loaders(cs_list)

    app = FakeApp(cs_list)
    app._reload_and_reposition(current_name="foo")
    assert app.current_idx == 1
    assert app.changespecs[app.current_idx].name == "foo_1"


def test_fallback_no_match(_patch_loaders) -> None:  # type: ignore[no-untyped-def]
    """Identity gone -> nearest-neighbor (clamped prior visual row).

    Plan §4.1 of tui_selection_drift.md: rather than snap to row 0,
    landing on the same visible row position keeps the cursor near
    where the user was looking. ``current_idx`` defaults to 0 in the
    FakeApp, so the prior visual row is 0 and the post-rebuild row
    happens to be 0 too — but the path under test is the helper
    fallback, not the historical hard-coded zero.
    """
    cs_list = [_make_cs("alpha"), _make_cs("beta")]
    _patch_loaders(cs_list)

    app = FakeApp(cs_list)
    app._reload_and_reposition(current_name="nonexistent")
    assert app.current_idx == 0


def test_nearest_neighbor_when_selected_changespec_filtered_out(  # type: ignore[no-untyped-def]
    _patch_loaders,
) -> None:
    """Submitting a CL must not snap the cursor back to row 0.

    Reproduces the §3.1 ChangeSpecs drift mode: user is selected on
    row 3 of [a, b, c, d, e]; CL ``d`` is submitted and filtered out
    of the new list [a, b, c, e]. The cursor should land on row 3
    (the new ``e``, the agent visually below the submitted entry),
    not snap to row 0.
    """
    new_list = [_make_cs("a"), _make_cs("b"), _make_cs("c"), _make_cs("e")]
    _patch_loaders(new_list)

    original = [
        _make_cs("a"),
        _make_cs("b"),
        _make_cs("c"),
        _make_cs("d"),
        _make_cs("e"),
    ]
    app = FakeApp(original)
    app.current_idx = 3  # On "d" before submit

    app._reload_and_reposition(current_name="d")
    assert app.current_idx == 3
    assert app.changespecs[app.current_idx].name == "e"


def test_off_tab_reload_does_not_mutate_current_idx(  # type: ignore[no-untyped-def]
    _patch_loaders,
) -> None:
    """An off-tab refresh must leave current_idx alone.

    ``current_idx`` belongs to the active tab. When the file watcher
    fires while the user is on Agents/AXE, the changespec reload
    should restore the saved row + name without overwriting the
    cursor position the active tab is using.
    """
    new_list = [_make_cs("a"), _make_cs("b"), _make_cs("c")]
    _patch_loaders(new_list)

    app = FakeApp(new_list)
    app.current_tab = "agents"  # off-tab
    app.current_idx = 12  # arbitrary value owned by the agents tab
    app._changespecs_last_idx = 1
    app._changespecs_last_name = "b"

    app._reload_and_reposition()
    # current_idx untouched
    assert app.current_idx == 12
    # saved-row points at b's new row (still 1 here, but the path is
    # what matters)
    assert app._changespecs_last_idx == 1
    assert app._changespecs_last_name == "b"
