"""Pilot tests for the ``@`` timeline picker modal."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing.wait import wait_for
from sase.pager._timeline_picker import TimelinePickerScreen
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import live_pin_for_subject
from sase.pager.history.provider import (
    clear_history_provider_factories,
    register_history_provider_factory,
)
from sase.pager.screen import PagerScreen

from ._app_helpers import pager_screen

_SUBJECT_ID = "note:project:sase/garden"
_IDENTITY = "sase/memory/garden.md"

_UNIFIED = "@@ -1,2 +1,2 @@\n line\n-old\n+new\n"


def _version(
    ordinal: int,
    class_name: str,
    bead: str = "",
    subject: str = "",
    section: str = "",
) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "class": class_name,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790486400,
        "path": "sase/memory/garden.md",
        "summary": {
            "section_paths": [section] if section else [],
            "words_added": 2 if section else 0,
            "words_removed": 0,
        },
        "provenance": {
            "agent": f"athena.{bead}" if bead else "",
            "bead": bead,
            "subject": subject,
        },
    }


def _timeline() -> dict[str, object]:
    return {
        "versions": [
            {
                "ordinal": 0,
                "class": "uncommitted",
                "commit": "",
                "committer_time": 0,
                "path": "sase/memory/garden.md",
                "summary": {},
                "provenance": {},
            },
            _version(3, "authored", "sase-9.3", "feat: plant", "Planting"),
            _version(2, "moved"),
            _version(1, "created", section=" beds"),
        ],
    }


def _comparison() -> dict[str, object]:
    return {
        "frontmatter": {"entries": [], "type_change": None},
        "line_marks": [1],
        "word_ops": [],
        "hunks": [],
        "removal_anchors": [],
        "stats": {},
        "unified_diff": _UNIFIED,
    }


class _FakeHistoryProvider:
    provider_key = "fake-history"

    def recognizes(self, section: PagerSection) -> bool:
        return True

    def load_timeline(self, section: PagerSection) -> dict[str, object]:
        return _timeline()

    def load_version(self, section: PagerSection, ordinal: int) -> PagerSection | None:
        from sase.pager.history.models import committed_pin_for_ordinal

        if ordinal == 0:
            pin = live_pin_for_subject(_SUBJECT_ID)
            return PagerSection(
                identity=section.identity,
                title=section.title,
                kind=section.kind,
                body="live body\n",
                subject_ref=section.subject_ref,
                version_pin=pin,
            )
        pin = committed_pin_for_ordinal(_SUBJECT_ID, ordinal)
        return PagerSection(
            identity=section.identity,
            title=section.title,
            kind=section.kind,
            body=f"body v{ordinal}\n",
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
        body="live body\n",
        subject_ref=_SUBJECT_ID,
    )
    return PagerDocument(
        sections=(section,), title="garden.md", origin=PagerOrigin.FILE
    )


@pytest.fixture
def fake_history_provider():  # type: ignore[no-untyped-def]
    clear_history_provider_factories()
    register_history_provider_factory(lambda: _FakeHistoryProvider())
    try:
        yield
    finally:
        clear_history_provider_factories()


async def _ready_screen(pilot, app: SasePager) -> PagerScreen:  # type: ignore[no-untyped-def]
    screen = pager_screen(app)
    await wait_for(
        pilot,
        lambda: any(
            state.visible_ordinals for state in screen._history_states.values()
        ),
    )
    return screen


async def _open_picker(pilot, app: SasePager) -> TimelinePickerScreen:  # type: ignore[no-untyped-def]
    await pilot.press("at")
    await pilot.pause()
    screen = app.screen
    assert isinstance(screen, TimelinePickerScreen)
    return screen


def _list_text(picker: TimelinePickerScreen) -> str:
    return picker.query_one("#pager-timeline-list", Static).visual.plain  # type: ignore[attr-defined]


async def test_at_lists_versions_and_footer_names_timeline(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(100, 24)) as pilot:
        screen = await _ready_screen(pilot, app)
        footer = screen.query_one("#pager-footer", Static)
        assert "@ timeline" in footer.visual.plain  # type: ignore[attr-defined]

        picker = await _open_picker(pilot, app)
        header = picker.query_one("#pager-timeline-header", Static)
        assert header.visual.plain.count("/ filter") == 1  # type: ignore[attr-defined]
        text = _list_text(picker)
        assert "now" in text
        assert "v3" in text
        assert "v1" in text
        # Hidden moves stay out until `.`.
        assert "v2" not in text
        assert "hidden" in text

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen


async def test_enter_jumps_and_pushes_a_trail_entry(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(100, 24)) as pilot:
        screen = await _ready_screen(pilot, app)
        await _open_picker(pilot, app)

        await pilot.press("j")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: (
                int(getattr(screen.document.sections[0].version_pin, "ordinal", 0) or 0)
                == 3
            ),
        )

        assert app.screen is screen
        assert screen._back_trail
        assert "body v3" in screen.document.sections[0].plain_text


async def test_equals_compares_row_with_open_version(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(100, 24)) as pilot:
        screen = await _ready_screen(pilot, app)
        await _open_picker(pilot, app)

        await pilot.press("j")
        await pilot.pause()
        await pilot.press("=")
        await wait_for(
            pilot,
            lambda: (
                getattr(screen.document.sections[0].version_pin, "view", "read")
                == "diff"
            ),
        )

        pin = screen.document.sections[0].version_pin
        assert pin is not None and pin.compare_base == 3
        state = screen._history_states[_IDENTITY]
        assert (3, 0) in state.comparison_cache


async def test_period_toggles_hidden_versions(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(100, 24)) as pilot:
        await _ready_screen(pilot, app)
        picker = await _open_picker(pilot, app)
        assert "v2" not in _list_text(picker)

        await pilot.press("full_stop")
        await pilot.pause()
        assert "v2" in _list_text(picker)

        await pilot.press("full_stop")
        await pilot.pause()
        assert "v2" not in _list_text(picker)


async def test_slash_filters_across_bead_and_section(
    fake_history_provider: object,
) -> None:
    app = SasePager(_live_document())
    async with app.run_test(size=(100, 24)) as pilot:
        await _ready_screen(pilot, app)
        picker = await _open_picker(pilot, app)

        await pilot.press("slash")
        await pilot.pause()
        assert picker.is_filtering
        for character in "sase-9.3":
            await pilot.press(character)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert not picker.is_filtering
        text = _list_text(picker)
        assert "v3" in text
        assert "v1" not in text

        await pilot.press("escape")
        await pilot.pause()
        assert "v1" in _list_text(picker)
