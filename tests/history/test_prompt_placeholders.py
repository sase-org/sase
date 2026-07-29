"""Tests for the durable common-placeholder store."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    _common_placeholder_limit,
    common_placeholder_source_token,
    load_common_placeholders,
    record_prompt_placeholders,
    remove_common_placeholder,
    seed_common_placeholders_from_history,
)
from sase.history.prompt_store import (
    PromptEntry,
    add_or_update_prompt,
    load_prompt_history,
    record_failed_launch_prompt,
    save_shard,
)
from tests.conftest import redirect_sase_home


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the placeholder limit to 100."""
    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    set_limit(monkeypatch, 100)
    return home


def set_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    """Point ``_common_placeholder_limit`` at a fixed configured value."""
    monkeypatch.setattr(
        store,
        "load_merged_config",
        lambda: {"ace": {"prompt_completion": {"common_placeholder_count": limit}}},
    )


def freeze_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    timestamps: list[str],
) -> None:
    """Serve *timestamps* in order, repeating the last one when exhausted."""
    pending = list(timestamps)

    def _next() -> str:
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(store, "generate_timestamp", _next)


def store_file(home: Path) -> Path:
    return home / "prompt_placeholders.json"


def read_store(home: Path) -> dict[str, Any]:
    return json.loads(store_file(home).read_text(encoding="utf-8"))


def entry(text: str, last_used: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=last_used, last_used=last_used)


def test_new_placeholder_is_inserted_then_incremented(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000", "260702_000000"])

    record_prompt_placeholders("write <alpha> now")
    assert read_store(sase_home_dir)["placeholders"] == [
        {"text": "alpha", "count": 1, "last_used": "260701_000000"}
    ]

    record_prompt_placeholders("write <alpha> again")
    assert read_store(sase_home_dir)["placeholders"] == [
        {"text": "alpha", "count": 2, "last_used": "260702_000000"}
    ]
    assert load_common_placeholders(10) == ["alpha"]


def test_placeholder_repeated_in_one_prompt_counts_once(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    record_prompt_placeholders("<alpha> then <alpha> and <alpha>")

    assert read_store(sase_home_dir)["placeholders"] == [
        {"text": "alpha", "count": 1, "last_used": "260701_000000"}
    ]


def test_only_raw_placeholders_are_recorded(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    record_prompt_placeholders("write `<alpha>`")

    assert not store_file(sase_home_dir).exists()

    record_prompt_placeholders("write <alpha>")

    assert load_common_placeholders(10) == ["alpha"]


def test_display_order_is_count_then_recency_then_text(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<beta> <gamma> <delta>")
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<gamma>")
    freeze_timestamps(monkeypatch, ["260703_000000"])
    record_prompt_placeholders("<delta>")

    # gamma and delta both reach count 2, so delta's newer last_used wins; beta
    # and epsilon tie on count and last_used, so the text tiebreak orders them.
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<epsilon>")

    assert load_common_placeholders(10) == ["delta", "gamma", "beta", "epsilon"]


def test_eviction_drops_the_least_recently_used_entry(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_limit(monkeypatch, 2)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    # ``stale`` is used far more often than the others but has not been written
    # since, so LRU retention still drops it once the store is full.
    record_prompt_placeholders("<stale>")
    record_prompt_placeholders("<stale>")
    record_prompt_placeholders("<stale>")
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<older>")
    freeze_timestamps(monkeypatch, ["260703_000000"])
    record_prompt_placeholders("<fresh>")

    assert load_common_placeholders(10) == ["fresh", "older"]


def test_lowering_the_limit_prunes_on_the_next_write(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<one>")
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<two>")
    freeze_timestamps(monkeypatch, ["260703_000000"])
    record_prompt_placeholders("<three>")
    assert len(load_common_placeholders(10)) == 3

    set_limit(monkeypatch, 2)
    freeze_timestamps(monkeypatch, ["260704_000000"])
    record_prompt_placeholders("<four>")

    assert load_common_placeholders(10) == ["four", "three"]


def test_zero_limit_records_nothing_and_loads_nothing(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_limit(monkeypatch, 0)

    record_prompt_placeholders("<alpha> <beta>")

    assert not store_file(sase_home_dir).exists()
    assert load_common_placeholders(0) == []
    assert seed_common_placeholders_from_history(0) is False


def test_limit_falls_back_to_the_default_for_unusable_config(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "load_merged_config", dict)
    assert _common_placeholder_limit() == 100

    monkeypatch.setattr(
        store,
        "load_merged_config",
        lambda: {"ace": {"prompt_completion": {"common_placeholder_count": "many"}}},
    )
    assert _common_placeholder_limit() == 100

    set_limit(monkeypatch, -5)
    assert _common_placeholder_limit() == 0


@pytest.mark.parametrize(
    "payload",
    [
        '{"version": 1, "placehol',
        "not json at all",
        '{"version": 2, "placeholders": [{"text": "alpha", "count": 3, '
        '"last_used": "260701_000000"}]}',
        '{"version": 1, "placeholders": [{"text": "alpha"}]}',
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

    assert read_store(sase_home_dir) == {
        "version": 1,
        "placeholders": [{"text": "alpha", "count": 1, "last_used": "260701_000000"}],
    }


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


def test_short_prompts_contribute_tags_without_entering_history(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    add_or_update_prompt("fix <alpha>")

    assert load_common_placeholders(10) == ["alpha"]
    assert load_prompt_history() == []


def test_cancelled_and_failed_prompts_still_contribute_tags(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    add_or_update_prompt("an abandoned draft mentioning <alpha>", cancelled=True)
    record_failed_launch_prompt("#gh:sase ship <beta>")

    assert sorted(load_common_placeholders(10)) == ["alpha", "beta"]


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


def test_removing_last_placeholder_leaves_store_present_and_seeded(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<alpha>")

    assert remove_common_placeholder("alpha") is True
    assert store_file(sase_home_dir).exists()
    assert read_store(sase_home_dir) == {"version": 1, "placeholders": []}

    with patch.object(
        store,
        "iter_shard_paths_newest_first",
        side_effect=AssertionError("history seed reran"),
    ):
        assert seed_common_placeholders_from_history(100) is False


def test_seed_counts_placeholders_across_shards(sase_home_dir: Path) -> None:
    history_dir = sase_home_dir / "prompt_history"
    save_shard(
        history_dir / "2607.json",
        [
            entry("newer <alpha> and <beta>", "260702_000000"),
            entry("older <alpha>", "260701_000000"),
        ],
    )
    save_shard(history_dir / "2606.json", [entry("archive <beta>", "260601_000000")])

    assert seed_common_placeholders_from_history(100) is True

    assert read_store(sase_home_dir)["placeholders"] == [
        {"text": "alpha", "count": 2, "last_used": "260702_000000"},
        {"text": "beta", "count": 2, "last_used": "260702_000000"},
    ]


def test_seed_stops_after_the_shard_bound(sase_home_dir: Path) -> None:
    paths = [Path(f"shard-{index}.json") for index in range(30)]

    def _load(path: Path) -> list[PromptEntry]:
        index = paths.index(path)
        return [entry(f"<tag{index}>", "260701_000000")]

    with (
        patch.object(
            store,
            "iter_shard_paths_newest_first",
            return_value=iter(paths),
        ),
        patch.object(store, "load_shard", side_effect=_load),
    ):
        assert seed_common_placeholders_from_history(100) is True

    saved = load_common_placeholders(100)
    assert "tag23" in saved
    assert "tag24" not in saved


def test_seed_is_a_no_op_once_the_store_exists(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_dir = sase_home_dir / "prompt_history"
    save_shard(history_dir / "2607.json", [entry("history <beta>", "260701_000000")])
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<alpha>")

    def _forbidden() -> Iterator[Path]:
        raise AssertionError("scanned history for an existing store")

    with patch.object(store, "iter_shard_paths_newest_first", _forbidden):
        assert seed_common_placeholders_from_history(100) is False

    assert load_common_placeholders(10) == ["alpha"]


def test_seed_writes_an_empty_store_without_history(sase_home_dir: Path) -> None:
    assert seed_common_placeholders_from_history(100) is True

    assert read_store(sase_home_dir) == {"version": 1, "placeholders": []}
    assert load_common_placeholders(10) == []
