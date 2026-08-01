"""Tests for the durable sticky-misspellings store."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

import sase.history.prompt_misspellings as store
from sase.history.prompt_misspellings import (
    allow_word,
    forget_misspelling,
    load_misspellings,
    misspellings_source_token,
    record_misspelling,
)
from tests.conftest import redirect_sase_home


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the remembered-words limit to 100."""
    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    set_limit(monkeypatch, 100)
    return home


def set_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    """Point ``_misspellings_limit`` at a fixed configured value."""
    monkeypatch.setattr(
        store,
        "load_merged_config",
        lambda: {"ace": {"prompt_spellcheck": {"max_remembered_words": limit}}},
    )


def store_file(home: Path) -> Path:
    return home / "prompt_misspellings.json"


def read_store(home: Path) -> dict[str, Any]:
    return json.loads(store_file(home).read_text(encoding="utf-8"))


def test_record_persists_a_new_misspelling(sase_home_dir: Path) -> None:
    assert record_misspelling("recieve") is True

    assert read_store(sase_home_dir) == {
        "version": 1,
        "misspelled": ["recieve"],
        "allowed": [],
    }
    assert load_misspellings().misspelled == ("recieve",)


def test_record_is_idempotent_for_the_same_word(sase_home_dir: Path) -> None:
    assert record_misspelling("recieve") is True
    assert record_misspelling("recieve") is False
    assert record_misspelling("Recieve") is False

    assert load_misspellings().misspelled == ("recieve",)


def test_record_no_ops_on_an_accepted_word(sase_home_dir: Path) -> None:
    record_misspelling("Bugyi")
    assert allow_word("Bugyi") is True

    assert record_misspelling("bugyi") is False

    assert load_misspellings().misspelled == ()
    assert load_misspellings().allowed == ("Bugyi",)


def test_allow_word_moves_it_out_of_misspelled(sase_home_dir: Path) -> None:
    record_misspelling("teh")

    assert allow_word("TEH") is True

    sets = load_misspellings()
    assert sets.misspelled == ()
    assert sets.allowed == ("TEH",)


def test_allow_word_on_an_unflagged_word_still_records_the_acceptance(
    sase_home_dir: Path,
) -> None:
    assert allow_word("sase") is True
    assert allow_word("sase") is False

    assert load_misspellings().allowed == ("sase",)


def test_forget_misspelling_removes_only_from_misspelled(sase_home_dir: Path) -> None:
    record_misspelling("recieve")
    record_misspelling("teh")

    assert forget_misspelling("RECIEVE") is True
    assert forget_misspelling("recieve") is False
    assert forget_misspelling("missing") is False

    sets = load_misspellings()
    assert sets.misspelled == ("teh",)
    assert sets.allowed == ()


def test_casefold_dedupe_keeps_first_seen_spelling(sase_home_dir: Path) -> None:
    record_misspelling("Recieve")
    record_misspelling("RECIEVE")
    record_misspelling("recieve")

    assert load_misspellings().misspelled == ("Recieve",)


def test_cap_trims_oldest_first_entry(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_limit(monkeypatch, 2)
    record_misspelling("alpha")
    record_misspelling("beta")
    record_misspelling("gamma")

    assert load_misspellings().misspelled == ("beta", "gamma")


def test_lowering_the_limit_prunes_on_the_next_write(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_misspelling("alpha")
    record_misspelling("beta")
    record_misspelling("gamma")
    assert len(load_misspellings().misspelled) == 3

    set_limit(monkeypatch, 1)
    record_misspelling("delta")

    assert load_misspellings().misspelled == ("delta",)


def test_zero_limit_records_nothing(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_limit(monkeypatch, 0)

    assert record_misspelling("alpha") is False
    assert not store_file(sase_home_dir).exists()


@pytest.mark.parametrize(
    "payload",
    [
        '{"version": 1, "misspell',
        "not json at all",
        '{"version": 2, "misspelled": ["alpha"], "allowed": []}',
        '{"version": 1, "misspelled": "alpha", "allowed": []}',
    ],
)
def test_unusable_store_loads_empty_and_is_replaced(
    sase_home_dir: Path,
    payload: str,
) -> None:
    store_file(sase_home_dir).write_text(payload, encoding="utf-8")

    assert load_misspellings().misspelled == ()
    assert load_misspellings().allowed == ()

    record_misspelling("alpha")

    assert read_store(sase_home_dir) == {
        "version": 1,
        "misspelled": ["alpha"],
        "allowed": [],
    }


def test_missing_store_loads_empty(sase_home_dir: Path) -> None:
    assert not store_file(sase_home_dir).exists()
    assert load_misspellings() == store._MisspellingSets(misspelled=(), allowed=())


def test_atomic_replace_leaves_no_temp_files(sase_home_dir: Path) -> None:
    record_misspelling("alpha")
    allow_word("beta")

    leftovers = [
        path for path in sase_home_dir.iterdir() if path.name.startswith(".prompt_")
    ]
    assert leftovers == []


def test_concurrent_locked_writes_do_not_lose_an_entry(sase_home_dir: Path) -> None:
    words = [f"word{i}" for i in range(20)]
    threads = [
        threading.Thread(target=record_misspelling, args=(word,)) for word in words
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(load_misspellings().misspelled) == sorted(words)


def test_source_token_tracks_the_store_file(sase_home_dir: Path) -> None:
    missing = misspellings_source_token()
    assert missing == (str(store_file(sase_home_dir)), -1, -1)

    record_misspelling("alpha")

    assert misspellings_source_token() != missing


def test_record_never_raises_on_write_failure(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_misspelled: object, _allowed: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_lists", _boom)

    assert record_misspelling("alpha") is False
    assert load_misspellings().misspelled == ()


def test_allow_and_forget_never_raise_on_write_failure(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed directly (bypassing ``_save_lists``) so ``forget_misspelling`` below
    # has an entry to remove and therefore actually reaches the write path.
    store_file(sase_home_dir).write_text(
        json.dumps({"version": 1, "misspelled": ["alpha"], "allowed": []}),
        encoding="utf-8",
    )

    def _boom(_misspelled: object, _allowed: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_lists", _boom)

    assert allow_word("beta") is False
    assert forget_misspelling("alpha") is False
