"""Deterministic PNG goldens for the pager time band (phase `time-band`).

Covers the band at 120x40 and 60x30 in dark and light themes: the past
band (meaning + time rows), the dirty life strip, the instruction cause
band, the untracked honest notice, and the degraded one-row past band
with the trail band visible at 60x30. Sections use fixed bodies, fixed
commit/blob OIDs, and a pinned "now" epoch so screenshots never depend
on checkout history or today's time. The real provider registry is
cleared so no git/file I/O can leak in; history state is injected
deterministically after mount.
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
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.screen import PagerScreen
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SIZES = [(120, 40), (60, 30)]

_NOW = 1790769600  # 2026-09-30 12:00 UTC (pinned; TZ is forced to UTC)
_V1_TIME = 1789905600  # 2026-09-20 12:00 UTC
_V2_TIME = 1790085780  # 2026-09-22 14:03 UTC

_COMMIT_V1 = "1111111111111111111111111111111111111111"
_COMMIT_V2 = "1a2b3c40000000000000000000000000000000000"
_BLOB_V1 = "aabbccddeeff00112233445566778899aabbccdd"
_BLOB_V2 = "ddeeff00112233445566778899aabbccddaabbcc"

_IDENTITY = "note:project:demo/garden"
_SUBJECT_ID = "note:project:demo/garden"
_TITLE = "garden.md"

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

_CAUSE_BODY = "# Demo\n\nGenerated instruction body.\n"


def _version_row(
    ordinal: int,
    commit: str,
    blob: str,
    committer_time: int,
    class_name: str,
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "ordinal": ordinal,
        "commit": commit,
        "committer_time": committer_time,
        "class": class_name,
        "hidden": False,
        "summary": {
            "section_paths": ["Default Keymap Config"],
            "words_added": 31,
            "words_removed": 4,
            "frontmatter_phrase": "promoted reference → core",
            "created_words": None,
            "volume": 35,
        },
        "provenance": {"agent": "athena", "bead": "sase-1au.5"},
        "cause": {
            "sources": [],
            "config_paths": [],
            "renderer_paths": [],
            "regen_only": False,
        },
        "diverged": False,
        "aliased_paths": [],
        "path": "sase/memory/garden.md",
        "source_path": "sase/memory/garden.md",
        "blob_oid": blob,
    }
    row.update(extra)
    return row


def _past_timeline() -> dict[str, object]:
    return {
        "subject_id": _SUBJECT_ID,
        "state": "tracked",
        "upstream_ahead": 2,
        "upstream_branch": "origin/master",
        "versions": [
            _version_row(2, _COMMIT_V2, _BLOB_V2, _V2_TIME, "promoted"),
            _version_row(
                1,
                _COMMIT_V1,
                _BLOB_V1,
                _V1_TIME,
                "created",
                summary={
                    "section_paths": [],
                    "words_added": 0,
                    "words_removed": 0,
                    "frontmatter_phrase": None,
                    "created_words": 412,
                    "volume": 412,
                },
                provenance={"agent": None, "bead": None},
            ),
        ],
    }


def _cause_timeline() -> dict[str, object]:
    return {
        "subject_id": "instructions:project:demo/.",
        "state": "tracked",
        "managed": True,
        "versions": [
            {
                "ordinal": 2,
                "commit": _COMMIT_V2,
                "committer_time": _V2_TIME,
                "class": "rendered",
                "hidden": False,
                "summary": {
                    "section_paths": [],
                    "words_added": 12,
                    "words_removed": 2,
                    "frontmatter_phrase": None,
                    "created_words": None,
                    "volume": 14,
                },
                "provenance": {"agent": "athena", "bead": "sase-1bc.12"},
                "cause": {
                    "sources": [
                        {"subject_id": "note:project:demo/gotchas"},
                        {"subject_id": "note:project:demo/dispatch"},
                    ],
                    "config_paths": [],
                    "renderer_paths": [],
                    "regen_only": False,
                },
                "diverged": False,
                "aliased_paths": ["CLAUDE.md"],
                "path": "AGENTS.md",
                "source_path": "AGENTS.md",
                "blob_oid": _BLOB_V2,
            },
            _version_row(1, _COMMIT_V1, _BLOB_V1, _V1_TIME, "created"),
        ],
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


def _section_for_state(state: str) -> PagerSection:
    raw = RawSourceSpec(language="markdown")
    if state == "cause":
        pin = committed_pin_for_ordinal(
            "instructions:project:demo/.", 2, commit=_COMMIT_V2, blob_oid=_BLOB_V2
        )
        return PagerSection(
            identity="instructions:project:demo/.",
            title="AGENTS.md",
            kind="file",
            body=_CAUSE_BODY,
            subject_ref="instructions:project:demo/.",
            raw_source=raw,
            version_pin=pin,
        )
    if state == "past":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID, 2, commit=_COMMIT_V2, blob_oid=_BLOB_V2
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
    if state == "untracked":
        return PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body=_PAST_BODY,
            subject_ref=_SUBJECT_ID,
            raw_source=raw,
        )
    return PagerSection(
        identity=_IDENTITY,
        title=_TITLE,
        kind="file",
        body=_PAST_BODY,
        subject_ref=_SUBJECT_ID,
        raw_source=raw,
    )


def _inject_time_band_state(screen: PagerScreen, state: str) -> None:
    """Populate deterministic per-section history state for *state*."""
    screen._time_band_now_epoch = _NOW  # type: ignore[attr-defined]
    identity = screen.document.sections[0].identity
    if state == "past":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID, 2, commit=_COMMIT_V2, blob_oid=_BLOB_V2
        )
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="live",
            visible_ordinals=(1, 2),
            current_pin=pin,
        )
        timeline = _past_timeline()
    elif state == "now":
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="dirty-now",
            visible_ordinals=(1, 2),
            current_pin=live_pin_for_subject(_SUBJECT_ID),
        )
        timeline = _past_timeline()
    elif state == "cause":
        pin = committed_pin_for_ordinal(
            "instructions:project:demo/.", 2, commit=_COMMIT_V2, blob_oid=_BLOB_V2
        )
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id="instructions:project:demo/.",
            scope_key="project",
            status="live",
            visible_ordinals=(1, 2),
            current_pin=pin,
        )
        timeline = _cause_timeline()
    else:
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="live",
            visible_ordinals=(),
            current_pin=live_pin_for_subject(_SUBJECT_ID),
        )
        timeline = {"subject_id": _SUBJECT_ID, "state": "untracked", "versions": []}
    versions = list(timeline.pop("versions", []))
    time_state.timeline = tuple(versions)  # type: ignore[assignment]
    time_state.timeline_meta = dict(timeline)
    screen._history_states[identity] = time_state
    screen._history_supported[identity] = True
    screen._body_width = None
    screen._ensure_body()
    screen._update_subject()
    screen._update_footer()
    screen._update_trail()


def _other_document() -> PagerDocument:
    section = PagerSection(
        identity="note:project:demo/other",
        title="other.md",
        kind="file",
        body="# Other\n",
        subject_ref="note:project:demo/other",
    )
    return PagerDocument(sections=(section,), title="other.md", origin=PagerOrigin.FILE)


@pytest.mark.parametrize("size", _SIZES)
@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("state", ["past", "now", "cause", "untracked"])
async def test_time_band_png_snapshot(
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
            title=section.title,
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
            _inject_time_band_state(screen, state)
            await pilot.pause()
            pager_png_visual.assert_page_png(
                _SvgExport(app),
                f"timeband_{state}_{theme_label}_{size[0]}x{size[1]}",
                title=f"SasePager: time band {state} ({theme_label})",
            )
    finally:
        clear_history_provider_factories()


@pytest.mark.parametrize("light", [False, True])
async def test_time_band_narrow_png_snapshot_with_trail(
    pager_png_visual: AcePngSnapshotFixture,
    light: bool,
) -> None:
    """The degraded one-row past band with the trail band visible."""
    clear_history_provider_factories()
    try:
        section = _section_for_state("past")
        document = PagerDocument(
            sections=(section,),
            title=section.title,
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
            await wait_for(
                pilot,
                lambda: (
                    _syntax_key_for_section(section) in screen._syntax_prepared
                    and not screen._syntax_pass_running
                ),
            )
            screen._apply_resolution(
                "other",
                LinkTarget(kind=LinkTargetKind.DOCUMENT, document=_other_document()),
                intent="follow",
            )
            await pilot.pause()
            await pilot.press("backspace")
            await pilot.pause()
            _inject_time_band_state(screen, "past")
            await pilot.pause()
            pager_png_visual.assert_page_png(
                _SvgExport(app),
                f"timeband_narrow_trail_{theme_label}_60x30",
                title=f"SasePager: time band narrow trail ({theme_label})",
            )
    finally:
        clear_history_provider_factories()
