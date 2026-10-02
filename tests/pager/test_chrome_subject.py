"""Subject-line, section-rule, and section-chrome tests for the pager."""

from __future__ import annotations

from rich.text import Span

from sase.pager._chrome import section_rule, subject_line
from sase.pager._chrome_sections import section_accent, section_icon
from sase.pager._chrome_subject import _format_char_count
from sase.pager._trail_chrome_model import MUTED_STYLE
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

from ._chrome_helpers import CONSOLE, file_section


def _bead_section(title: str = "sase-uk.3: The reading surface") -> PagerSection:
    return PagerSection(
        identity="bead:sase-uk.3",
        title=title,
        kind="bead",
        body="some detail",
        subject_ref="bead:sase-uk.3",
    )


def _agent_section(title: str = "IDENTITY") -> PagerSection:
    return PagerSection(
        identity="agent-identity",
        title=title,
        kind="agent",
        body="Name: worker\n",
    )


def test_section_icon_and_accent_use_the_artifacts_tables() -> None:
    assert section_icon("bead") == "◈"
    assert section_icon("file") == "▤"
    assert section_icon("agent") == "⬡"
    assert section_accent("bead") == "#D787FF"
    assert section_accent("file") == "#FFAF5F"
    assert section_accent("agent") == "#0062FF"


def test_section_icon_and_accent_fall_back_for_unknown_kinds() -> None:
    assert section_icon("diff") == "◆"
    assert section_accent("diff") == "#AFAFAF"


def test_format_char_count_scales_with_magnitude() -> None:
    assert _format_char_count(88) == "88c"
    assert _format_char_count(1_234) == "1.2Kc"
    assert _format_char_count(2_500_000) == "2.5Mc"


def test_subject_line_omits_position_for_a_single_section_document() -> None:
    section = _bead_section()
    document = PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=41,
        char_count=88,
        width=80,
    )

    assert "◈" in line.plain
    assert document.title in line.plain
    assert "1/1" not in line.plain
    assert "41%" in line.plain
    assert "⌘ 88c" in line.plain


def test_subject_line_shows_position_and_current_section_title_when_multi() -> None:
    sections = (file_section("a.py"), file_section("b.py"), file_section("c.py"))
    document = PagerDocument(
        sections=sections, title="3 files", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        sections[1],
        section_index=2,
        section_total=3,
        scroll_percent=12,
        char_count=42,
        width=80,
    )

    assert "▤" in line.plain
    assert "3 files" in line.plain
    assert "b.py" in line.plain
    assert "2/3" in line.plain
    assert "12%" in line.plain


def test_subject_line_pads_to_the_requested_width_when_it_fits() -> None:
    section = _bead_section()
    document = PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=0,
        width=80,
    )

    assert len(line.plain) == 80


def test_subject_line_shows_the_syntax_hint_when_it_fits() -> None:
    section = file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        syntax_hint="py",
    )

    assert "· py" in line.plain


def test_subject_line_omits_the_syntax_hint_when_absent() -> None:
    section = file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        syntax_hint=None,
    )

    assert "· py" not in line.plain


def test_subject_line_drops_the_syntax_hint_before_the_subject_at_narrow_width() -> (
    None
):
    section = file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    without_hint = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=20,
        syntax_hint=None,
    )
    with_hint = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=20,
        syntax_hint="py",
    )

    assert "· py" not in with_hint.plain
    assert with_hint.plain == without_hint.plain


def test_subject_line_uses_the_agent_glyph_and_accent() -> None:
    section = _agent_section()
    document = PagerDocument(
        sections=(section,), title="worker", origin=PagerOrigin.AGENT
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=13,
        width=80,
    )

    assert "⬡" in line.plain
    color = line.get_style_at_offset(CONSOLE, 0).color
    assert color is not None
    assert color.get_truecolor().hex == "#0062ff"


def test_subject_line_mutes_an_intact_ws_root_token() -> None:
    section = file_section("~ws/acme_3/a.py")
    document = PagerDocument(
        sections=(section,), title="~ws/acme_3/a.py", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
    )

    start = line.plain.index("~ws/acme_3/a.py")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in line.spans


def test_subject_line_mutes_the_current_sections_ws_token_when_multi() -> None:
    first = file_section("a.py")
    second = file_section("~ws/acme_3/b.py")
    document = PagerDocument(
        sections=(first, second), title="2 files", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        second,
        section_index=2,
        section_total=2,
        scroll_percent=0,
        char_count=10,
        width=80,
    )

    start = line.plain.index("~ws/acme_3/b.py")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in line.spans


def test_section_rule_mutes_an_intact_ws_root_token() -> None:
    section = file_section("~ws/acme_3/b.py")

    line = section_rule(section, index=2, total=2, width=80)

    start = line.plain.index("~ws/acme_3/b.py")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in line.spans


def test_section_rule_renders_the_agent_kind() -> None:
    section = _agent_section("MODEL")

    line = section_rule(section, index=2, total=7, width=80)

    assert line.plain.startswith("━━ 2/7 ━ ⬡ MODEL")
    assert len(line.plain) == 80


def test_section_rule_shape_matches_the_design_doc() -> None:
    section = file_section("artifact_links.py")

    line = section_rule(section, index=2, total=3, width=80)

    assert line.plain.startswith("━━ 2/3 ━ ▤ artifact_links.py")
    assert line.plain.endswith("━")
    assert len(line.plain) == 80
