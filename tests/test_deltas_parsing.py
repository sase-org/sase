"""Tests for DELTAS field parsing, formatting, and round-trip."""

from sase.ace.changespec import DeltaEntry, DeltaLineStats
from sase.ace.changespec.deltas_format import format_deltas_field
from sase.ace.changespec.parser import _parse_changespec_from_lines


def _base_lines() -> list[str]:
    return [
        "## ChangeSpec\n",
        "NAME: test_cl\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Ready\n",
    ]


def test_parse_deltas_all_three_change_types() -> None:
    """Parse a DELTAS section with added, modified, and deleted entries."""
    lines = _base_lines() + [
        "DELTAS:\n",
        "  + src/sase/ace/changespec/deltas.py\n",
        "  + tests/test_deltas_parsing.py\n",
        "  ~ src/sase/ace/changespec/models.py\n",
        "  ~ src/sase/ace/changespec/parser.py\n",
        "  - src/sase/legacy/old_deltas.py\n",
        "\n",
    ]
    changespec, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.deltas is not None
    assert len(changespec.deltas) == 5
    assert changespec.deltas[0] == DeltaEntry(
        path="src/sase/ace/changespec/deltas.py", change_type="A"
    )
    assert changespec.deltas[1] == DeltaEntry(
        path="tests/test_deltas_parsing.py", change_type="A"
    )
    assert changespec.deltas[2].change_type == "M"
    assert changespec.deltas[3].change_type == "M"
    assert changespec.deltas[4] == DeltaEntry(
        path="src/sase/legacy/old_deltas.py", change_type="D"
    )


def test_parse_no_deltas_section_yields_none() -> None:
    """Backwards compat: a CS without DELTAS section parses with deltas=None."""
    lines = _base_lines() + [
        "COMMITS:\n",
        "  (1) Manual commit\n",
        "\n",
    ]
    changespec, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.deltas is None


def test_parse_deltas_path_with_spaces() -> None:
    """Paths containing spaces parse correctly (rest-of-line capture)."""
    lines = _base_lines() + [
        "DELTAS:\n",
        "  + path/with spaces/file name.py\n",
        "  ~ another path/with spaces.txt\n",
        "\n",
    ]
    changespec, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.deltas is not None
    assert changespec.deltas[0].path == "path/with spaces/file name.py"
    assert changespec.deltas[0].change_type == "A"
    assert changespec.deltas[1].path == "another path/with spaces.txt"
    assert changespec.deltas[1].change_type == "M"


def test_format_deltas_empty_list_emits_nothing() -> None:
    """An empty deltas list is omitted (no DELTAS: header on disk)."""
    assert format_deltas_field([]) == []


def test_format_deltas_alphabetical_sort_and_glyphs() -> None:
    """format_deltas_field sorts alphabetically and maps types to glyphs."""
    deltas = [
        DeltaEntry(path="z/last.py", change_type="D"),
        DeltaEntry(path="a/first.py", change_type="M"),
        DeltaEntry(path="m/middle.py", change_type="A"),
    ]
    result = format_deltas_field(deltas)
    assert result == [
        "DELTAS:\n",
        "  ~ a/first.py\n",
        "  + m/middle.py\n",
        "  - z/last.py\n",
    ]


def test_parse_deltas_line_stats_drawers() -> None:
    lines = _base_lines() + [
        "DELTAS:\n",
        "  + src/new.py\n",
        "      | LINES: +12\n",
        "  ~ src/edit.py\n",
        "      | LINES: +2 ~3 -1\n",
        "  - image.bin\n",
        "      | LINES: binary\n",
        "\n",
    ]
    changespec, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.deltas == [
        DeltaEntry(
            path="src/new.py",
            change_type="A",
            line_stats=DeltaLineStats(added=12),
        ),
        DeltaEntry(
            path="src/edit.py",
            change_type="M",
            line_stats=DeltaLineStats(added=2, modified=3, removed=1),
        ),
        DeltaEntry(
            path="image.bin",
            change_type="D",
            line_stats=DeltaLineStats(binary=True),
        ),
    ]


def test_format_deltas_line_stats_drawers() -> None:
    deltas = [
        DeltaEntry(path="zero.py", change_type="A", line_stats=DeltaLineStats()),
        DeltaEntry(
            path="edit.py",
            change_type="M",
            line_stats=DeltaLineStats(added=2, modified=3, removed=1),
        ),
        DeltaEntry(
            path="image.bin",
            change_type="D",
            line_stats=DeltaLineStats(binary=True),
        ),
    ]
    assert format_deltas_field(deltas) == [
        "DELTAS:\n",
        "  ~ edit.py\n",
        "      | LINES: +2 ~3 -1\n",
        "  - image.bin\n",
        "      | LINES: binary\n",
        "  + zero.py\n",
        "      | LINES: 0\n",
    ]


def test_deltas_round_trip_parse_then_format() -> None:
    """Parsing then formatting a DELTAS section returns the original text."""
    # Already alphabetical by path so format() preserves the order.
    deltas_lines = [
        "DELTAS:\n",
        "  + src/sase/ace/changespec/deltas.py\n",
        "  ~ src/sase/ace/changespec/models.py\n",
        "  ~ src/sase/ace/changespec/parser.py\n",
        "  - src/sase/legacy/old_deltas.py\n",
        "  + tests/test_deltas_parsing.py\n",
    ]
    full = _base_lines() + deltas_lines + ["\n"]
    changespec, _ = _parse_changespec_from_lines(full, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.deltas is not None
    formatted = format_deltas_field(changespec.deltas)
    assert formatted == deltas_lines


def test_deltas_round_trip_with_line_stats() -> None:
    deltas_lines = [
        "DELTAS:\n",
        "  ~ a.py\n",
        "      | LINES: ~1\n",
        "  + b.py\n",
        "      | LINES: +2\n",
        "  - c.bin\n",
        "      | LINES: binary\n",
    ]
    full = _base_lines() + deltas_lines + ["\n"]
    changespec, _ = _parse_changespec_from_lines(full, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.deltas is not None
    assert format_deltas_field(changespec.deltas) == deltas_lines
