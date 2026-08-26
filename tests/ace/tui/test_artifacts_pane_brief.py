"""Renderer tests for the Artifacts pane description brief (no app)."""

from __future__ import annotations

import pytest

from sase.ace.tui.artifacts_description import ARTIFACTS_BRIEF_MAX_LINES
from sase.ace.tui.widgets.artifacts.shell import build_pane_brief


_ACCENT = "#D787FF"
_ICON = "◈"
_SUMMARY = "The work SASE tracks: plan and epic beads, and standalone task beads."
_BODY = (
    "Rows come from the current project's bead store, grouped by hierarchy. "
    "Selecting one shows its status, size, dependencies, and notes."
)


@pytest.mark.parametrize("width", [120, 80])
@pytest.mark.parametrize("mode", ["off", "summary", "full"])
def test_build_pane_brief_smoke_across_modes_and_widths(width: int, mode: str) -> None:
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=_SUMMARY,
        body=_BODY,
        mode=mode,  # type: ignore[arg-type]
        width=width,
        disclosure_key="D",
    )
    if mode == "off":
        assert text.plain == ""
        return
    assert text.plain != ""
    lines = text.plain.split("\n")
    assert len(lines) <= ARTIFACTS_BRIEF_MAX_LINES
    assert lines[0].startswith("▌ ")


def test_summary_mode_ellipsizes_rather_than_wraps() -> None:
    long_summary = "word " * 60
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=long_summary,
        body=_BODY,
        mode="summary",
        width=80,
        disclosure_key=None,
    )
    lines = text.plain.split("\n")
    assert len(lines) == 1
    assert lines[0].endswith("…")


def test_full_mode_wraps_summary_instead_of_ellipsizing() -> None:
    long_summary = "word " * 60
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=long_summary,
        body="",
        mode="full",
        width=80,
        disclosure_key=None,
    )
    lines = text.plain.split("\n")
    assert len(lines) > 1
    assert not lines[0].endswith("…")


def test_disclosure_hint_shown_when_room_and_target_exist() -> None:
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary="Short summary.",
        body=_BODY,
        mode="summary",
        width=80,
        disclosure_key="D",
    )
    assert "▸ D" in text.plain


def test_disclosure_hint_dropped_without_room() -> None:
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary="Short summary.",
        body=_BODY,
        mode="summary",
        width=8,
        disclosure_key="D",
    )
    assert "▸ D" not in text.plain
    assert "▾ D" not in text.plain


def test_disclosure_hint_dropped_with_nothing_to_disclose() -> None:
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary="Short summary.",
        body="",
        mode="summary",
        width=80,
        disclosure_key="D",
        unconfigured_hint=None,
    )
    assert "▸ D" not in text.plain


def test_disclosure_hint_uses_resolved_key_display_name() -> None:
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary="Short summary.",
        body=_BODY,
        mode="full",
        width=80,
        disclosure_key="ctrl+d",
    )
    assert "▾ ctrl+d" in text.plain


def test_line_cap_emits_overflow_row_and_never_exceeds_max_lines() -> None:
    huge_body = "\n\n".join(
        f"Paragraph number {i} with several words in it." for i in range(20)
    )
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=_SUMMARY,
        body=huge_body,
        mode="full",
        width=40,
        disclosure_key="D",
        max_lines=6,
    )
    lines = text.plain.split("\n")
    assert len(lines) == 6
    assert "… +" in lines[-1]
    assert lines[-1].endswith(" more")


def test_unconfigured_hint_only_rendered_in_full_mode() -> None:
    hint = "Describe this pane with ref.pane.description in its sidecar ref config."
    summary_mode = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=_SUMMARY,
        body="",
        mode="summary",
        width=80,
        disclosure_key="D",
        unconfigured_hint=hint,
    )
    assert hint not in summary_mode.plain

    full_mode = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=_SUMMARY,
        body="",
        mode="full",
        width=80,
        disclosure_key="D",
        unconfigured_hint=hint,
    )
    assert hint in full_mode.plain


def test_accent_appears_only_in_gutter_and_disclosure_hint() -> None:
    text = build_pane_brief(
        icon=_ICON,
        accent=_ACCENT,
        summary=_SUMMARY,
        body=_BODY,
        mode="full",
        width=80,
        disclosure_key="D",
    )
    for span in text.spans:
        style = str(span.style)
        if _ACCENT not in style:
            continue
        fragment = text.plain[span.start : span.end]
        assert fragment == "▌ " or fragment.strip().startswith(("▸", "▾"))
