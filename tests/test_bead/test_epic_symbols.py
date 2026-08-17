"""Unit coverage for Justfile ``--epic-symbol`` discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.epic_symbols import (
    _EpicSymbolEntry,
    _LeftoverEpicSymbolsError,
    _leftover_epic_symbols_for_close,
    _parse_epic_symbol_entries,
    discover_justfile,
    entries_for_beads,
    raise_if_leftover_epic_symbols,
)
from sase.bead.model import Issue, IssueType, Status


def _issue(issue_id: str, *, status: Status = Status.IN_PROGRESS) -> Issue:
    return Issue(
        id=issue_id,
        title=issue_id,
        issue_type=IssueType.PLAN,
        status=status,
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
    )


def test_parse_epic_symbol_entries_accepts_quoted_and_bare_flags() -> None:
    text = """
        --epic-symbol "sase-nb(encode_feature_flags_env)" \\
        --epic-symbol 'sase-o8.4(PlaceholderRankingMetadata)' \\
        --epic-symbol=sase-n4(UsageLimitSettings) \\
        --epic-symbol sase-n4.5(ProviderDisableWriteOutcome) \\
        --epic-symbol "not-a-body"
    """

    parsed = _parse_epic_symbol_entries(text, source=Path("Justfile"))

    assert [entry.raw for entry in parsed] == [
        "sase-nb(encode_feature_flags_env)",
        "sase-o8.4(PlaceholderRankingMetadata)",
        "sase-n4(UsageLimitSettings)",
        "sase-n4.5(ProviderDisableWriteOutcome)",
    ]
    assert parsed[0].flag == '--epic-symbol "sase-nb(encode_feature_flags_env)"'
    assert parsed[1].bead_id == "sase-o8.4"
    assert parsed[1].symbol == "PlaceholderRankingMetadata"


def test_entries_for_beads_include_descendant_suffixes_only() -> None:
    entries = _parse_epic_symbol_entries(
        """
        --epic-symbol "sase-o8(CommonIndex)"
        --epic-symbol "sase-o8.3(RankedPlaceholder)"
        --epic-symbol "sase-o8.4(load_common_placeholder_index)"
        --epic-symbol "sase-o9.2(monitor_row_agent_name)"
        """
    )

    epic = [entry.raw for entry in entries_for_beads(entries, ["sase-o8"])]
    phase = [entry.raw for entry in entries_for_beads(entries, ["sase-o8.3"])]

    assert epic == [
        "sase-o8(CommonIndex)",
        "sase-o8.3(RankedPlaceholder)",
        "sase-o8.4(load_common_placeholder_index)",
    ]
    assert phase == ["sase-o8.3(RankedPlaceholder)"]


def test_leftover_epic_symbols_skip_already_closed_targets() -> None:
    entries = [
        _EpicSymbolEntry(bead_id="sase-o8.2", symbol="CommonPlaceholderIndex"),
    ]

    leftovers = _leftover_epic_symbols_for_close(
        [_issue("sase-o8.2", status=Status.CLOSED)],
        entries,
    )

    assert leftovers == []


def test_discover_justfile_stops_at_git_root_without_crossing_it(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    nested = repo / "src"
    nested.mkdir()

    assert discover_justfile(nested) is None

    justfile = repo / "Justfile"
    justfile.write_text('--epic-symbol "sase-x(Foo)"\n', encoding="utf-8")

    assert discover_justfile(nested) == justfile


def test_raise_if_leftover_epic_symbols_names_the_justfile_flags(
    tmp_path: Path,
) -> None:
    (tmp_path / "Justfile").write_text(
        '--epic-symbol "sase-o8.2(CommonPlaceholderIndex)"\n'
        '--epic-symbol "sase-o8.2(load_common_placeholder_index)"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        _LeftoverEpicSymbolsError, match="refusing to close"
    ) as exc_info:
        raise_if_leftover_epic_symbols(
            [_issue("sase-o8.2")],
            start=tmp_path,
        )

    message = str(exc_info.value)
    assert '--epic-symbol "sase-o8.2(CommonPlaceholderIndex)"' in message
    assert '--epic-symbol "sase-o8.2(load_common_placeholder_index)"' in message
    assert "sase bead epic-symbols sase-o8.2" in message
