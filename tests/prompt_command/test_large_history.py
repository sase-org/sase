"""Large-history output bounds for ``sase prompt`` inspection commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.history.prompt import PromptEntry
from sase.prompt.cli_list import handle_prompt_list
from sase.prompt.cli_maintenance import handle_prompt_doctor
from sase.prompt.cli_stats import handle_prompt_stats

from ._helpers import _entry, _seed

# A history big enough that an unbounded command would be obviously wrong:
# thousands of ordinary prompts plus a handful of very large pastes. The
# read-only inspection commands must stay bounded and must never echo a full
# prompt body, only previews.
_BULK_PROMPT_COUNT = 3000
_HUGE_PROMPT_CHARS = 50_000
_HUGE_PROMPT_COUNT = 4

# Bounds the source code promises for inspection output.
_LIST_DEFAULT_LIMIT = 20
_STATS_LARGEST_LIMIT = 5
_STATS_CHIPS_LIMIT = 10
_DOCTOR_LIST_LIMIT = 5
_PREVIEW_MAX = 73  # 72-char window plus a possible ellipsis


@pytest.fixture
def large_history(history_file: Path) -> list[str]:
    """Seed thousands of prompts plus a few very large ones.

    Each huge prompt hides a unique sentinel near its very end, far beyond any
    preview cutoff, and the huge prompts carry the most recent timestamps so
    they land in the default ``list`` window. Returns the sentinels so callers
    can assert the full body never reaches command output.
    """
    entries: list[PromptEntry] = [
        _entry(f"bulk prompt number {i}", f"260101_{i:06d}")
        for i in range(_BULK_PROMPT_COUNT)
    ]

    sentinels: list[str] = []
    for j in range(_HUGE_PROMPT_COUNT):
        sentinel = f"SECRET_TAIL_{j}_END"
        sentinels.append(sentinel)
        # Innocuous head, a huge body, and the secret buried at the tail.
        text = f"huge paste {j} " + ("x" * _HUGE_PROMPT_CHARS) + f" {sentinel}"
        entries.append(_entry(text, f"260201_00000{j}"))

    _seed(*entries)
    return sentinels


def _assert_bounded_and_no_full_text(output: str, sentinels: list[str]) -> None:
    """No buried sentinel and no long run of the huge body may leak."""
    for sentinel in sentinels:
        assert sentinel not in output, f"leaked full prompt body ({sentinel})"
    # Previews cap well under 200 chars, so a long ``x`` run means a full
    # huge body escaped into the rendered output.
    assert "x" * 200 not in output


def test_large_history_list_stays_bounded_and_hides_full_text(
    large_history: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = large_history

    # Default pretty table: bounded rows, previews only.
    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )
    _assert_bounded_and_no_full_text(capsys.readouterr().out, sentinels)

    # Default JSON: at most the limit, preview-only, no full text.
    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=True)
    )
    out = capsys.readouterr().out
    _assert_bounded_and_no_full_text(out, sentinels)
    payload = json.loads(out)
    assert len(payload) == _LIST_DEFAULT_LIMIT
    for row in payload:
        assert "text" not in row  # list never emits full text
        assert len(row["text_preview"]) <= _PREVIEW_MAX


def test_large_history_stats_stays_bounded_and_hides_full_text(
    large_history: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = large_history

    handle_prompt_stats(argparse.Namespace(json=True))
    out = capsys.readouterr().out
    _assert_bounded_and_no_full_text(out, sentinels)
    payload = json.loads(out)
    assert payload["total"] == _BULK_PROMPT_COUNT + _HUGE_PROMPT_COUNT
    assert payload["length_percentiles"]["max"] >= _HUGE_PROMPT_CHARS
    assert len(payload["largest"]) <= _STATS_LARGEST_LIMIT
    assert len(payload["top_chips"]) <= _STATS_CHIPS_LIMIT
    for item in payload["largest"]:
        assert "text" not in item
        assert len(item["preview"]) <= _PREVIEW_MAX

    handle_prompt_stats(argparse.Namespace(json=False))
    _assert_bounded_and_no_full_text(capsys.readouterr().out, sentinels)


def test_large_history_doctor_stays_bounded_and_hides_full_text(
    large_history: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = large_history

    handle_prompt_doctor(argparse.Namespace(json=True))
    out = capsys.readouterr().out
    _assert_bounded_and_no_full_text(out, sentinels)
    payload = json.loads(out)
    assert payload["parseable"] is True
    assert payload["total"] == _BULK_PROMPT_COUNT + _HUGE_PROMPT_COUNT
    assert len(payload["oversized"]) <= _DOCTOR_LIST_LIMIT
    for item in payload["oversized"]:
        assert item["text_chars"] >= _HUGE_PROMPT_CHARS
        assert len(item["preview"]) <= _PREVIEW_MAX

    handle_prompt_doctor(argparse.Namespace(json=False))
    _assert_bounded_and_no_full_text(capsys.readouterr().out, sentinels)
