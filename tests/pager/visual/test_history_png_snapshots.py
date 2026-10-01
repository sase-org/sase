"""Deterministic PNG goldens for memory-history pager read and diff states.

Covers the sase-1dr.6 read view in three honest states — past read view,
dirty now, and deletion tombstone — plus the sase-1dr.8 word-diff view in
its past and dirty forms, plus the sase-1dr.10 changes feed in its
collapsed and regen-expanded forms, at 120x40 and 60x30 in dark and light
themes. Sections use fixed bodies, fixed commit/blob OIDs, canned
comparisons, and fixed feed epochs (the visual lane pins ``TZ=UTC``) so
screenshots never depend on checkout history or today's time. The real
provider registry is cleared so no git/file I/O can leak in; history
chrome/gutter state is injected deterministically after mount.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection, RawSourceSpec
from sase.pager._screen_syntax import _syntax_key_for_section  # noqa: PLC2701
from sase.pager.history.diff import build_diff_body
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

#: Long past-read body for the `past-frame` golden: the time band scrolls
#: out of view on small terminals, so the past-accent gutter rail is the
#: cue. The head matches `_PAST_BODY` so the fixture change marks stay put.
_FRAME_BODY = _PAST_BODY + "".join(
    f"Row {number}: turn the compost and check the cold frame.\n"
    for number in range(7, 130)
)

#: The tombstone body is exactly the last content: the deletion notice
#: moved from the body into band tombstone chrome (band phase).
_TOMBSTONE_BODY = (
    "# Garden note\n\nThis note was removed when the beds were replanted.\n"
)

_DIFF_PAST_BODY = (
    "# Garden note\n"
    "\n"
    "Soil is ready for spring planting.\n"
    "Added: compost row along the north bed.\n"
    "Changed: water schedule is now thrice weekly.\n"
    "Keep the stone path clear of weeds.\n"
    "\n"
    "## Next steps\n"
    "\n"
    "- Sow carrots in the east row.\n"
    "- Label the seed trays.\n"
)

_DIFF_OLD_LINE = "Changed: water schedule is now twice weekly."
_DIFF_NEW_LINE = "Changed: water schedule is now thrice weekly."
_DIFF_PREFIX = "Changed: water schedule is now "
_DIFF_SUFFIX = " weekly."


def _diff_past_comparison() -> dict[str, object]:
    start = len(_DIFF_PREFIX)
    return {
        "frontmatter": {"type_change": "promoted", "entries": []},
        "line_marks": [5],
        "word_ops": [
            {
                "target_line": 5,
                "ops": [
                    {"kind": "equal", "text": _DIFF_PREFIX, "start": 0, "end": start},
                    {"kind": "delete", "text": "twice", "start": start, "end": start},
                    {
                        "kind": "insert",
                        "text": "thrice",
                        "start": start,
                        "end": start + len("thrice"),
                    },
                    {
                        "kind": "equal",
                        "text": _DIFF_SUFFIX,
                        "start": start + len("thrice"),
                        "end": len(_DIFF_NEW_LINE),
                    },
                ],
            }
        ],
        "hunks": [
            {"target_start": 5, "target_end": 6, "section_path": ["Garden note"]}
        ],
        "removal_anchors": [{"after_target_line": 10, "removed_count": 1}],
        "stats": {"words_added": 1, "words_removed": 1},
        "unified_diff": (f"@@ -5 +5 @@\n-{_DIFF_OLD_LINE}\n+{_DIFF_NEW_LINE}\n"),
    }


_DIRTY_DIFF_PREFIX = "Uncommitted: "
_DIRTY_DIFF_ADDED = "drafted a new herb spiral sketch."


def _diff_dirty_comparison() -> dict[str, object]:
    start = len(_DIRTY_DIFF_PREFIX)
    return {
        "frontmatter": {"entries": [], "type_change": None},
        "line_marks": [4],
        "word_ops": [
            {
                "target_line": 4,
                "ops": [
                    {
                        "kind": "equal",
                        "text": _DIRTY_DIFF_PREFIX,
                        "start": 0,
                        "end": start,
                    },
                    {
                        "kind": "insert",
                        "text": _DIRTY_DIFF_ADDED,
                        "start": start,
                        "end": start + len(_DIRTY_DIFF_ADDED),
                    },
                ],
            }
        ],
        "hunks": [{"target_start": 4, "target_end": 5}],
        "removal_anchors": [],
        "stats": {"words_added": 6, "words_removed": 0},
        "unified_diff": (f"@@ -3,0 +4 @@\n+{_DIRTY_DIFF_PREFIX}{_DIRTY_DIFF_ADDED}\n"),
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
    if state in ("past", "past-frame"):
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
            body=_FRAME_BODY if state == "past-frame" else _PAST_BODY,
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
    if state == "past-diff":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            2,
            commit=_COMMIT_V2,
            blob_oid=_BLOB_V2,
            view="diff",
            compare_base=1,
        )
        rendered = build_diff_body(_diff_past_comparison(), _DIFF_PAST_BODY)
        return PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body=rendered.text,
            subject_ref=_SUBJECT_ID,
            raw_source=raw,
            targets=rendered.fold_targets,
            version_pin=pin,
        )
    if state == "dirty-diff":
        pin = replace(live_pin_for_subject(_SUBJECT_ID), view="diff", compare_base=3)
        rendered = build_diff_body(_diff_dirty_comparison(), _DIRTY_BODY)
        return PagerSection(
            identity=_IDENTITY,
            title=_TITLE,
            kind="file",
            body=rendered.text,
            subject_ref=_SUBJECT_ID,
            raw_source=raw,
            targets=rendered.fold_targets,
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


#: Fixed committer time for fixture rows (2020-01-01 UTC): the subject
#: chip's relative age reads ``6y`` and stays put until 2027, long after
#: the badge phase replaces the interim chip with the state pill.
_FIXTURE_TIME = 1577836800


def _fixture_timeline_rows(
    deleted_newest: bool = False,
) -> tuple[dict[str, object], ...]:
    """Return fixed committed rows for the injected history state."""
    return (
        {
            "ordinal": 1,
            "commit": _COMMIT_V1,
            "committer_time": _FIXTURE_TIME,
            "class": "created",
            "summary": {"section_paths": ["Garden note"], "created_words": 90},
            "provenance": {"subject": "plant the garden"},
        },
        {
            "ordinal": 2,
            "commit": _COMMIT_V2,
            "blob_oid": _BLOB_V2,
            "committer_time": _FIXTURE_TIME,
            "class": "authored",
            "summary": {
                "section_paths": ["Garden note"],
                "words_added": 12,
                "words_removed": 4,
                "volume": 16,
            },
            "provenance": {"subject": "tend the garden"},
        },
        {
            "ordinal": 3,
            "commit": _COMMIT_V3,
            "blob_oid": _BLOB_V3,
            "committer_time": _FIXTURE_TIME,
            "class": "deleted" if deleted_newest else "authored",
            "summary": {
                "section_paths": ["Garden note"],
                "words_added": 3,
                "words_removed": 9,
                "volume": 12,
            },
            "provenance": {"subject": "replant the beds"},
        },
    )


def _inject_history_state(screen: PagerScreen, state: str) -> None:
    """Populate deterministic per-section history state for *state*."""
    if state in ("past", "past-frame"):
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
    elif state == "past-diff":
        pin = committed_pin_for_ordinal(
            _SUBJECT_ID,
            2,
            commit=_COMMIT_V2,
            blob_oid=_BLOB_V2,
            view="diff",
            compare_base=1,
        )
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="live",
            visible_ordinals=(1, 2, 3),
            current_pin=pin,
        )
        time_state.comparison_cache[(1, 2)] = _diff_past_comparison()
    elif state == "dirty-diff":
        pin = replace(live_pin_for_subject(_SUBJECT_ID), view="diff", compare_base=3)
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="dirty-now",
            visible_ordinals=(1, 2, 3),
            current_pin=pin,
        )
        time_state.comparison_cache[(3, 0)] = _diff_dirty_comparison()
    else:
        time_state = SectionTimeState(
            provider_key="fixture",
            subject_id=_SUBJECT_ID,
            scope_key="project",
            status="dirty-now",
            visible_ordinals=(1, 2, 3),
            current_pin=live_pin_for_subject(_SUBJECT_ID),
        )
    time_state.timeline = _fixture_timeline_rows(  # type: ignore[assignment]
        deleted_newest=(state == "tombstone")
    )
    time_state.timeline_meta = {}
    screen._history_states[_IDENTITY] = time_state
    screen._history_supported[_IDENTITY] = True
    screen._body_width = None
    screen._ensure_body()
    screen._update_subject()
    screen._update_footer()


_FEED_EPOCH_DAY_ONE = 1790486400
_FEED_EPOCH_DAY_TWO = 1790400000


def _feed_fixture() -> dict[str, object]:
    """Return a fixed two-day feed with home and regen-only changesets."""
    return {
        "changesets": [
            {
                "scope_key": "project:sase",
                "commit": "dddddddddddddddddddddddddddddddddddddddd",
                "committer_time": _FEED_EPOCH_DAY_ONE,
                "provenance": {
                    "subject": "feat(tabs): inherit agent tab across launches",
                    "bead": "sase-1bc.5",
                    "agent": "athena.sase-1bc.5",
                },
                "boilerplate": False,
                "regen_only": False,
                "authored": [
                    {
                        "subject_id": "note:project:sase/dispatch",
                        "ordinal": 4,
                        "class": "authored",
                        "summary": {
                            "section_paths": ["Remote dispatch"],
                            "words_added": 44,
                            "words_removed": 10,
                        },
                        "path": "sase/memory/dispatch.md",
                    }
                ],
                "consequences": [
                    {
                        "subject_id": "instructions:project:sase/.",
                        "ordinal": 12,
                        "class": "rendered",
                        "summary": {},
                        "path": "AGENTS.md",
                    }
                ],
            },
            {
                "scope_key": "home",
                "commit": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "committer_time": _FEED_EPOCH_DAY_ONE + 600,
                "provenance": {
                    "subject": "feat(home): tune prompt hosts",
                    "bead": "",
                    "agent": "",
                },
                "boilerplate": False,
                "regen_only": False,
                "authored": [],
                "consequences": [],
            },
            {
                "scope_key": "project:sase",
                "commit": "ffffffffffffffffffffffffffffffffffffffff",
                "committer_time": _FEED_EPOCH_DAY_TWO,
                "provenance": {
                    "subject": "chore: regenerate managed files",
                    "bead": "",
                    "agent": "",
                },
                "boilerplate": False,
                "regen_only": True,
                "authored": [],
                "consequences": [
                    {
                        "subject_id": "instructions:project:sase/.",
                        "ordinal": 11,
                        "class": "regen_only",
                        "summary": {},
                        "path": "AGENTS.md",
                    }
                ],
            },
        ],
        "hidden_changeset_count": 0,
    }


def _document_for_state(state: str) -> PagerDocument:
    """Return the golden document for *state* (feed states use the builder)."""
    if state == "feed":
        from sase.memory.history.feed_document import build_feed_document

        return build_feed_document(_feed_fixture(), "project:sase + home").document
    if state == "feed-expanded":
        from sase.memory.history.feed_document import build_feed_document

        return build_feed_document(
            _feed_fixture(), "project:sase + home", expanded_regen="all"
        ).document
    section = _section_for_state(state)
    return PagerDocument(
        sections=(section,),
        title=_TITLE,
        origin=PagerOrigin.FILE,
    )


@pytest.mark.parametrize("size", _SIZES)
@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize(
    "state",
    [
        "past",
        "past-frame",
        "dirty",
        "tombstone",
        "past-diff",
        "dirty-diff",
        "feed",
        "feed-expanded",
    ],
)
async def test_history_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    size: tuple[int, int],
    light: bool,
    state: str,
) -> None:
    clear_history_provider_factories()
    try:
        document = _document_for_state(state)
        theme_label = "light" if light else "dark"
        app = _SnapshotPager(
            document,
            theme_name="textual-light" if light else None,
        )
        async with app.run_test(size=size) as pilot:
            screen = app.screen
            assert isinstance(screen, PagerScreen)
            if state.endswith("-diff") or state.startswith("feed"):
                # Diff-view sections carry their own word-diff styling and
                # feed sections carry fixed builder text: neither needs
                # syntax preparation before capture.
                await pilot.pause()
            else:
                section = document.sections[0]
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
