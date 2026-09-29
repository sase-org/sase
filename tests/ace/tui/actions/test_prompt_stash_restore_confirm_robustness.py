"""Tests for prompt-stash restore fidelity and failure recovery.

Covers cursor propagation into restored panes, in-place deletes while the
picker stays open, and restore-capture hardening (load from the pop outcome,
keep-read failures, load-failure rollback, and background-task reporting).
Basic pop / keep / delete confirms, the pin toggle, and keep-only confirms
live in `test_prompt_stash_restore_confirm_apply.py`. The original
`test_prompt_stash_restore_confirm.py` module remains as a facade that lazily
re-exports every test here under its historic import path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)

from ._prompt_stash_restore_helpers import (
    FakeBar,
    RestoreHarness,
    point_store_at,
    restore_pairs,
    seed_prompt_stash,
    skip_without_prompt_stash_bindings,
    wait_prompt_stash_tasks,
)


async def test_confirm_restores_bundle_cursor_on_middle_pane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    from sase.core.prompt_stash_facade import (
        PromptStashCursorWire,
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="bundle",
            created_at="2026-06-16T10:00:00",
            text="alpha\n---\nbeta\n---\ngamma",
            frontmatter="model: c",
            cursor=PromptStashCursorWire(pane_index=1, row=0, column=2),
        ),
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["bundle"])
    )
    await wait_prompt_stash_tasks(harness)

    assert bar.restored is not None
    assert [pane.text for pane in bar.restored] == ["alpha", "beta", "gamma"]
    assert [pane.is_focus_target for pane in bar.restored] == [False, True, False]
    assert bar.restored[1].cursor == (0, 2)


async def test_confirm_final_row_cursor_wins_over_earlier_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    from sase.core.prompt_stash_facade import (
        PromptStashCursorWire,
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="a",
            created_at="2026-06-16T10:00:00",
            text="first",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=1),
        ),
    )
    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="b",
            created_at="2026-06-16T11:00:00",
            text="second",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=4),
        ),
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"])
    )
    await wait_prompt_stash_tasks(harness)

    assert bar.restored is not None
    assert [pane.is_focus_target for pane in bar.restored] == [False, True]
    assert bar.restored[1].cursor == (0, 4)


async def test_confirm_without_bar_passes_final_row_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    from sase.core.prompt_stash_facade import (
        PromptStashCursorWire,
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="a",
            created_at="2026-06-16T10:00:00",
            text="first",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=1),
        ),
    )
    append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="b",
            created_at="2026-06-16T11:00:00",
            text="alpha\n---\nbeta",
            cursor=PromptStashCursorWire(pane_index=0, row=0, column=2),
        ),
    )
    harness = RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"])
    )
    await wait_prompt_stash_tasks(harness)

    assert harness.home_mounts == ["first\n---\nalpha\n---\nbeta"]
    assert harness.home_mount_selected_panes == [1]
    assert harness.home_mount_cursors == [(0, 2)]


async def test_confirm_without_bar_legacy_row_uses_end_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(path, [("a", "2026-06-16T10:00:00", "solo", "")])
    harness = RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(StashRestoreResult(pop_ids=["a"]))
    await wait_prompt_stash_tasks(harness)

    assert harness.home_mounts == ["solo"]
    assert harness.home_mount_selected_panes == [None]
    assert harness.home_mount_cursors == [None]


# --- in-place delete while the picker stays open ---------------------------


async def test_delete_requested_removes_one_and_refreshes_badge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    harness.on_stashed_prompts_modal_delete_requested(
        StashedPromptsModal.DeleteRequested(["a"])
    )
    await wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["b"]
    assert bar.restored is None  # nothing loaded
    assert harness.home_mounts == []
    assert harness.notifications == [
        (
            "Deleted stashed prompt. Drafts stay recoverable with "
            "`sase prompt stash-archive`.",
            None,
        )
    ]
    assert harness.applied_counts == [1]


async def test_delete_requested_two_ids_plural_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
            ("c", "2026-06-16T12:00:00", "gamma", ""),
        ],
    )
    harness = RestoreHarness(bar=FakeBar(mode="prompt"))

    harness.on_stashed_prompts_modal_delete_requested(
        StashedPromptsModal.DeleteRequested(["a", "b"])
    )
    await wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["c"]
    assert harness.notifications == [
        (
            "Deleted 2 stashed prompts. Drafts stay recoverable with "
            "`sase prompt stash-archive`.",
            None,
        )
    ]
    assert harness.applied_counts == [1]


async def test_delete_requested_ignores_other_events() -> None:
    harness = RestoreHarness(bar=FakeBar(mode="prompt"))
    harness.on_stashed_prompts_modal_delete_requested(object())
    await wait_prompt_stash_tasks(harness)
    assert harness.notifications == []
    assert harness.applied_counts == []


# --- restore-capture hardening (epic sase-1ca phase 4) ----------------------


async def test_confirm_pop_loads_from_pop_outcome_without_snapshot_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pop-only restores load from the pop outcome, never a snapshot read."""
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    def _boom() -> object:
        raise AssertionError("pop path must not read the snapshot")

    monkeypatch.setattr(harness, "_read_prompt_stash_entries_strict", _boom)

    await harness._apply_stash_restore(StashRestoreResult(pop_ids=["a"]))

    assert restore_pairs(bar) == [("alpha", "")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.notifications == [("Restored prompt", None)]
    assert harness.applied_counts == [0]


async def test_confirm_keep_read_failure_does_not_pop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing keep-ids snapshot read toasts and leaves the stash intact."""
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    def _failing_read() -> object:
        raise OSError("disk gone")

    monkeypatch.setattr(harness, "_read_prompt_stash_entries_strict", _failing_read)

    await harness._apply_stash_restore(
        StashRestoreResult(pop_ids=["a"], keep_ids=["b"])
    )

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["a", "b"]
    assert bar.restored is None
    assert harness.home_mounts == []
    assert harness.notifications == [("Failed to restore prompt: disk gone", "error")]
    assert harness.applied_counts == []


async def test_confirm_load_failure_rolls_row_back_into_stash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bar-load failure after a pop appends the row back with its id."""
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c")])
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    def _boom(_entries: object) -> None:
        raise RuntimeError("bar exploded")

    monkeypatch.setattr(harness, "_load_restored_entries", _boom)

    await harness._apply_stash_restore(StashRestoreResult(pop_ids=["a"]))

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    rolled_back = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in rolled_back] == ["a"]
    assert rolled_back[0].text == "alpha"
    assert bar.restored is None
    assert len(harness.notifications) == 1
    message, severity = harness.notifications[0]
    assert severity == "error"
    assert "put back in the stash" in message
    assert harness.applied_counts == [1]  # badge reflects the rolled-back row


async def test_confirm_load_and_rollback_failure_toasts_archive_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed rollback still leaves the popped row recoverable in the archive."""
    skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    point_store_at(monkeypatch, path)
    seed_prompt_stash(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c")])
    bar = FakeBar(mode="prompt")
    harness = RestoreHarness(bar=bar)

    def _boom_load(_entries: object) -> None:
        raise RuntimeError("bar exploded")

    def _boom_append(*args: object, **kwargs: object) -> object:
        raise RuntimeError("rollback exploded")

    monkeypatch.setattr(harness, "_load_restored_entries", _boom_load)
    monkeypatch.setattr(
        "sase.core.prompt_stash_facade.append_prompt_stash", _boom_append
    )

    await harness._apply_stash_restore(StashRestoreResult(pop_ids=["a"]))

    assert len(harness.notifications) == 1
    message, severity = harness.notifications[0]
    assert severity == "error"
    assert "sase prompt stash-archive" in message

    from sase.core.prompt_stash_facade import read_prompt_stash_archive

    archive = read_prompt_stash_archive(path)
    assert any(
        record.entry.id == "a" and record.reason == "popped"
        for record in archive.records
    )


async def test_spawned_task_exception_is_logged_and_toasted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unhandled stash-task failure is logged and toasted."""
    harness = RestoreHarness()

    async def _boom() -> None:
        raise RuntimeError("kablam")

    with caplog.at_level(logging.ERROR, logger="sase"):
        harness._spawn_prompt_stash_task(_boom())
        await asyncio.sleep(0.1)  # sase-test-wait: let failure callback run

    assert ("Prompt stash task failed: kablam", "error") in harness.notifications
    failures = [
        record
        for record in caplog.records
        if "Prompt stash background task failed" in record.message
    ]
    assert failures, "expected the stash-task failure to be logged"
    assert any(
        isinstance(record.exc_info, tuple)
        and isinstance(record.exc_info[1], RuntimeError)
        and "kablam" in str(record.exc_info[1])
        for record in failures
    )


async def test_spawned_task_cancelled_stays_silent() -> None:
    """Cancelled stash tasks surface neither a log nor a toast."""
    harness = RestoreHarness()

    async def _hang() -> None:
        await asyncio.sleep(30)  # sase-test-wait: simulate a hung task until cancelled

    harness._spawn_prompt_stash_task(_hang())
    pending = list(getattr(harness, "_prompt_stash_async_tasks", set()))
    assert len(pending) == 1
    pending[0].cancel()
    await asyncio.sleep(0.05)  # sase-test-wait: let task cancellation propagate

    assert harness.notifications == []
