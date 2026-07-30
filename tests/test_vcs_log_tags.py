"""Tests for ``sase vcs log`` SASE footer parsing helpers."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_log._tag_style import full_tag_lines, inline_tag_text
from sase.vcs_log.tags import commit_tag_view


def _commit(body: str, subject: str = "feat: work") -> VcsCommitWire:
    return VcsCommitWire(
        full_id="a1b2c3d4",
        short_id="a1b2c3d",
        author_name="bryan",
        author_email="b@x",
        timestamp=300,
        subject=subject,
        body=body,
    )


def test_parses_trailing_sase_tag_block() -> None:
    view = commit_tag_view(
        _commit("body text\n\nSASE_TYPE=sdd\nSASE_PLAN=sdd/plans/foo.md")
    )

    assert view.tags == (
        ("TYPE", "sdd"),
        ("PLAN", "sdd/plans/foo.md"),
    )
    assert view.body == "body text"


def test_strips_only_sase_prefix_from_keys() -> None:
    view = commit_tag_view(_commit("SASE_AGENT=worker-1\nSASE_MACHINE=host-a"))

    assert view.tags == (("AGENT", "worker-1"), ("MACHINE", "host-a"))
    assert view.body == ""


def test_ignores_non_trailing_sase_text() -> None:
    body = "SASE_TYPE=sdd\n\nregular body after"

    view = commit_tag_view(_commit(body))

    assert view.tags == ()
    assert view.body == body


def test_ignores_legacy_unprefixed_footer_keys() -> None:
    body = "body text\n\nTYPE=sdd\nAGENT=worker-1"

    view = commit_tag_view(_commit(body))

    assert view.tags == ()
    assert view.body == body


def test_mixed_footer_displays_only_sase_tags_and_strips_block() -> None:
    view = commit_tag_view(_commit("body text\n\nTYPE=legacy\nSASE_TYPE=sdd"))

    assert view.tags == (("TYPE", "sdd"),)
    assert view.body == "body text"


def test_duplicate_sase_keys_keep_later_value() -> None:
    view = commit_tag_view(
        _commit("body text\n\nSASE_TYPE=old\nSASE_PLAN=plan.md\nSASE_TYPE=new")
    )

    assert view.tags == (("TYPE", "new"), ("PLAN", "plan.md"))
    assert view.body == "body text"


def test_linked_plan_displays_label_and_hides_definition_from_body() -> None:
    view = commit_tag_view(
        _commit(
            "body text\n\nSASE_PLAN=[202607/foo.md][1]\n\n"
            "[1]: https://github.com/acme/plans/blob/main/202607/foo.md"
        )
    )

    assert view.tags == (("PLAN", "202607/foo.md"),)
    assert view.body == "body text"


def test_linked_lane_agent_tag_displays_the_lane_label() -> None:
    """A family member's commit shows its lane, linked to the family page."""
    view = commit_tag_view(
        _commit(
            "body text\n\nSASE_AGENT=[bbugyi200.athena.pc][1]\n\n"
            "[1]: https://github.com/sase-org/sase--agents/blob/main/"
            "families/bbugyi200.athena.pc.md"
        )
    )

    assert view.tags == (("AGENT", "bbugyi200.athena.pc"),)
    assert view.body == "body text"

    text = inline_tag_text(view.tags)

    assert text.plain == "@bbugyi200.athena.pc"
    assert _styles_covering(text, "bbugyi200.athena.pc") == ["#FFD700"]


@pytest.mark.parametrize(
    ("type_value", "expected_color"),
    [
        ("sdd", "#87D7FF"),
        ("init", "#5FD75F"),
        ("beads", "#5FD7AF"),
        ("bead_work", "#00D7AF"),
        ("memory", "#AF87FF"),
        ("skills", "#D787AF"),
        ("xprompt", "#FFAF5F"),
        ("config", "#D7AF5F"),
    ],
)
def test_tag_style_type_colors(type_value: str, expected_color: str) -> None:
    text = inline_tag_text((("TYPE", type_value),))

    assert text.plain == f"◆ {type_value}"
    assert _styles_covering(text, "◆") == [expected_color]
    assert _styles_covering(text, type_value) == [expected_color]


def test_tag_style_unknown_type_falls_back_to_neutral_mauve() -> None:
    text = inline_tag_text((("TYPE", "experimental"),))

    assert text.plain == "◆ experimental"
    assert _styles_covering(text, "◆") == ["#AF87D7"]
    assert _styles_covering(text, "experimental") == ["#AF87D7"]


def test_tag_style_ordering_and_known_chip_styles() -> None:
    text = inline_tag_text(
        (
            ("PLAN", "sdd/plans/foo.md"),
            ("EXTRA", "value"),
            ("BUG", "412"),
            ("MACHINE", "athena"),
            ("AGENT", "worker-1"),
            ("TYPE", "sdd"),
        )
    )

    assert (
        text.plain
        == "◆ sdd · @worker-1 · machine athena · plan sdd/plans/foo.md · #412 · extra value"
    )
    assert _styles_covering(text, "@") == ["#FFD700"]
    assert _styles_covering(text, "worker-1") == ["#FFD700"]
    assert _styles_covering(text, "#") == ["#FF8787"]
    assert _styles_covering(text, "412") == ["#FF8787"]
    assert _styles_covering(text, "machine") == ["#8A8A8A"]
    assert _styles_covering(text, "athena") == ["#8A8A8A"]
    assert _styles_covering(text, "plan") == ["dim"]
    assert _styles_covering(text, "sdd/plans/") == ["dim"]
    assert _styles_covering(text, "foo.md") == ["#5FAFFF"]
    assert _styles_covering(text, "extra") == ["dim"]
    assert _styles_covering(text, "value") == []


def test_full_tag_lines_align_keys_and_reuse_chip_styles() -> None:
    lines = full_tag_lines(
        (
            ("BUG", "412"),
            ("TYPE", "sdd"),
            ("PLAN", "sdd/plans/foo.md"),
            ("AGENT", "worker-1"),
        )
    )

    assert [line.plain for line in lines] == [
        "     ◆ type   sdd",
        "     @ agent  worker-1",
        "       plan   sdd/plans/foo.md",
        "     # bug    412",
    ]
    assert _styles_covering(lines[0], "◆") == ["#87D7FF"]
    assert _styles_covering(lines[1], "worker-1") == ["#FFD700"]
    assert _styles_covering(lines[2], "foo.md") == ["#5FAFFF"]
    assert _styles_covering(lines[3], "412") == ["#FF8787"]


def _styles_covering(text: Text, fragment: str) -> list[str]:
    start = text.plain.index(fragment)
    end = start + len(fragment)
    return [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
