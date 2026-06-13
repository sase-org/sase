"""Tests for the read-only prompt-history catalog layer."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.prompt import (
    PromptEntry,
    PromptHistoryRecord,
    PromptSelectorError,
    _save_prompt_history,
    compute_prompt_stats,
    list_prompt_records,
    resolve_prompt_selector,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_id(text: str) -> str:
    return f"ph_{_sha256(text)[:12]}"


@pytest.fixture
def history_file(tmp_path: Path) -> Iterator[Path]:
    """Point the prompt-history store at an isolated temp file."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        yield test_file


def _entry(
    text: str,
    last_used: str,
    *,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=last_used,
        last_used=last_used,
        cancelled=cancelled,
    )


# ---------------------------------------------------------------------------
# ID / hash generation
# ---------------------------------------------------------------------------


def test_compute_prompt_id_is_stable_and_content_addressed() -> None:
    text = "fix the parser bug in the login flow"

    first = prompt_id(text)
    assert first == prompt_id(text)
    assert first.startswith("ph_")
    assert len(first) == len("ph_") + 12
    assert first[3:] == _sha256(text)[:12]
    assert prompt_id("a different prompt") != first


# ---------------------------------------------------------------------------
# Listing / filtering
# ---------------------------------------------------------------------------


def test_list_defaults_to_non_cancelled_recency_order(history_file: Path) -> None:
    _save_prompt_history(
        [
            _entry("alpha prompt one", "260601_000000"),
            _entry("beta prompt two", "260603_000000"),
            _entry("cancelled prompt three", "260605_000000", cancelled=True),
        ]
    )

    records = list_prompt_records()

    assert [r.text for r in records] == ["beta prompt two", "alpha prompt one"]


def test_list_all_includes_cancelled(history_file: Path) -> None:
    _save_prompt_history(
        [
            _entry("alpha prompt one", "260601_000000"),
            _entry("cancelled prompt three", "260605_000000", cancelled=True),
        ]
    )

    records = list_prompt_records(include_cancelled=True)

    assert len(records) == 2


def test_list_cancelled_only_and_precedence(history_file: Path) -> None:
    _save_prompt_history(
        [
            _entry("alpha prompt one", "260601_000000"),
            _entry("cancelled prompt three", "260605_000000", cancelled=True),
        ]
    )

    cancelled = list_prompt_records(cancelled_only=True)
    assert [r.text for r in cancelled] == ["cancelled prompt three"]

    # --cancelled takes precedence over --all.
    both = list_prompt_records(include_cancelled=True, cancelled_only=True)
    assert [r.text for r in both] == ["cancelled prompt three"]


def test_list_query_is_case_insensitive_substring(history_file: Path) -> None:
    _save_prompt_history(
        [
            _entry("Fix the AUTH bug now", "260601_000000"),
            _entry("refactor the parser", "260602_000000"),
        ]
    )

    records = list_prompt_records(query="auth")

    assert [r.text for r in records] == ["Fix the AUTH bug now"]


def test_list_limit_applies_after_sort(history_file: Path) -> None:
    _save_prompt_history(
        [
            _entry("alpha prompt one", "260601_000000"),
            _entry("beta prompt two", "260603_000000"),
            _entry("gamma prompt three", "260602_000000"),
        ]
    )

    records = list_prompt_records(limit=1)

    assert [r.text for r in records] == ["beta prompt two"]


def test_records_expose_stable_id_and_hash(history_file: Path) -> None:
    _save_prompt_history([_entry("fix the parser bug", "260601_000000")])

    (record,) = list_prompt_records()

    assert record.id == prompt_id("fix the parser bug")
    assert record.text_sha256 == _sha256("fix the parser bug")
    assert record.text_chars == len("fix the parser bug")


# ---------------------------------------------------------------------------
# Selector resolution
# ---------------------------------------------------------------------------


def test_resolve_by_full_id_bare_prefix_and_sha256(history_file: Path) -> None:
    text = "fix the parser bug"
    _save_prompt_history([_entry(text, "260601_000000")])
    digest = _sha256(text)

    assert resolve_prompt_selector(prompt_id(text)).text == text
    assert resolve_prompt_selector(digest[:8]).text == text
    assert resolve_prompt_selector(f"sha256:{digest}").text == text


def test_resolve_selectors_stable_after_newer_prompts(history_file: Path) -> None:
    text = "fix the parser bug"
    _save_prompt_history([_entry(text, "260601_000000")])
    selector = prompt_id(text)

    _save_prompt_history(
        [
            _entry(text, "260601_000000"),
            _entry("a brand new prompt", "260609_000000"),
        ]
    )

    assert resolve_prompt_selector(selector).text == text


def test_resolve_not_found_and_bad_selectors(history_file: Path) -> None:
    _save_prompt_history([_entry("fix the parser bug", "260601_000000")])

    with pytest.raises(PromptSelectorError):
        resolve_prompt_selector("ph_ffffffffffff")
    with pytest.raises(PromptSelectorError):
        resolve_prompt_selector("zzz")
    with pytest.raises(PromptSelectorError):
        resolve_prompt_selector("")


def test_resolve_ambiguous_prefix_lists_matches() -> None:
    records = [
        PromptHistoryRecord(
            id="ph_abcd00000000",
            text_sha256="abcd0000" + "0" * 56,
            text="first",
            timestamp="260601_000000",
            last_used="260601_000000",
            cancelled=False,
        ),
        PromptHistoryRecord(
            id="ph_abcd11111111",
            text_sha256="abcd1111" + "1" * 56,
            text="second",
            timestamp="260602_000000",
            last_used="260602_000000",
            cancelled=False,
        ),
    ]

    with pytest.raises(PromptSelectorError) as exc_info:
        resolve_prompt_selector("abcd", records=records)

    assert exc_info.value.matches == [
        "ph_abcd00000000",
        "ph_abcd11111111",
    ]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_compute_prompt_stats(history_file: Path) -> None:
    _save_prompt_history(
        [
            _entry("aaaa bbbb", "260601_000000"),
            _entry("#gh:sase do the longer thing right now", "260603_000000"),
            _entry("cancel me please", "260602_000000", cancelled=True),
        ]
    )

    stats = compute_prompt_stats()

    assert stats.exists is True
    assert stats.total == 3
    assert stats.launched == 2
    assert stats.cancelled == 1
    assert stats.oldest_last_used == "260601_000000"
    assert stats.newest_last_used == "260603_000000"
    assert stats.length_percentiles["max"] == len(
        "#gh:sase do the longer thing right now"
    )
    # Largest is sorted by size descending and never carries a multiline body.
    assert stats.largest[0].text_chars >= stats.largest[-1].text_chars
    for item in stats.largest:
        assert "\n" not in item.preview


def test_stats_reports_missing_store(history_file: Path) -> None:
    stats = compute_prompt_stats()

    assert stats.exists is False
    assert stats.total == 0
    assert stats.size_bytes == 0
    assert stats.oldest_last_used is None


# ---------------------------------------------------------------------------
# Corrupt store tolerance (read-only commands must not crash)
# ---------------------------------------------------------------------------


def test_corrupt_history_is_tolerated_read_only(history_file: Path) -> None:
    history_file.write_text("{ this is not valid json ]", encoding="utf-8")

    assert list_prompt_records() == []

    stats = compute_prompt_stats()
    assert stats.exists is True
    assert stats.total == 0

    with pytest.raises(PromptSelectorError):
        resolve_prompt_selector("ph_abc")
