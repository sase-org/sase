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
        self.parsed_query = MagicMock()
        self.query_string = ""
        self.hide_reverted = False
        self.hide_submitted = False
        self._all_changespecs: list = changespecs  # type: ignore[assignment]
        self.marked_indices: set[int] = set()
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
    """When nothing matches at all, falls back to index 0."""
    cs_list = [_make_cs("alpha"), _make_cs("beta")]
    _patch_loaders(cs_list)

    app = FakeApp(cs_list)
    app._reload_and_reposition(current_name="nonexistent")
    assert app.current_idx == 0
