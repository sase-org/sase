"""Tribe header and fold-level rendering tests."""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from sase.ace.tui.models.fold_state import FoldLevel
import sase.ace.tui.models.tribe_display as tribe_display
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._helpers import PROMPT_PANEL_LINE_CELL_LIMIT
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from tests.ace.tui.widgets._agent_display_tribe_helpers import (
    make_tribe_snapshot,
)


def test_tribe_header_colors_only_the_structured_name_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {
            "ace": {
                "tribes": {
                    "epic": {"icon": "▲", "color": "#123456"},
                }
            }
        },
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-header-color",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(make_tribe_snapshot())
    name_start = detail.plain.index("▲ @epic")

    assert any(
        span.start <= name_start < span.end and str(span.style) == "bold #123456"
        for span in detail.spans
    )
    assert any(
        span.start <= detail.plain.index("TRIBE") < span.end
        and str(span.style) == "bold #FFD75F underline"
        for span in detail.spans
    )


def test_tribe_description_renders_below_the_header_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"description": "Epic phase workers."}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-line",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(make_tribe_snapshot())
    plain = detail.plain
    fold_index = plain.index("Fold: ")
    divider_index = plain.index("─" * 50)
    description_start = plain.index("Epic phase workers.")

    assert fold_index < description_start < divider_index
    assert plain[description_start - 2 : description_start] == "\n\n"
    assert "Description: " not in plain
    assert any(
        span.start <= description_start < span.end
        and str(span.style) == "italic #C6C6C6"
        for span in detail.spans
    )


def test_tribe_long_description_wraps_with_a_hanging_indent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"description": "x" * 160}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-wrap",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(make_tribe_snapshot())
    lines = detail.plain.splitlines()

    assert all(cell_len(line) <= PROMPT_PANEL_LINE_CELL_LIMIT for line in lines)

    fold_line_index = next(
        index for index, line in enumerate(lines) if line.startswith("Fold: ")
    )
    description_start = next(
        index
        for index in range(fold_line_index + 1, len(lines))
        if lines[index].startswith("x")
    )
    assert lines[description_start - 1] == ""
    wrapped_description_lines = []
    for line in lines[description_start:]:
        if not line.startswith("x"):
            break
        wrapped_description_lines.append(line)

    assert len(wrapped_description_lines) > 1
    for line in wrapped_description_lines:
        assert not line.startswith(" ")


def test_tribe_omits_the_description_row_when_none_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"icon": "▲"}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-missing",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(make_tribe_snapshot())
    plain = detail.plain
    lines = plain.splitlines()
    fold_line_index = next(
        index for index, line in enumerate(lines) if line.startswith("Fold: ")
    )

    assert "not set" not in plain
    assert "ace.tribes." not in plain
    assert lines[fold_line_index + 1] == ""
    assert lines[fold_line_index + 2].startswith("─" * 50)

    cheap = build_tribe_detail_text(make_tribe_snapshot(), cheap=True).plain
    assert cheap.endswith("Fold: 1/4\n")
    assert not cheap.endswith("Fold: 1/4\n\n")
    assert "not set" not in cheap
    assert "ace.tribes." not in cheap


def test_tribe_ad_hoc_panel_renders_no_description_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-unconfigured",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(make_tribe_snapshot())

    assert "not set" not in detail.plain
    assert "ace.tribes." not in detail.plain


def test_tribe_description_renders_in_cheap_mode() -> None:
    detail = build_tribe_detail_text(make_tribe_snapshot(), cheap=True).plain

    assert "Description: " not in detail
    assert (
        "Epic phase-worker clans from sase bead work, one member per phase of an "
        "approved plan."
    ) in " ".join(detail.split())


def test_tribe_description_with_markup_characters_renders_literally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"description": "Has [bold] brackets."}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-markup",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(make_tribe_snapshot())

    assert "Has [bold] brackets." in detail.plain


def test_tribe_levels_have_distinct_glance_triage_inspect_and_forensics_jobs() -> None:
    snapshot = make_tribe_snapshot()
    published: list[MemberJumpMap] = []

    pulse = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    ).plain
    roster = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=published.append,
    ).plain
    members = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    ).plain
    forensics = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.EXHAUSTIVE,
    ).plain

    assert pulse.startswith(
        "TRIBE\nName: ▲ @epic\n"
        "Status: FAILED [R1 F1]\n"
        "Composition: 1 family · 2 lanes · 1 nested\n"
        "Runtime: 1h\nFold: 1/4\n"
        "\n"
        "Epic phase-worker clans from sase bead work, one member per phase of an "
        "approved\n"
        "plan.\n"
    )
    assert "▸ NEEDS ATTENTION · 1\n• failed · FAILED · Build failed" in pulse
    assert "▸ ❖ TRIBE MEMBERS · 2\n" in pulse
    assert " 0  [✓] build · family" in pulse
    assert " 1  failed · agent" in pulse
    assert published[0].targets

    assert "Fold: 2/4\n" in roster
    assert " 0  [✓] build · family" in roster
    assert " 1  failed · agent" in roster
    assert "--code" not in roster
    assert "• failed · Build failed" in roster
    assert published[1].container_identity == ("panel", "epic")
    assert [target.member_identity for target in published[1].targets] == [
        snapshot.units[0].identity,
        snapshot.units[1].identity,
    ]

    assert "Fold: 3/4\n" in members
    assert "└─ [✓] --code" in members
    assert "writing tests" in members
    assert "ws 8" not in members
    assert "Second error detail" in members
    assert "ValueError: broken" not in members
    assert "    findings:\n      - file: src/a.py\n        severity: high\n" in members
    assert "    passed: true\n" in members
    assert "    ratio: 2.5\n" in members
    assert "    summary: summary line\n" in members
    assert "release detail" in members

    assert "Fold: 4/4\n" in forensics
    assert "ws 8" in forensics
    assert "ValueError: broken" in forensics
    assert pulse != roster != members != forensics


def test_tribe_structured_variable_lines_have_per_kind_styles() -> None:
    detail = build_tribe_detail_text(
        make_tribe_snapshot(),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    def style_at(needle: str) -> str | None:
        position = detail.plain.index(needle)
        for span in reversed(detail.spans):
            if span.start <= position < span.end:
                return str(span.style)
        return str(detail.style) if detail.style else None

    assert style_at("true") == "italic #AFAFAF"
    assert style_at("2.5") == "#FFAF5F"
    assert style_at("summary line") == "#5FD75F"
