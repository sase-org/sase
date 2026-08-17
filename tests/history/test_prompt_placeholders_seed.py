"""Tests for seeding the placeholder store from prompt history shards."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    load_common_placeholder_index,
    load_common_placeholders,
    record_prompt_placeholders,
    seed_common_placeholders_from_history,
)
from sase.history.prompt_store import PromptEntry, save_shard
from tests.history._prompt_placeholders_helpers import (
    core_entries,
    entry,
    freeze_timestamps,
    make_sase_home,
    read_store,
    version_1_store,
    write_store,
)


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the placeholder limit to 100."""
    return make_sase_home(tmp_path, monkeypatch)


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
