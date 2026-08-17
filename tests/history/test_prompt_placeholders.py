"""Tests for the durable common-placeholder store."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    CONTEXT_STOPWORD_RATIO,
    CONTEXT_TOKENS_PER_PROMPT,
    _common_placeholder_limit,
    _prompt_context_tokens,
    common_placeholder_source_token,
    load_common_placeholder_index,
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


def core_entries(home: Path) -> list[dict[str, Any]]:
    """Return the version-1 placeholder fields, ignoring context bags."""
    return [
        {"text": item["text"], "count": item["count"], "last_used": item["last_used"]}
        for item in read_store(home)["placeholders"]
    ]


def write_store(home: Path, payload: dict[str, Any]) -> None:
    store_file(home).write_text(json.dumps(payload), encoding="utf-8")


def version_1_store(*placeholders: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "placeholders": list(placeholders)}


def entry(text: str, last_used: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=last_used, last_used=last_used)


def test_new_placeholder_is_inserted_then_incremented(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000", "260702_000000"])

    record_prompt_placeholders("write <alpha> now")
    assert core_entries(sase_home_dir) == [
        {"text": "alpha", "count": 1, "last_used": "260701_000000"}
    ]

    record_prompt_placeholders("write <alpha> again")
    assert core_entries(sase_home_dir) == [
        {"text": "alpha", "count": 2, "last_used": "260702_000000"}
    ]
    assert load_common_placeholders(10) == ["alpha"]


def test_placeholder_repeated_in_one_prompt_counts_once(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    record_prompt_placeholders("<alpha> then <alpha> and <alpha>")

    assert core_entries(sase_home_dir) == [
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

    assert core_entries(sase_home_dir) == [
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

    assert read_store(sase_home_dir) == {
        "version": 2,
        "prompt_count": 0,
        "context_frequency": {},
        "placeholders": [],
    }
    assert load_common_placeholders(10) == []


def test_version_1_store_loads_without_upgrade(sase_home_dir: Path) -> None:
    write_store(
        sase_home_dir,
        version_1_store(
            {"text": "delta", "count": 3, "last_used": "260703_000000"},
            {"text": "gamma", "count": 3, "last_used": "260702_000000"},
            {"text": "alpha", "count": 1, "last_used": "260701_000000"},
        ),
    )

    assert load_common_placeholders(10) == ["delta", "gamma", "alpha"]
    index = load_common_placeholder_index()
    assert index.prompt_count == 0
    assert index.context_frequency == {}
    assert index.max_count == 3
    assert all(
        entry.context_uses == 0 and entry.context == {} for entry in index.entries
    )
    assert read_store(sase_home_dir)["version"] == 1


def test_version_1_store_upgrades_in_place_from_history(sase_home_dir: Path) -> None:
    write_store(
        sase_home_dir,
        version_1_store(
            {"text": "alpha", "count": 5, "last_used": "260615_000000"},
            {"text": "gamma", "count": 1, "last_used": "260610_000000"},
        ),
    )
    history_dir = sase_home_dir / "prompt_history"
    save_shard(
        history_dir / "2607.json",
        [
            entry("newer <alpha> with <beta>", "260702_000000"),
            entry("older <alpha>", "260701_000000"),
        ],
    )

    assert load_common_placeholders(10) == ["alpha", "gamma"]
    assert seed_common_placeholders_from_history(100) is True

    data = read_store(sase_home_dir)
    assert data["version"] == 2
    assert data["prompt_count"] == 2
    by_text = {item["text"]: item for item in data["placeholders"]}
    assert set(by_text) == {"alpha", "beta", "gamma"}
    assert by_text["alpha"]["count"] == 5
    assert by_text["alpha"]["last_used"] == "260615_000000"
    assert by_text["alpha"]["context_uses"] == 2
    assert "<beta>" in by_text["alpha"]["context"]
    assert "<alpha>" not in by_text["alpha"]["context"]
    assert by_text["gamma"]["count"] == 1
    assert by_text["gamma"]["last_used"] == "260610_000000"
    assert by_text["beta"]["count"] == 1
    assert by_text["beta"]["last_used"] == "260702_000000"
    assert seed_common_placeholders_from_history(100) is False


def test_version_1_upgrade_keeps_a_submit_that_races_the_scan(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_store(
        sase_home_dir,
        version_1_store({"text": "alpha", "count": 4, "last_used": "260601_000000"}),
    )
    save_shard(
        sase_home_dir / "prompt_history" / "2607.json",
        [entry("history <alpha> <beta>", "260701_000000")],
    )
    freeze_timestamps(monkeypatch, ["260805_000000"])
    original_load = store.load_shard
    raced = False

    def _race(path: Path) -> list[PromptEntry]:
        nonlocal raced
        if not raced:
            raced = True
            record_prompt_placeholders("live <fresh>")
        return original_load(path)

    with patch.object(store, "load_shard", side_effect=_race):
        assert seed_common_placeholders_from_history(100) is True

    by_text = {item["text"]: item for item in read_store(sase_home_dir)["placeholders"]}
    assert by_text["alpha"]["count"] == 4
    assert by_text["alpha"]["last_used"] == "260601_000000"
    assert "beta" in by_text
    assert by_text["fresh"]["count"] == 1
    assert by_text["fresh"]["last_used"] == "260805_000000"


def test_recording_increments_context_once_per_prompt(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000", "260702_000000"])

    record_prompt_placeholders("<alpha> then <alpha> and <beta> write")
    first = read_store(sase_home_dir)
    assert first["version"] == 2
    assert first["prompt_count"] == 1
    by_text = {item["text"]: item for item in first["placeholders"]}
    assert by_text["alpha"]["count"] == 1
    assert by_text["alpha"]["context_uses"] == 1
    assert by_text["beta"]["count"] == 1
    assert "<beta>" in by_text["alpha"]["context"]
    assert by_text["alpha"]["context"]["<beta>"] == 1
    assert "<alpha>" not in by_text["alpha"]["context"]
    assert "<alpha>" in by_text["beta"]["context"]
    assert "<beta>" not in by_text["beta"]["context"]
    assert first["context_frequency"]["<alpha>"] == 1
    assert first["context_frequency"]["<beta>"] == 1

    record_prompt_placeholders("<alpha> then <alpha> and <beta> write")
    second = read_store(sase_home_dir)
    assert second["prompt_count"] == 2
    by_text = {item["text"]: item for item in second["placeholders"]}
    assert by_text["alpha"]["count"] == 2
    assert by_text["alpha"]["context_uses"] == 2
    assert by_text["alpha"]["context"]["<beta>"] == 2
    assert second["context_frequency"]["<alpha>"] == 2


def test_literal_zone_tag_is_context_but_not_a_saved_entry(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    record_prompt_placeholders("see `<alpha>` and <beta>")

    assert load_common_placeholders(10) == ["beta"]
    beta = read_store(sase_home_dir)["placeholders"][0]
    assert "<alpha>" in beta["context"]
    assert "<beta>" not in beta["context"]


def test_prompt_context_tokens_keep_tags_and_drop_stopwords() -> None:
    tokens = _prompt_context_tokens(
        "write the plan <phase title> rareword",
        context_frequency={
            "write": 10,
            "plan": 10,
            "rareword": 1,
            "<phase title>": 10,
        },
        prompt_count=10,
    )
    assert tokens[0] == "<phase title>"
    assert "write" not in tokens
    assert "plan" not in tokens
    assert "rareword" in tokens
    assert 10 / 10 > CONTEXT_STOPWORD_RATIO


def test_prompt_context_tokens_prefer_tags_when_the_prompt_is_capped() -> None:
    words = " ".join(f"word{index:02d}xx" for index in range(30))
    tokens = _prompt_context_tokens(
        f"<alpha> <beta> {words}",
        context_frequency={},
        prompt_count=0,
    )
    assert tokens[:2] == ("<alpha>", "<beta>")
    assert len(tokens) == CONTEXT_TOKENS_PER_PROMPT
    assert "<alpha>" in tokens
    assert "<beta>" in tokens


def test_prompt_context_tokens_are_deterministic() -> None:
    first = _prompt_context_tokens(
        "write the <phase title> plan",
        context_frequency={"write": 2, "phase": 1},
        prompt_count=4,
    )
    second = _prompt_context_tokens(
        "write the <phase title> plan",
        context_frequency={"write": 2, "phase": 1},
        prompt_count=4,
    )
    assert first == second


def test_entry_and_vocabulary_trims_are_deterministic(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(store, "CONTEXT_TOKENS_PER_ENTRY", 2)
    monkeypatch.setattr(store, "CONTEXT_VOCABULARY_LIMIT", 2)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    monkeypatch.setattr(
        store,
        "_prompt_context_tokens",
        lambda _text, **_kwargs: ("<zebra>", "<mango>", "<apple>"),
    )

    with caplog.at_level(logging.DEBUG, logger=store.log.name):
        record_prompt_placeholders("<alpha>")

    saved = read_store(sase_home_dir)
    assert saved["placeholders"][0]["context"] == {"<apple>": 1, "<mango>": 1}
    assert saved["context_frequency"] == {"<apple>": 1, "<mango>": 1}
    assert "trimmed placeholder context bag" in caplog.text
    assert "trimmed placeholder context vocabulary" in caplog.text


def test_entry_trim_keeps_highest_count_then_smallest_token(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "CONTEXT_TOKENS_PER_ENTRY", 2)
    monkeypatch.setattr(store, "CONTEXT_VOCABULARY_LIMIT", 50)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    tokens = iter(
        [
            ("<zebra>", "<apple>"),
            ("<zebra>", "<mango>"),
        ]
    )
    monkeypatch.setattr(
        store,
        "_prompt_context_tokens",
        lambda _text, **_kwargs: next(tokens),
    )

    record_prompt_placeholders("<alpha>")
    record_prompt_placeholders("<alpha>")

    assert read_store(sase_home_dir)["placeholders"][0]["context"] == {
        "<zebra>": 2,
        "<apple>": 1,
    }


def test_lru_eviction_drops_the_bag_and_keeps_corpus_statistics(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_limit(monkeypatch, 2)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<stale> uniqueaaaa")
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<older>")
    freeze_timestamps(monkeypatch, ["260703_000000"])
    record_prompt_placeholders("<fresh>")

    data = read_store(sase_home_dir)
    assert [item["text"] for item in data["placeholders"]] == ["fresh", "older"]
    assert data["prompt_count"] == 3
    assert "uniqueaaaa" in data["context_frequency"]
    assert "<stale>" in data["context_frequency"]


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
