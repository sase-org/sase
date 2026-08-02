"""Tests for prompt-search date parsing and archive date precedence."""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sase.prompt.search.dates import (
    PromptSearchDateError,
    hit_date,
    parse_search_date,
    resolve_archive_date,
)
from sase.prompt.search.model import PromptHit, PromptSource

_UTC = ZoneInfo("UTC")
# A fixed "now" so relative-offset parsing is deterministic.
_FIXED_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=_UTC)


@pytest.fixture
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``_now`` and the timezone so date math is reproducible."""
    monkeypatch.setattr("sase.prompt.search.dates._now", lambda: _FIXED_NOW)
    monkeypatch.setattr("sase.prompt.search.dates._timezone", lambda: _UTC)


# ---------------------------------------------------------------------------
# parse_search_date — absolute forms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-15", "260115_000000"),
        ("260104", "260104_000000"),
        ("260104_143000", "260104_143000"),
        ("202604", "260401_000000"),
        ("202612", "261201_000000"),
    ],
)
def test_parse_search_date_absolute_forms(value: str, expected: str) -> None:
    assert parse_search_date(value) == expected


def test_parse_search_date_six_digits_prefers_yymmdd() -> None:
    # ``260104`` is a valid YYmmdd (2026-01-04) and must win over YYYYMM.
    assert parse_search_date("260104") == "260104_000000"
    # ``202604`` is not a valid YYmmdd (month 26) so it falls back to YYYYMM.
    assert parse_search_date("202604") == "260401_000000"


def test_parse_search_date_strips_surrounding_whitespace() -> None:
    assert parse_search_date("  2026-01-15  ") == "260115_000000"


# ---------------------------------------------------------------------------
# parse_search_date — relative offsets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("30d", "260519_000000"),
        ("0d", "260618_000000"),
        ("2w", "260604_000000"),
        ("6m", "251218_000000"),
        ("1y", "250618_000000"),
        ("24m", "240618_000000"),
    ],
)
@pytest.mark.usefixtures("fixed_now")
def test_parse_search_date_relative_offsets(value: str, expected: str) -> None:
    assert parse_search_date(value) == expected


@pytest.mark.usefixtures("fixed_now")
def test_parse_search_date_relative_is_case_insensitive() -> None:
    assert parse_search_date("30D") == parse_search_date("30d")


def test_parse_search_date_month_offset_clamps_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1 month before 2026-03-31 has no 31st of February → clamps to the 28th.
    monkeypatch.setattr(
        "sase.prompt.search.dates._now",
        lambda: datetime(2026, 3, 31, 9, 0, 0, tzinfo=_UTC),
    )
    assert parse_search_date("1m") == "260228_000000"


# ---------------------------------------------------------------------------
# parse_search_date — rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "   ", "garbage", "2026-13-01", "999999", "12", "tomorrow", "5x", "d30"],
)
def test_parse_search_date_rejects_garbage(value: str) -> None:
    with pytest.raises(PromptSearchDateError):
        parse_search_date(value)


def test_parse_search_date_error_lists_examples() -> None:
    with pytest.raises(PromptSearchDateError) as exc:
        parse_search_date("nope")
    message = str(exc.value)
    assert "YYYY-MM-DD" in message
    assert "30d" in message


# ---------------------------------------------------------------------------
# resolve_archive_date — precedence
# ---------------------------------------------------------------------------


def test_resolve_archive_date_prefers_frontmatter_last_used() -> None:
    path = Path("prompts/202604/x.md")
    resolved = resolve_archive_date(
        {"last_used": "260512_143000", "timestamp": "260101_000000"}, path
    )
    assert resolved == "260512_143000"


def test_resolve_archive_date_falls_back_to_timestamp() -> None:
    path = Path("prompts/202604/x.md")
    assert resolve_archive_date({"timestamp": "260101_000000"}, path) == "260101_000000"


def test_resolve_archive_date_accepts_yaml_date_objects() -> None:
    path = Path("prompts/202604/x.md")
    assert (
        resolve_archive_date({"last_used": date(2026, 5, 12)}, path) == "260512_000000"
    )
    moment = datetime(2026, 5, 12, 8, 9, 10)
    assert resolve_archive_date({"timestamp": moment}, path) == "260512_080910"


def test_resolve_archive_date_falls_back_to_path_yyyymm() -> None:
    path = Path("prompts/202604/x.md")
    assert resolve_archive_date({}, path) == "260401_000000"


def test_resolve_archive_date_ignores_unparseable_frontmatter_date() -> None:
    # A garbage frontmatter date is skipped, not fatal: precedence drops to path.
    path = Path("prompts/202604/x.md")
    assert resolve_archive_date({"last_used": "not-a-date"}, path) == "260401_000000"


def test_resolve_archive_date_falls_back_to_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.prompt.search.dates._timezone", lambda: _UTC)
    snapshot = tmp_path / "flat.md"  # not under a YYYYMM directory
    snapshot.write_text("body\n", encoding="utf-8")
    mtime = datetime(2026, 3, 4, 5, 6, 7, tzinfo=_UTC).timestamp()
    os.utime(snapshot, (mtime, mtime))
    assert resolve_archive_date({}, snapshot) == "260304_050607"


# ---------------------------------------------------------------------------
# hit_date
# ---------------------------------------------------------------------------


def _hit(date_value: str) -> PromptHit:
    return PromptHit(
        source=PromptSource.LOCAL,
        id="ph_x",
        text="t",
        title="t",
        date=date_value,
        text_sha256="abc",
    )


def test_hit_date_returns_stored_date() -> None:
    assert hit_date(_hit("260512_143000")) == "260512_143000"


def test_hit_date_floors_empty_date() -> None:
    floored = hit_date(_hit(""))
    assert floored == "000000_000000"
