"""App-handler tests for opening prompt-stash restore flows.

Pin the app glue that opens the unified picker for prompt-local restores, while
the global ``@`` action auto-restores a lone stash entry and otherwise shares
the same picker transport.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals.prompts_modal import PromptsModal, PromptsTab
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_stash_restore_helpers import (
    _FakeBar,
    _RestoreHarness,
    _point_store_at,
    _restore_pairs,
    _seed,
    _skip_without_lifecycle_bindings,
    _skip_without_pinned_binding,
    _wait_prompt_stash_tasks,
)


# --- open / guards ---------------------------------------------------------


async def test_feedback_mode_is_noop_with_toast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    await harness._open_prompt_stash_panel(bar_mode="feedback")

    assert harness.pushed == []
    assert harness.notifications == [
        ("Restore is only available for agent prompts", "warning")
    ]


async def test_empty_store_opens_overlay_on_stash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty Stash still opens the overlay (empty state points at Trash)."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    await harness._open_prompt_stash_panel()

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert modal._active_tab is PromptsTab.STASH
    assert harness.notifications == []


async def test_open_pushes_modal_with_snapshot_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    harness = _RestoreHarness()

    await harness._open_prompt_stash_panel()

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert modal._active_tab is PromptsTab.STASH
    # Newest first.
    assert [e.id for e in modal._stash_pane._entries] == ["b", "a"]


async def test_action_restore_prompt_stash_opens_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The global ``@`` action opens the overlay for multiple entries."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    harness = _RestoreHarness()

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert [e.id for e in modal._stash_pane._entries] == ["b", "a"]


async def test_action_open_prompt_stash_single_entry_opens_without_restoring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Leader panel action keeps a lone entry available for inspection."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_open_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert [e.id for e in modal._stash_pane._entries] == ["a"]
    assert bar.restored is None
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["a"]
    assert harness.applied_counts == []


# --- global action single-entry shortcuts ---------------------------------


async def test_action_restore_prompt_stash_single_unpinned_restores_and_pops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone unpinned stash entry restores directly and is removed."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert _restore_pairs(bar) == [("alpha", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.applied_counts == [0]
    assert harness.notifications == [("Restored prompt", None)]


async def test_action_restore_prompt_stash_single_pinned_restores_and_keeps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone pinned stash entry restores directly and stays stashed."""
    _skip_without_lifecycle_bindings()
    _skip_without_pinned_binding()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c", True)])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert _restore_pairs(bar) == [("alpha", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [(entry.id, entry.pinned) for entry in remaining] == [("a", True)]
    assert harness.applied_counts == []
    assert harness.notifications == [("Restored prompt", None)]


async def test_action_restore_prompt_stash_single_unpinned_mounts_home_and_pops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone unpinned stash entry restores into a new home prompt bar."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    harness = _RestoreHarness(bar=None)

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert harness.home_mounts == ["alpha"]
    assert harness.home_mount_macro_markdown == [True]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.applied_counts == [0]
    assert harness.notifications == [("Restored prompt", None)]


async def test_action_restore_prompt_stash_single_bundle_restores_panes_and_pops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone bundle row counts as one stash entry and restores all panes."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "model: c")],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert _restore_pairs(bar) == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.applied_counts == [0]
    assert harness.notifications == [("Restored 2 prompts", None)]


async def test_action_restore_prompt_stash_empty_store_toasts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The global ``@`` action opens the overlay even when fully empty."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert modal._active_tab is PromptsTab.STASH


# --- prompt-local restore events ------------------------------------------


async def test_restore_requested_single_entry_still_opens_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prompt-local ``Ctrl+G p`` stays the panel path for a single entry."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.on_prompt_input_bar_restore_requested(
        PromptInputBar.RestoreRequested("prompt")
    )
    await _wait_prompt_stash_tasks(harness)

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert [e.id for e in modal._stash_pane._entries] == ["a"]
    assert bar.restored is None
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["a"]
    assert harness.applied_counts == []


async def test_restore_requested_event_routes_through_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    # A non-prompt bar mode is guarded before any store read.
    await harness.on_prompt_input_bar_restore_requested(
        PromptInputBar.RestoreRequested("approve_prompt")
    )
    await _wait_prompt_stash_tasks(harness)
    assert harness.pushed == []
    assert harness.notifications[-1][1] == "warning"


async def test_non_restore_event_ignored() -> None:
    harness = _RestoreHarness()
    await harness.on_prompt_input_bar_restore_requested(PromptInputBar.Submitted("x"))
    await _wait_prompt_stash_tasks(harness)
    assert harness.notifications == []
    assert harness.pushed == []


# --- @@ race guard ----------------------------------------------------------


async def _wait_for_read_started(read_calls: list[int]) -> None:
    import asyncio

    for _ in range(100):
        if read_calls:
            return
        await asyncio.sleep(0.02)  # sase-test-wait: let the read reach the gate
    raise AssertionError("snapshot read never started")


async def test_double_at_restores_newest_once_without_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two fast `@` presses pop the newest draft exactly once, no overlay."""
    import asyncio
    import threading

    from tests.ace.tui.actions._prompt_stash_restore_helpers import (
        _point_store_at,
        _restore_pairs,
        _seed,
        _skip_without_lifecycle_bindings,
        _wait_prompt_stash_tasks,
        _FakeBar,
        _RestoreHarness,
    )

    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    gate = threading.Event()
    read_calls: list[int] = []
    orig = harness._read_prompt_stash_overlay_snapshot

    def _blocking_read():  # type: ignore[no-untyped-def]
        read_calls.append(1)
        assert gate.wait(timeout=10)
        return orig()

    monkeypatch.setattr(harness, "_read_prompt_stash_overlay_snapshot", _blocking_read)

    await harness.action_restore_prompt_stash()
    await _wait_for_read_started(read_calls)
    # Second `@` while the open is in flight: no new task, pending set.
    await harness.action_restore_prompt_stash()
    assert getattr(harness, "_prompts_stash_pop_newest_pending", False) is True
    gate.set()
    await _wait_prompt_stash_tasks(harness)

    assert len(read_calls) == 1
    assert harness.pushed == []
    assert _restore_pairs(bar) == [("beta", "")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["a"]


async def test_double_at_single_entry_restores_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`@@` with one draft restores once (second press absorbed)."""
    import asyncio
    import threading

    from tests.ace.tui.actions._prompt_stash_restore_helpers import (
        _point_store_at,
        _restore_pairs,
        _seed,
        _skip_without_lifecycle_bindings,
        _wait_prompt_stash_tasks,
        _FakeBar,
        _RestoreHarness,
    )

    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    gate = threading.Event()
    read_calls: list[int] = []
    orig = harness._read_prompt_stash_overlay_snapshot

    def _blocking_read():  # type: ignore[no-untyped-def]
        read_calls.append(1)
        assert gate.wait(timeout=10)
        return orig()

    monkeypatch.setattr(harness, "_read_prompt_stash_overlay_snapshot", _blocking_read)

    await harness.action_restore_prompt_stash()
    await _wait_for_read_started(read_calls)
    await harness.action_restore_prompt_stash()
    gate.set()
    await _wait_prompt_stash_tasks(harness)

    assert len(read_calls) == 1
    assert harness.pushed == []
    assert _restore_pairs(bar) == [("alpha", "")]


async def test_failed_read_clears_flags_next_opens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed snapshot read clears flags so the next `@` opens normally."""
    from tests.ace.tui.actions._prompt_stash_restore_helpers import (
        _point_store_at,
        _seed,
        _skip_without_lifecycle_bindings,
        _wait_prompt_stash_tasks,
        _RestoreHarness,
    )

    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    harness = _RestoreHarness()

    def _failing_read():  # type: ignore[no-untyped-def]
        raise OSError("disk gone")

    with monkeypatch.context() as scoped:
        scoped.setattr(harness, "_read_prompt_stash_overlay_snapshot", _failing_read)
        await harness.action_restore_prompt_stash()
        await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert getattr(harness, "_prompts_stash_open_in_flight", False) is False
    assert getattr(harness, "_prompts_stash_pop_newest_pending", False) is False

    # Next `@` opens normally (overlay pushed). The tmp store redirect stays
    # active: the scoped context above reverted only the failing-read patch,
    # so the read cannot fall back to the account's real prompt stash.
    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)
    assert len(harness.pushed) == 1

    from sase.core import paths as _paths

    assert _paths.prompt_stash_path() == path
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert {entry.id for entry in read_prompt_stash_snapshot(path).entries} == {
        "a",
        "b",
    }


async def test_single_at_pushes_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A single `@` with several drafts still pushes the overlay."""
    from tests.ace.tui.actions._prompt_stash_restore_helpers import (
        _point_store_at,
        _seed,
        _skip_without_lifecycle_bindings,
        _wait_prompt_stash_tasks,
        _RestoreHarness,
    )

    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    harness = _RestoreHarness()
    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)
    assert len(harness.pushed) == 1
