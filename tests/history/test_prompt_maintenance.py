"""Tests for the prompt-history maintenance layer (doctor/delete/prune)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.prompt import (
    PromptDateError,
    PromptSelectorError,
    PromptStoreCorruptError,
    compute_prompt_doctor,
    delete_prompt,
    parse_prune_date,
    prune_prompts,
)
from sase.history.prompt_store import (
    PromptEntry,
    load_prompt_history,
    save_prompt_history,
)


def _prompt_id(text: str) -> str:
    """Local re-implementation of the stable ``ph_<sha256[:12]>`` content ID."""
    return f"ph_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


@pytest.fixture
def history_file(tmp_path: Path) -> Iterator[Path]:
    """Point the prompt-history store at an isolated temp file."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        yield test_file


def _entry(
    text: str,
    last_used: str,
    *,
    cancelled: bool = False,
    workspace: str = "",
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=last_used,
        last_used=last_used,
        cancelled=cancelled,
        workspace=workspace,
    )


# ---------------------------------------------------------------------------
# parse_prune_date
# ---------------------------------------------------------------------------


def test_parse_prune_date_accepts_supported_formats() -> None:
    assert parse_prune_date("2026-01-01") == "260101_000000"
    assert parse_prune_date("260101") == "260101_000000"
    assert parse_prune_date("260101_143000") == "260101_143000"


def test_parse_prune_date_rejects_ambiguous_with_examples() -> None:
    with pytest.raises(PromptDateError) as exc_info:
        parse_prune_date("20260101")

    message = str(exc_info.value)
    assert "YYYY-MM-DD" in message
    assert "YYmmdd" in message
    # Nonsense calendar dates are rejected too.
    with pytest.raises(PromptDateError):
        parse_prune_date("2026-13-45")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_one_prompt(history_file: Path) -> None:
    keep = "keep this launched prompt"
    drop = "delete this other prompt"
    save_prompt_history([_entry(keep, "260601_000000"), _entry(drop, "260602_000000")])

    deleted = delete_prompt(_prompt_id(drop))

    assert deleted.id == _prompt_id(drop)
    assert [e.text for e in load_prompt_history()] == [keep]


def test_delete_unknown_selector_does_not_rewrite(history_file: Path) -> None:
    save_prompt_history([_entry("a stored prompt here", "260601_000000")])
    before = history_file.read_text(encoding="utf-8")

    with pytest.raises(PromptSelectorError):
        delete_prompt("ph_ffffffffffff")

    assert history_file.read_text(encoding="utf-8") == before


def test_delete_uses_atomic_replace_and_lock(history_file: Path) -> None:
    drop = "delete this prompt atomically"
    save_prompt_history(
        [_entry("survivor prompt", "260601_000000"), _entry(drop, "260602_000000")]
    )

    replace_calls: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def tracking_replace(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        replace_calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    with (
        patch("sase.history.prompt_store.os.replace", side_effect=tracking_replace),
        patch("sase.history.prompt_store.locked_prompt_history") as mock_lock,
    ):
        delete_prompt(_prompt_id(drop))

    assert mock_lock.called
    assert len(replace_calls) == 1
    temp_path, final_path = replace_calls[0]
    assert final_path == history_file
    assert not temp_path.exists()


def test_delete_corrupt_store_aborts_without_rewrite(history_file: Path) -> None:
    history_file.write_text("{ not valid json ]", encoding="utf-8")
    before = history_file.read_text(encoding="utf-8")

    with pytest.raises(PromptStoreCorruptError):
        delete_prompt("ph_abc")

    assert history_file.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def test_prune_keep_retains_newest(history_file: Path) -> None:
    save_prompt_history(
        [
            _entry("oldest prompt", "260601_000000"),
            _entry("middle prompt", "260602_000000"),
            _entry("newest prompt", "260603_000000"),
        ]
    )

    plan = prune_prompts(keep=1)

    assert plan.applied is True
    assert {r.text for r in plan.removed} == {"oldest prompt", "middle prompt"}
    assert [e.text for e in load_prompt_history()] == ["newest prompt"]


def test_prune_before_removes_older(history_file: Path) -> None:
    save_prompt_history(
        [
            _entry("ancient prompt", "251201_000000"),
            _entry("recent prompt", "260605_000000"),
        ]
    )

    plan = prune_prompts(before=parse_prune_date("2026-01-01"))

    assert {r.text for r in plan.removed} == {"ancient prompt"}
    assert [e.text for e in load_prompt_history()] == ["recent prompt"]


def test_prune_cancelled_only(history_file: Path) -> None:
    save_prompt_history(
        [
            _entry("launched prompt", "260601_000000"),
            _entry("cancelled prompt", "260602_000000", cancelled=True),
        ]
    )

    plan = prune_prompts(cancelled_only=True)

    assert {r.text for r in plan.removed} == {"cancelled prompt"}
    assert [e.text for e in load_prompt_history()] == ["launched prompt"]


def test_prune_keep_is_a_hard_floor_for_before(history_file: Path) -> None:
    # Even though every entry is "before" the cutoff, --keep protects the newest.
    save_prompt_history(
        [
            _entry("old one", "251101_000000"),
            _entry("old two", "251102_000000"),
            _entry("old three", "251103_000000"),
        ]
    )

    plan = prune_prompts(keep=1, before=parse_prune_date("2026-01-01"))

    # Intersection: removable must be both beyond-newest-1 AND older-than-cutoff.
    assert {r.text for r in plan.removed} == {"old one", "old two"}
    assert [e.text for e in load_prompt_history()] == ["old three"]


def test_prune_dry_run_does_not_mutate(history_file: Path) -> None:
    save_prompt_history(
        [
            _entry("keep me", "260603_000000"),
            _entry("drop me", "260601_000000"),
        ]
    )
    before = history_file.read_text(encoding="utf-8")

    plan = prune_prompts(keep=1, dry_run=True)

    assert plan.applied is False
    assert {r.text for r in plan.removed} == {"drop me"}
    assert history_file.read_text(encoding="utf-8") == before


def test_prune_requires_a_predicate(history_file: Path) -> None:
    save_prompt_history([_entry("a prompt", "260601_000000")])

    with pytest.raises(ValueError):
        prune_prompts()


def test_prune_corrupt_store_aborts(history_file: Path) -> None:
    history_file.write_text("{ not valid json ]", encoding="utf-8")

    with pytest.raises(PromptStoreCorruptError):
        prune_prompts(keep=1)


def test_prune_reports_per_predicate_counts(history_file: Path) -> None:
    save_prompt_history(
        [
            _entry("old cancelled", "251101_000000", cancelled=True),
            _entry("old launched", "251102_000000"),
            _entry("new cancelled", "260605_000000", cancelled=True),
        ]
    )

    plan = prune_prompts(
        keep=1, before=parse_prune_date("2026-01-01"), cancelled_only=True, dry_run=True
    )

    # Candidates are the two cancelled prompts.
    assert plan.candidate_count == 2
    # Only "old cancelled" is both beyond newest-1 and older than the cutoff.
    assert {r.text for r in plan.removed} == {"old cancelled"}


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_reports_counts_and_availability(history_file: Path) -> None:
    save_prompt_history(
        [
            _entry("launched prompt one", "260601_000000"),
            _entry("cancelled prompt two", "260602_000000", cancelled=True),
        ]
    )

    with (
        patch(
            "sase.history.prompt_maintenance.shutil.which", return_value="/usr/bin/fzf"
        ),
        patch("sase.core.clipboard.clipboard_available", return_value=True),
    ):
        report = compute_prompt_doctor()

    assert report.exists is True
    assert report.parseable is True
    assert report.total == 2
    assert report.cancelled == 1
    assert report.invalid_entries == 0
    assert report.fzf_available is True
    assert report.clipboard_available is True


def test_doctor_flags_corrupt_store(history_file: Path) -> None:
    history_file.write_text("{ not valid json ]", encoding="utf-8")

    report = compute_prompt_doctor()

    assert report.exists is True
    assert report.parseable is False
    assert report.total == 0


def test_doctor_counts_invalid_entries(history_file: Path) -> None:
    history_file.write_text(
        '{"prompts": [{"text": "valid one here", "timestamp": "260601_000000",'
        ' "last_used": "260601_000000"}, {"text": 123}, "garbage"]}',
        encoding="utf-8",
    )

    report = compute_prompt_doctor()

    assert report.parseable is True
    assert report.total == 1
    assert report.invalid_entries == 2


def test_doctor_flags_oversized_and_short_and_legacy(history_file: Path) -> None:
    # Legacy context fields only survive in pre-existing files: new writes drop
    # them, so seed the raw store directly to exercise the legacy-field count.
    big = "huge " + "x" * 11000
    history_file.write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "text": big,
                        "timestamp": "260601_000000",
                        "last_used": "260601_000000",
                    },
                    {
                        "text": "#gh:foo",  # single token, recovery-path
                        "timestamp": "260602_000000",
                        "last_used": "260602_000000",
                    },
                    {
                        "text": "legacy fielded prompt",
                        "timestamp": "260603_000000",
                        "last_used": "260603_000000",
                        "workspace": "proj",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = compute_prompt_doctor()

    assert [item.id for item in report.oversized] == [_prompt_id(big)]
    assert [item.id for item in report.short_recovery] == [_prompt_id("#gh:foo")]
    assert report.legacy_field_entries == 1
    # Never echoes full oversized text.
    assert "x" * 11000 not in report.oversized[0].preview
