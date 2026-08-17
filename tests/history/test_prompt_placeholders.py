"""Tests for recording, ordering, and limiting common placeholders."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    _common_placeholder_limit,
    load_common_placeholders,
    record_prompt_placeholders,
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
    set_limit,
    store_file,
)


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the placeholder limit to 100."""
    return make_sase_home(tmp_path, monkeypatch)


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
