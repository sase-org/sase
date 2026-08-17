"""Tests for the pre-argparse completion-candidates disk cache."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sase.completion.candidates.cache import (
    load_cached_candidates,
    store_cached_candidates,
)
from sase.completion.candidates.protocol import Candidate


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))


def test_cache_round_trips_stored_candidates() -> None:
    candidates = [Candidate("sase-1", "Fix the thing"), Candidate("sase-2")]

    store_cached_candidates("bead", candidates)

    assert load_cached_candidates("bead", source_mtime=None) == candidates


def test_cache_miss_when_absent() -> None:
    assert load_cached_candidates("bead", source_mtime=None) is None


def test_cache_miss_when_older_than_ttl() -> None:
    store_cached_candidates("bead", [Candidate("sase-1")])

    assert load_cached_candidates("bead", source_mtime=None, ttl_seconds=-1.0) is None


def test_cache_miss_when_source_newer_than_cache() -> None:
    store_cached_candidates("bead", [Candidate("sase-1")])

    future = time.time() + 60
    assert load_cached_candidates("bead", source_mtime=future) is None


def test_cache_hit_when_source_older_than_cache() -> None:
    candidates = [Candidate("sase-1")]
    store_cached_candidates("bead", candidates)

    past = time.time() - 3600
    assert load_cached_candidates("bead", source_mtime=past) == candidates


def test_no_cache_env_var_disables_store_and_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")

    store_cached_candidates("bead", [Candidate("sase-1")])

    assert load_cached_candidates("bead", source_mtime=None) is None


def test_store_is_atomic_and_leaves_no_tmp_files() -> None:
    from sase.core.paths import sase_subdir

    store_cached_candidates("bead", [Candidate("sase-1")])

    entries = list((sase_subdir("completion") / "cache").iterdir())
    assert [entry.name for entry in entries] == ["bead.tsv"]


def test_store_write_failure_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "blocked-home"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(blocked / "nested"))

    store_cached_candidates("bead", [Candidate("sase-1")])

    assert load_cached_candidates("bead", source_mtime=None) is None


def test_cache_key_isolates_different_kinds() -> None:
    store_cached_candidates("project", [Candidate("acme")])
    store_cached_candidates("bead", [Candidate("sase-1")])

    assert load_cached_candidates("project", source_mtime=None) == [Candidate("acme")]
    assert load_cached_candidates("bead", source_mtime=None) == [Candidate("sase-1")]


def test_load_ignores_unreadable_cache_directory_gracefully() -> None:
    # No cache written yet, and the parent dir does not exist -- must not raise.
    assert load_cached_candidates("never-written", source_mtime=None) is None
    assert os.environ.get("SASE_COMPLETION_NO_CACHE") is None
