"""Tests for the durable deleted-history-word store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.history.prompt_word_deletions as store
from sase.history.prompt_word_deletions import (
    delete_prompt_word,
    load_deleted_prompt_words,
    prompt_word_deletions_source_token,
)
from tests.conftest import redirect_sase_home


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return redirect_sase_home(monkeypatch, tmp_path / ".sase")


def store_file(home: Path) -> Path:
    return home / "prompt_word_deletions.json"


def test_round_trip_is_idempotent_and_exact_case(sase_home_dir: Path) -> None:
    assert delete_prompt_word("Foo") is True
    assert delete_prompt_word("Foo") is False
    assert delete_prompt_word("foo") is True

    assert load_deleted_prompt_words() == {"Foo", "foo"}
    assert json.loads(store_file(sase_home_dir).read_text(encoding="utf-8")) == {
        "version": 1,
        "words": ["Foo", "foo"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not json",
        '{"version": 2, "words": ["alpha"]}',
        '{"version": 1, "words": "alpha"}',
    ],
)
def test_unusable_store_reads_empty(
    sase_home_dir: Path,
    payload: str | None,
) -> None:
    if payload is not None:
        store_file(sase_home_dir).write_text(payload, encoding="utf-8")

    assert load_deleted_prompt_words() == set()


def test_cap_evicts_the_oldest_words(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "_MAX_DELETED_WORDS", 3)

    for word in ("one", "two", "three", "four"):
        assert delete_prompt_word(word) is True

    assert json.loads(store_file(sase_home_dir).read_text(encoding="utf-8"))[
        "words"
    ] == ["two", "three", "four"]


def test_source_token_changes_after_a_write(sase_home_dir: Path) -> None:
    missing = prompt_word_deletions_source_token()
    assert missing == (str(store_file(sase_home_dir)), -1, -1)

    delete_prompt_word("alpha")

    assert prompt_word_deletions_source_token() != missing
