"""Pilot tests for the history diff view: ``=``, ``[``/``]``, folds, ``yy``."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.diff import FOLD_TARGET_KIND
from sase.pager.history.models import (
    SectionTimeState,
    committed_pin_for_ordinal,
    live_pin_for_subject,
)
from sase.pager.history.provider import (
    clear_history_provider_factories,
    register_history_provider_factory,
)
from sase.pager.screen import PagerScreen

from ._app_helpers import body_scroll, pager_screen

_SUBJECT_ID = "note:project:sase/garden"
_IDENTITY = "sase/memory/garden.md"

_UNIFIED = "@@ -8,3 +8,3 @@\n line 7\n-old word\n+new word\n line 9\n"


def _target_body(version: int) -> str:
    lines = [f"filler line {index}" for index in range(1, 61)]
    if version == 1:
        lines[7] = "old word here"
        lines[49] = "second old word"
    else:
        lines[7] = "new word here"
        lines[49] = "second new word"
    return "\n".join(lines) + "\n"


def _comparison() -> dict[str, object]:
    return {
        "frontmatter": {"entries": [], "type_change": None},
        "line_marks": [8, 50],
        "word_ops": [
            {
                "target_line": 8,
                "ops": [
                    {"kind": "equal", "text": "new ", "start": 0, "end": 4},
                    {"kind": "delete", "text": "old", "start": 4, "end": 4},
                    {"kind": "insert", "text": "new", "start": 4, "end": 7},
                    {"kind": "equal", "text": " word here", "start": 7, "end": 17},
                ],
            },
            {
                "target_line": 50,
                "ops": [
                    {"kind": "equal", "text": "second ", "start": 0, "end": 7},
                    {"kind": "delete", "text": "old", "start": 7, "end": 7},
                    {"kind": "insert", "text": "new", "start": 7, "end": 10},
                    {"kind": "equal", "text": " word", "start": 10, "end": 15},
                ],
            },
        ],
        "hunks": [
            {"target_start": 8, "target_end": 9},
            {"target_start": 50, "target_end": 51},
        ],
        "removal_anchors": [],
        "stats": {"words_added": 2, "words_removed": 2},
        "unified_diff": _UNIFIED,
    }


class _FakeHistoryProvider:
    provider_key = "fake-history"

    def recognizes(self, section: PagerSection) -> bool:
        return True

    def load_timeline(self, section: PagerSection) -> dict[str, object]:
        return {
            "versions": [
                {"ordinal": 1, "hidden": False, "class": "authored"},
                {"ordinal": 2, "hidden": False, "class": "authored"},
            ],
        }

    def load_version(self, section: PagerSection, ordinal: int) -> PagerSection | None:
        if ordinal == 0:
            pin = live_pin_for_subject(_SUBJECT_ID)
            return PagerSection(
                identity=section.identity,
                title=section.title,
                kind=section.kind,
                body=_target_body(2),
                subject_ref=section.subject_ref,
                version_pin=pin,
            )
        pin = committed_pin_for_ordinal(_SUBJECT_ID, ordinal)
        return PagerSection(
            identity=section.identity,
            title=section.title,
            kind=section.kind,
            body=_target_body(ordinal),
            subject_ref=section.subject_ref,
            version_pin=pin,
        )

    def compare_versions(
        self, section: PagerSection, base_ordinal: int, target_ordinal: int
    ) -> dict[str, object] | None:
        return _comparison()

    def resolve_historical_link(
        self, section: PagerSection, ref: str
    ) -> PagerSection | None:
        return None

    def refresh(self, section: PagerSection) -> PagerSection | None:
        return self.load_version(section, 0)


def _live_document() -> PagerDocument:
    section = PagerSection(
        identity=_IDENTITY,
        title="garden.md",
        kind="file",
        body=_target_body(2),
        subject_ref=_SUBJECT_ID,
    )
    return PagerDocument(
        sections=(section,), title="garden.md", origin=PagerOrigin.FILE
    )


def _diff_pin(section: PagerSection):  # type: ignore[no-untyped-def]
    pin = section.version_pin
    assert pin is not None
    return pin


async def _ready_screen(pilot, app: SasePager) -> PagerScreen:  # type: ignore[no-untyped-def]
    screen = pager_screen(app)
    await wait_for(
        pilot,
        lambda: any(
            state.visible_ordinals for state in screen._history_states.values()
        ),
    )
    return screen


@pytest.fixture
def fake_history_provider():  # type: ignore[no-untyped-def]
    clear_history_provider_factories()
    register_history_provider_factory(lambda: _FakeHistoryProvider())
    try:
        yield
    finally:
        clear_history_provider_factories()


async def test_equals_toggles_read_and_diff_views(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _ready_screen(pilot, app)
        footer = screen.query_one("#pager-footer", Static)
        assert "= diff" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("=")
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", "read")
                == "diff"
            ),
        )
        await pilot.pause()
        body = screen.document.sections[0].plain_text
        assert "unchanged line" in body
        assert "expand" in body
        assert "= read" in footer.visual.plain  # type: ignore[attr-defined]
        assert "diff vs v1" in screen.query_one("#pager-subject", Static).visual.plain  # type: ignore[attr-defined]

        await pilot.press("=")
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", None) != "diff"
            ),
        )
        assert screen.document.sections[0].plain_text == _target_body(2)
        assert "= diff" in footer.visual.plain  # type: ignore[attr-defined]


async def test_brackets_walk_changes_in_both_views(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(80, 10)) as pilot:
        screen = await _ready_screen(pilot, app)
        scroll = body_scroll(app)
        scroll.focus()

        await pilot.press("=")
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", "read")
                == "diff"
            ),
        )
        await pilot.pause()
        first = int(scroll.scroll_y)

        await pilot.press("]")
        await pilot.pause()
        await pilot.pause()
        assert int(scroll.scroll_y) >= first

        await pilot.press("[")
        await pilot.pause()
        await pilot.pause()
        assert int(scroll.scroll_y) <= first + 8


async def test_fold_label_expands_in_place(fake_history_provider: object) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _ready_screen(pilot, app)
        await pilot.press("=")
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", "read")
                == "diff"
            ),
        )
        await pilot.pause()
        assert (
            "filler line 1" not in screen.document.sections[0].plain_text.splitlines()
        )

        labels = [
            label
            for label in screen._label_layer.labels
            if label.target.kind == FOLD_TARGET_KIND
        ]
        assert labels
        screen._activate_label(labels[0])
        await pilot.pause()
        assert "filler line 1" in screen.document.sections[0].plain_text.splitlines()


async def test_toggle_is_sticky_across_version_steps(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _ready_screen(pilot, app)
        await pilot.press("=")
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", "read")
                == "diff"
            ),
        )
        await pilot.pause()

        await pilot.press("(")
        await wait_for(
            pilot,
            lambda: (
                int(getattr(screen.document.sections[0].version_pin, "ordinal", 0) or 0)
                == 2
            ),
        )
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", "read")
                == "diff"
            ),
        )


def test_yy_unified_branch_states() -> None:
    document = _live_document()
    screen = PagerScreen(document)
    read_section = document.sections[0]
    assert screen._diff_unified_for_section(read_section) == (False, False, "")

    pin = committed_pin_for_ordinal(_SUBJECT_ID, 2, commit="a" * 40)
    diff_section = PagerSection(
        identity=_IDENTITY,
        title="garden.md",
        kind="file",
        body="diff body\n",
        subject_ref=_SUBJECT_ID,
        version_pin=pin,
    )
    assert screen._diff_unified_for_section(diff_section) == (False, False, "")

    from dataclasses import replace

    diff_pin_section = PagerSection(
        identity=_IDENTITY,
        title="garden.md",
        kind="file",
        body="diff body\n",
        subject_ref=_SUBJECT_ID,
        version_pin=replace(pin, view="diff"),
    )
    state = SectionTimeState(
        provider_key="fake",
        subject_id=_SUBJECT_ID,
        scope_key="project",
        status="live",
        visible_ordinals=(1, 2),
        current_pin=replace(pin, view="diff"),
    )
    screen._history_states[_IDENTITY] = state
    assert screen._diff_unified_for_section(diff_pin_section) == (True, False, "")
    state.comparison_cache[(1, 2)] = _comparison()
    assert screen._diff_unified_for_section(diff_pin_section) == (True, True, _UNIFIED)
