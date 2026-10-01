"""Deterministic PNG goldens for the ``@`` timeline picker modal.

Covers the sase-1dr.9 picker in its default list state (worktree row,
committed rows, and the hidden-versions summary row) and in a filtered
state, at 120x40 and 60x30 in dark and light themes. Rows come from
the real memory-side builder over a fixed timeline with fixed epochs,
so screenshots never depend on checkout history or today's time. The
real provider registry is cleared so no git/file I/O can leak in.
"""

from __future__ import annotations

import pytest

from sase.memory.history.timeline_picker import (
    build_picker_rows,
    hidden_picker_rows,
    hidden_summary_text,
    picker_header_text,
)
from sase.pager._timeline_picker import TimelinePickerScreen
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection, RawSourceSpec
from sase.pager.history.models import committed_pin_for_ordinal
from sase.pager.history.provider import clear_history_provider_factories
from sase.pager.screen import PagerScreen
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SIZES = [(120, 40), (60, 30)]

_NOW_EPOCH = 1790700000
_COMMIT_V1 = "1111111111111111111111111111111111111111"
_COMMIT_V8 = "2222222222222222222222222222222222222222"
_COMMIT_V9 = "3333333333333333333333333333333333333333"

_IDENTITY = "note:project:memory/garden"
_SUBJECT_ID = "note:project:memory/garden"
_TITLE = "memory/garden.md"

_TIMELINE = {
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
        {
            "ordinal": 9,
            "class": "authored",
            "commit": _COMMIT_V9,
            "committer_time": 1790486400,
            "path": "sase/memory/garden.md",
            "summary": {
                "section_paths": ["Default Keymap Config"],
                "words_added": 31,
                "words_removed": 4,
            },
            "provenance": {
                "agent": "athena.sase-1bc.12",
                "bead": "sase-1bc.12",
                "subject": "feat(tui): keymaps",
            },
        },
        {
            "ordinal": 8,
            "class": "promoted",
            "commit": _COMMIT_V8,
            "committer_time": 1790054400,
            "path": "sase/memory/garden.md",
            "summary": {
                "section_paths": [],
                "words_added": 0,
                "words_removed": 0,
                "frontmatter_phrase": "promoted reference → core",
            },
            "provenance": {
                "agent": "athena.sase-1au.5",
                "bead": "sase-1au.5",
                "subject": "feat(memory): promote",
            },
        },
        {
            "ordinal": 7,
            "class": "moved",
            "commit": _COMMIT_V1,
            "committer_time": 1789000000,
            "path": "memory/garden.md",
            "summary": {},
            "provenance": {},
        },
        {
            "ordinal": 1,
            "class": "created",
            "commit": _COMMIT_V1,
            "committer_time": 1788000000,
            "path": "memory/garden.md",
            "summary": {"section_paths": [], "created_words": 412},
            "provenance": {},
        },
    ]
}


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


def _picker_for_state(state: str) -> TimelinePickerScreen:
    rows = build_picker_rows(_TIMELINE, now_epoch=_NOW_EPOCH)
    hidden = hidden_picker_rows(rows)
    total_committed = sum(1 for row in rows if not bool(row.get("pseudo", False)))
    header = picker_header_text(
        subject_display="garden.md",
        total_committed=total_committed,
        hidden_count=len(hidden),
        show_hidden=False,
        query="",
    )
    picker = TimelinePickerScreen(
        title=header,
        rows=rows,
        current_ordinal=8,
        current_class="",
        hidden_summary=hidden_summary_text(hidden),
        initial_cursor=1,
    )
    if state == "filtered":
        picker._query = "keymap"  # noqa: SLF001 — deterministic pre-filter
        picker._cursor = 0  # noqa: SLF001 — deterministic pre-filter
    return picker


def _picker_many() -> TimelinePickerScreen:
    versions: list[dict[str, object]] = []
    for ordinal in range(260, 0, -1):
        versions.append(
            {
                "ordinal": ordinal,
                "class": "authored",
                "commit": f"{ordinal:040d}",
                "committer_time": 1790486400 - ordinal * 3600,
                "path": "sase/memory/garden.md",
                "summary": {
                    "section_paths": [f"Section {ordinal}"],
                    "words_added": ordinal % 97,
                    "words_removed": ordinal % 5,
                },
                "provenance": {
                    "agent": f"athena.sase-1dr.{ordinal}",
                    "bead": f"sase-1dr.{ordinal}",
                    "subject": f"edit number {ordinal}",
                },
            }
        )
    rows = build_picker_rows(
        {"versions": versions},
        now_epoch=_NOW_EPOCH,
        now_matches_newest=True,
        newest=260,
    )
    hidden = hidden_picker_rows(rows)
    header = picker_header_text(
        subject_display="garden.md",
        total_committed=260,
        hidden_count=len(hidden),
        show_hidden=False,
        query="",
        pill_text="⟲ PAST · v130",
    )
    return TimelinePickerScreen(
        title=header,
        rows=rows,
        current_ordinal=130,
        current_class="",
        hidden_summary=hidden_summary_text(hidden),
        initial_cursor=132,
    )


@pytest.mark.parametrize("light", [False, True])
async def test_timeline_picker_many_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    light: bool,
) -> None:
    clear_history_provider_factories()
    try:
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            130,
            commit=f"{130:040d}",
        )
        section = PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body="# Garden note\n",
            subject_ref=_SUBJECT_ID,
            raw_source=RawSourceSpec(language="markdown"),
            version_pin=pin,
        )
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
        async with app.run_test(size=(60, 30)) as pilot:
            screen = app.screen
            assert isinstance(screen, PagerScreen)
            await pilot.pause()
            app.push_screen(_picker_many())
            await pilot.pause()
            await pilot.pause()
            pager_png_visual.assert_page_png(
                _SvgExport(app),
                f"timeline_picker_many_{theme_label}_60x30",
                title=f"SasePager: timeline picker many ({theme_label})",
            )
    finally:
        clear_history_provider_factories()


@pytest.mark.parametrize("size", _SIZES)
@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("state", ["default", "filtered"])
async def test_timeline_picker_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    size: tuple[int, int],
    light: bool,
    state: str,
) -> None:
    clear_history_provider_factories()
    try:
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            8,
            commit=_COMMIT_V8,
        )
        section = PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body="# Garden note\n",
            subject_ref=_SUBJECT_ID,
            raw_source=RawSourceSpec(language="markdown"),
            version_pin=pin,
        )
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
            await pilot.pause()
            app.push_screen(_picker_for_state(state))
            await pilot.pause()
            await pilot.pause()
            pager_png_visual.assert_page_png(
                _SvgExport(app),
                f"timeline_picker_{state}_{theme_label}_{size[0]}x{size[1]}",
                title=f"SasePager: timeline picker {state} ({theme_label})",
            )
    finally:
        clear_history_provider_factories()
