"""Pilot tests for split panes and ``ctrl+w`` over memory history: source-pane
loading, band labels, and focus-scoped band hint letters.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

import pytest

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import committed_pin_for_ordinal
from sase.pager.history.provider import (
    clear_history_provider_factories,
    register_history_provider_factory,
)
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.view import PagerView

from ._app_helpers import pager_screen, target_document


class _SplitHistoryProvider:
    """Three-version provider whose timeline load can be held open."""

    provider_key = "split-history-fake"
    IDENTITY = "probe:/tmp/split-history.md"
    gate: threading.Event | None = None

    def recognizes(self, section: PagerSection) -> bool:
        return section.identity == self.IDENTITY

    def load_timeline(self, section: PagerSection) -> dict[str, object]:
        gate = type(self).gate
        if gate is not None:
            gate.wait(5)
        return {
            "versions": [
                {"ordinal": 1, "commit": "a" * 40, "blob_oid": "a" * 40},
                {"ordinal": 2, "commit": "b" * 40, "blob_oid": "b" * 40},
                {"ordinal": 3, "commit": "c" * 40, "blob_oid": "c" * 40},
            ],
            "worktree_oid": "c" * 40,
            "head_oid": "c" * 40,
        }

    def load_version(self, section: PagerSection, ordinal: int) -> PagerSection | None:
        if ordinal == 0:
            return replace(section, body=_BODY, version_pin=None)
        letter = "abc"[ordinal - 1]
        pin = committed_pin_for_ordinal(
            section.subject_ref or section.identity,
            ordinal,
            commit=letter * 40,
            blob_oid=letter * 40,
        )
        return replace(
            section,
            body=f"version {ordinal} body\n",
            version_pin=pin,  # type: ignore[arg-type]
        )

    def compare_versions(
        self, section: PagerSection, base_ordinal: int, target_ordinal: int
    ) -> dict[str, object] | None:
        return {"line_marks": [1], "word_ops": [], "removal_anchors": []}

    def resolve_historical_link(
        self, section: PagerSection, ref: str
    ) -> PagerSection | None:
        return None

    def refresh(self, section: PagerSection) -> PagerSection | None:
        return replace(section, version_pin=None)


_BODY = "see /tmp/target.py for details\nsecond line\n"


def _history_document() -> PagerDocument:
    section = PagerSection(
        identity=_SplitHistoryProvider.IDENTITY,
        title="split-history.md",
        kind="file",
        body=_BODY,
        subject_ref=_SplitHistoryProvider.IDENTITY,
    )
    return PagerDocument(
        sections=(section,), title="split-history.md", origin=PagerOrigin.FILE
    )


def _document_resolver(target: PagerDocument) -> Any:
    def resolve(ref: str, **_kwargs: Any) -> LinkTarget:
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    return resolve


def _ordinal(view: PagerView) -> int | None:
    state = view._history_states.get(_SplitHistoryProvider.IDENTITY)
    if state is None or state.current_pin is None:
        return None
    return state.current_pin.ordinal


@pytest.fixture
def split_history_provider() -> Any:
    clear_history_provider_factories()
    register_history_provider_factory(_SplitHistoryProvider)
    try:
        yield _SplitHistoryProvider
    finally:
        gate = _SplitHistoryProvider.gate
        if gate is not None:
            gate.set()
        _SplitHistoryProvider.gate = None
        clear_history_provider_factories()


async def test_ctrl_w_keeps_source_pane_history_loading(
    split_history_provider: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    split_history_provider.gate = gate
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    app = SasePager(_history_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source = screen.views[0]
        await pilot.press("ctrl+w")
        await pilot.press("0")
        await wait_for(
            pilot,
            lambda: len(screen.views) == 2 and screen.views[1].document is target,
        )
        # The source pane stayed put, so its in-flight discovery must land.
        gate.set()
        await wait_for(pilot, lambda: _ordinal(source) == 0)
        assert screen._focused_index == 0
        assert screen.views[0] is source


async def test_ctrl_w_band_commit_label_opens_in_other_pane(
    split_history_provider: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    app = SasePager(_history_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        source = screen.views[0]
        await wait_for(pilot, lambda: _ordinal(source) == 0)
        await pilot.press("(")
        await wait_for(pilot, lambda: _ordinal(source) == 2)
        await wait_for(pilot, lambda: bool(source._time_band_hints))
        (band_hint,) = source._time_band_hints
        await pilot.press("ctrl+w")
        await pilot.press(band_hint)
        await wait_for(
            pilot,
            lambda: len(screen.views) == 2 and screen.views[1].document is target,
        )
        assert screen._focused_index == 0
        assert screen.views[0] is source
        assert _ordinal(source) == 2
        assert "version 2 body" in source.document.sections[0].plain_text
        assert source._pending_action == "follow"


async def test_unfocused_pane_drops_band_hint_letters(
    split_history_provider: Any,
) -> None:
    app = SasePager(_history_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        first = screen.views[0]
        await wait_for(pilot, lambda: _ordinal(first) == 0)
        await pilot.press("(")
        await wait_for(pilot, lambda: _ordinal(first) == 2)
        await wait_for(pilot, lambda: bool(first._time_band_hints))
        await pilot.press("\\")
        await wait_for(pilot, lambda: len(screen.views) == 2)
        second = screen.views[1]
        assert screen._focused_index == 1
        await wait_for(pilot, lambda: bool(second._time_band_hints))
        assert first._time_band_hints == {}
        assert first._time_band_labels
        await pilot.press("ctrl+f")
        await wait_for(pilot, lambda: bool(first._time_band_hints))
        assert second._time_band_hints == {}
