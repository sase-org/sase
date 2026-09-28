"""End-to-end: a TUI restore pop archives the row; the CLI recovers it."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.ace.tui.modals.stashed_prompts_modal import StashRestoreResult
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.prompt.cli_stash_archive import _handle_stash_archive_restore

from ._prompt_stash_restore_helpers import (
    _FakeBar,
    _RestoreHarness,
    _point_store_at,
    _seed,
    _skip_without_prompt_stash_bindings,
    _wait_prompt_stash_tasks,
)


def _skip_without_archive_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    for name in ("read_prompt_stash_archive", "recover_prompt_stash_archive"):
        if not hasattr(rust_module, name):
            pytest.skip(f"sase_core_rs is too old (no {name} binding).")


async def test_tui_restore_pop_then_cli_recovery_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_without_prompt_stash_bindings()
    _skip_without_archive_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    monkeypatch.setattr(
        "sase.prompt.cli_stash_archive.prompt_stash_path",
        lambda: path,
        raising=True,
    )
    _seed(path, [("a", "2026-06-16T10:00:00", "e2e draft", "")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    # The real TUI restore path: pop the row and load it into the bar.
    await harness._on_prompt_stash_restore_confirmed(StashRestoreResult(pop_ids=["a"]))
    await _wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert bar.restored is not None

    # The popped row is archived and recoverable through the CLI.
    code = _handle_stash_archive_restore(argparse.Namespace(ids=["a"]))
    assert code == 0
    assert "Restored a" in capsys.readouterr().out
    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["a"]
