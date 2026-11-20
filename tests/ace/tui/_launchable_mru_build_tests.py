"""Tests for launchable MRU snapshot data building."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.launchable_mru import build_launchable_mru_data
from sase.history.vcs_macro_mru import load_launchable_vcs_macro_mru
from tests.ace.tui._launchable_mru_test_helpers import seed_mru


def test_snapshot_ring_matches_loader_displays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot ring equals the loader's displays across prune classes."""
    mru_file = seed_mru(
        tmp_path,
        monkeypatch,
        ["#git:foo", "#git:home", "#git:bar", "#git:gone-proj", "#gh:stale-patch"],
    )
    before = mru_file.read_bytes()
    built = build_launchable_mru_data(force=True)
    assert built is not None
    _signature, pairs, _token = built
    assert [display for _, display in pairs] == load_launchable_vcs_macro_mru(
        prune=False
    )
    # The build never writes: key paths must not prune the MRU file.
    assert mru_file.read_bytes() == before


def test_worker_fast_path_skips_unchanged_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching signature publishes nothing unless forced."""
    seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    first = build_launchable_mru_data(force=True)
    assert first is not None
    signature, _pairs, _token = first
    assert build_launchable_mru_data(force=False, last_signature=signature) is None
    assert build_launchable_mru_data(force=True, last_signature=signature) is not None


def test_build_failure_raises_for_error_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader failure raises so the caller publishes ``error``, not stale data."""
    seed_mru(tmp_path, monkeypatch, ["#git:foo"])
    with patch(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            build_launchable_mru_data(force=True)
