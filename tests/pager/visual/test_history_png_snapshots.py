"""Deterministic PNG goldens for memory-history pager read states.

Covers the sase-1dr.6 read view in three honest states — past read view,
dirty now, and deletion tombstone — at 120x40 and 60x30 in dark and light
themes. Sections use fixed bodies, fixed commit/blob OIDs, and an empty age
string so screenshots never depend on checkout history or today's time. The
real provider registry is cleared so no git/file I/O can leak in; history
chrome/gutter state is injected deterministically after mount.
"""

from __future__ import annotations

import pytest

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection, RawSourceSpec
from sase.pager._screen_syntax import _syntax_key_for_section  # noqa: PLC2701
from sase.pager.history.models import (
    SectionTimeState,
    committed_pin_for_ordinal,
    live_pin_for_subject,
)
from sase.pager.history.provider import clear_history_provider_factories
from sase.pager.screen import PagerScreen
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SIZES = [(120, 40), (60, 30)]

_COMMIT_V1 = "1111111111111111111111111111111111111111"
_COMMIT_V2 = "2222222222222222222222222222222222222222"
_COMMIT_V3 = "3333333333333333333333333333333333333333"
_BLOB_V2 = "aabbccddeeff00112233445566778899aabbccdd"
_BLOB_V3 = "ddeeff00112233445566778899aabbccddaabbcc"

_IDENTITY = "note:project:memory/garden"
_SUBJECT_ID = "note:project:memory/garden"
_TITLE = "memory/garden.md"

_PAST_BODY = (
    "# Garden note\n"
    "\n"
    "Soil is ready for spring planting.\n"
    "Added: compost row along the north bed.\n"
    "Changed: water schedule is now twice weekly.\n"
    "Keep the stone path clear of weeds.\n"
    "\n"
    "## Next steps\n"
    "\n"
    "- Sow carrots in the east row.\n"
    "- Label the seed trays.\n"
)

_DIRTY_BODY = (
    "# Garden note\n"
    "\n"
    "Soil is ready for spring planting.\n"
    "Uncommitted: drafted a new herb spiral sketch.\n"
    "Changed: water schedule is now twice weekly.\n"
    "Keep the stone path clear of weeds.\n"
    "\n"
    "## Next steps\n"
    "\n"
    "- Sow carrots in the east row.\n"
    "- Label the seed trays.\n"
)

_TOMBSTONE_BODY = (
    "✖ deleted by Test Author at 20200101 — last content shown\n"
    "\n"
    "# Garden note\n"
    "\n"
    "This note was removed when the beds were replanted.\n"
)


class _SnapshotPager(SasePager):
    """Apply the snapshot theme before the pager screen mounts."""

    def __init__(
        self,
        document: PagerDocument,
        *,
        theme_name: str | None = None,
    ) -> None:
        super().__init__(document)
        self._theme_name = theme_name

    def on_mount(self) -> None:
        if self._theme_name is not None:
            self.theme = self._theme_name
        super().on_mount()


class _SvgExport:
    def __init__(self, app: SasePager) -> None:
        self._app = app

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        return self._app.export_screenshot(title=title, simplify=simplify)


def _section_for_state(state: str) -> PagerSection:
    raw = RawSourceSpec(language="markdown")
    if state == "past":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            2,
            commit=_COMMIT_V2,
            blob_oid=_BLOB_V2,
        )
        return PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body=_PAST_BODY,
            subject_ref=_SUBJECT_ID,
            raw_source=raw,
            version_pin=pin,
        )
    if state == "tombstone":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            3,
            commit=_COMMIT_V3,
            blob_oid=_BLOB_V3,
        )
        return PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body=_TOMBSTONE_BODY,
            subject_ref=_SUBJECT_ID,
            raw_source=raw,
            version_pin=pin,
        )
    return PagerSection(
        identity=_IDENTITY,
        title=_TITLE,
        kind="file",
        body=_DIRTY_BODY,
        subject_ref=_SUBJECT_ID,
        raw_source=raw,
    )


def _inject_history_state(screen: PagerScreen, state: str) -> None:
    """Populate deterministic per-section history state for *state*."""
    if state == "past":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            2,
            commit=_COMMIT_V2,
            blob_oid=_BLOB_V2,
        )
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="live",
            visible_ordinals=(1, 2, 3),
            current_pin=pin,
        )
        time_state.comparison_cache[(1, 2)] = {
            "line_marks": [4, 5],
            "word_ops": [
                {"target_line": 5, "ops": [{"kind": "replace"}]},
            ],
            "removal_anchors": [6],
        }
    elif state == "tombstone":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            3,
            commit=_COMMIT_V3,
            blob_oid=_BLOB_V3,
        )
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="tombstone",
            visible_ordinals=(1, 2, 3),
            current_pin=pin,
        )
    else:
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="dirty-now",
            visible_ordinals=(1, 2, 3),
            current_pin=live_pin_for_subject(_SUBJECT_ID),
        )
    screen._history_states[_IDENTITY] = time_state
    screen._history_supported[_IDENTITY] = True
    screen._body_width = None
    screen._ensure_body()
    screen._update_subject()
    screen._update_footer()


@pytest.mark.parametrize("size", _SIZES)
@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("state", ["past", "dirty", "tombstone"])
async def test_history_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    size: tuple[int, int],
    light: bool,
    state: str,
) -> None:
    clear_history_provider_factories()
    try:
        section = _section_for_state(state)
        document = PagerDocument(
            sections=(section,),
            title=_TITLE,
            origin=PagerOrigin.FILE,
        )
        theme_label = "light" if light else "dark"
        app = _SnapshotPager(
            document,
            theme_name="textual-light" if light else None,
        )
        async with app.run_test(size=size) as pilot:
            screen = app.screen
            assert isinstance(screen, PagerScreen)
            await wait_for(
                pilot,
                lambda: (
                    _syntax_key_for_section(section) in screen._syntax_prepared
                    and not screen._syntax_pass_running
                ),
            )
            _inject_history_state(screen, state)
            await pilot.pause()
            pager_png_visual.assert_page_png(
                _SvgExport(app),
                f"history_{state}_{theme_label}_{size[0]}x{size[1]}",
                title=f"SasePager: history {state} ({theme_label})",
            )
    finally:
        clear_history_provider_factories()
