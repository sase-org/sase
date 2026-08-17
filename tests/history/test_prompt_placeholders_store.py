"""Tests for placeholder store durability, removal, and source tokens."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    common_placeholder_source_token,
    load_common_placeholder_index,
    load_common_placeholders,
    record_prompt_placeholders,
    remove_common_placeholder,
    seed_common_placeholders_from_history,
)
from sase.history.prompt_store import (
    add_or_update_prompt,
    load_prompt_history,
    record_failed_launch_prompt,
)
from tests.history._prompt_placeholders_helpers import (
    core_entries,
    freeze_timestamps,
    make_sase_home,
    read_store,
    store_file,
    write_store,
)


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the placeholder limit to 100."""
    return make_sase_home(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "payload",
    [
        '{"version": 1, "placehol',
        "not json at all",
        '{"version": 3, "placeholders": [{"text": "alpha", "count": 3, '
        '"last_used": "260701_000000"}]}',
        '{"version": 1, "placeholders": [{"text": "alpha"}]}',
        "",
    ],
)
def test_unusable_store_loads_empty_and_is_replaced(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
) -> None:
    store_file(sase_home_dir).write_text(payload, encoding="utf-8")
    assert load_common_placeholders(10) == []

    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<alpha>")

    recorded = read_store(sase_home_dir)
    assert recorded["version"] == 2
    assert core_entries(sase_home_dir) == [
        {"text": "alpha", "count": 1, "last_used": "260701_000000"}
    ]


def test_version_2_payload_with_missing_stats_degrades_to_zero(
    sase_home_dir: Path,
) -> None:
    write_store(
        sase_home_dir,
        {
            "version": 2,
            "prompt_count": -3,
            "context_frequency": {"write": -1, "plan": True, "": 2},
            "placeholders": [
                {
                    "text": "alpha",
                    "count": 3,
                    "last_used": "260701_000000",
                    "context_uses": -1,
                    "context": [],
                }
            ],
        },
    )

    assert load_common_placeholders(10) == ["alpha"]
    index = load_common_placeholder_index()
    assert index.prompt_count == 0
    assert index.context_frequency == {}
    assert index.max_count == 3
    assert index.entries[0].context_uses == 0
    assert index.entries[0].context == {}


def test_store_write_failure_does_not_break_prompt_recording(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_entries: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_payload", _boom)

    add_or_update_prompt("a long enough prompt about <alpha> tags")
    record_failed_launch_prompt("<beta>")

    assert load_common_placeholders(10) == []
    assert sorted(prompt.text for prompt in load_prompt_history()) == [
        "<beta>",
        "a long enough prompt about <alpha> tags",
    ]


def test_failed_write_leaves_the_previous_store_readable(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000", "260702_000000"])
    record_prompt_placeholders("<alpha>")
    before = read_store(sase_home_dir)

    def _boom(_loaded: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_payload", _boom)
    record_prompt_placeholders("<beta>")

    assert read_store(sase_home_dir) == before
    assert load_common_placeholders(10) == ["alpha"]


def test_source_token_tracks_the_store_file(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = common_placeholder_source_token()
    assert missing == (str(store_file(sase_home_dir)), -1, -1)

    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<alpha>")

    assert common_placeholder_source_token() != missing


def test_remove_common_placeholder_preserves_remaining_order_and_counts(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<alpha> <beta>")
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<alpha> <gamma>")
    before = read_store(sase_home_dir)["placeholders"]

    assert remove_common_placeholder("beta") is True
    assert remove_common_placeholder("missing") is False

    assert read_store(sase_home_dir)["placeholders"] == [
        entry for entry in before if entry["text"] != "beta"
    ]


def test_remove_common_placeholder_leaves_corpus_statistics(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<alpha> <beta>")
    before = read_store(sase_home_dir)

    assert remove_common_placeholder("beta") is True

    after = read_store(sase_home_dir)
    assert after["prompt_count"] == before["prompt_count"]
    assert after["context_frequency"] == before["context_frequency"]
    assert [item["text"] for item in after["placeholders"]] == ["alpha"]


def test_removing_last_placeholder_leaves_store_present_and_seeded(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<alpha>")

    before = read_store(sase_home_dir)
    assert remove_common_placeholder("alpha") is True
    assert store_file(sase_home_dir).exists()
    after = read_store(sase_home_dir)
    assert after["version"] == 2
    assert after["placeholders"] == []
    assert after["prompt_count"] == before["prompt_count"]
    assert after["context_frequency"] == before["context_frequency"]

    with patch.object(
        store,
        "iter_shard_paths_newest_first",
        side_effect=AssertionError("history seed reran"),
    ):
        assert seed_common_placeholders_from_history(100) is False
