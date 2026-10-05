"""Entry-point rollout tests for the tabbed Prompts overlay.

Every Stash and History entry point must open the complete overlay on its
correct initial tab with a typed origin, and the full active → Trash →
active path must round-trip through the host dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.config import get_ace_prompt_stash_trash_limit
from sase.ace.tui.actions.agent_workflow._entry_prompt_history import (
    EntryPromptHistoryMixin,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_stash_restore import (
    PromptBarStashRestoreMixin,
)
from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsResult,
    PromptsTab,
)
from sase.ace.tui.modals.stash_pane import StashRestoreResult
from sase.ace.tui.modals.stash_pane import TrashRequested
from sase.ace.tui.modals.trash_pane import TrashRestoreRequested
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from ._prompt_stash_restore_helpers import (
    _FakeBar,
    _RestoreHarness,
    _point_store_at,
    _seed,
    _skip_without_prompt_stash_bindings,
    _wait_prompt_stash_tasks,
)

TRASHED_AT = "2026-09-26T14:00:00+00:00"


def _skip_without_lifecycle_bindings() -> None:
    _skip_without_prompt_stash_bindings()
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    for name in (
        "read_prompt_stash_lifecycle",
        "trash_prompt_stash",
        "restore_prompt_stash",
        "purge_prompt_stash",
    ):
        if not hasattr(rust_module, name):
            pytest.skip(f"sase_core_rs is too old (no {name} binding).")


def _overlay(harness: _RestoreHarness) -> tuple[PromptsModal, object]:
    assert len(harness.pushed) == 1
    modal, callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    return modal, callback


def _seed_trash(path: Path, entry_id: str) -> None:
    from sase.core.prompt_stash_facade import trash_prompt_stash

    outcome = trash_prompt_stash(path, [entry_id], 20, TRASHED_AT)
    assert [record.entry.id for record in outcome.snapshot.trash] == [entry_id]


# -- entry points open the overlay on the correct tab ------------------------


async def test_restore_requested_opens_overlay_on_stash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prompt-local ``Ctrl+G p`` opens the overlay on Stash."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness.on_prompt_input_bar_restore_requested(
        PromptInputBar.RestoreRequested("prompt")
    )
    await _wait_prompt_stash_tasks(harness)

    modal, _callback = _overlay(harness)
    assert modal._active_tab is PromptsTab.STASH
    assert modal._origin.kind == "live_bar"


async def test_open_action_opens_overlay_on_stash_with_trash_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`,@` opens Stash with the Trash count visible in the tab strip."""
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
    _seed_trash(path, "a")
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness.action_open_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    modal, _callback = _overlay(harness)
    assert modal._active_tab is PromptsTab.STASH
    assert [e.id for e in modal._stash_pane._entries] == ["b"]
    assert [r.entry.id for r in modal._trash_records] == ["a"]
    assert modal._trash_limit == get_ace_prompt_stash_trash_limit()


async def test_live_bar_history_opens_overlay_on_history_with_seed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``Ctrl+K`` opens the overlay on History with the live-bar origin."""
    _skip_without_lifecycle_bindings()
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    from tests.ace.tui.test_prompt_bar_history_requests import (
        _HistoryRequestHarness,
        _open_history,
    )

    harness = _HistoryRequestHarness()
    event = PromptInputBar.HistoryRequested(
        preserve_prompt_bar=True,
        prompt_seed="#gh:sase fix parser",
    )

    modal, _overlay_cb = await _open_history(harness, event)

    assert modal._active_tab is PromptsTab.HISTORY
    assert modal._origin.kind == "live_bar"
    assert modal._origin.prompt_seed == "#gh:sase fix parser"


class _EntryHarness(EntryPromptHistoryMixin, PromptBarStashRestoreMixin):
    """Drive the home/MRU history entry without a live Textual DOM."""

    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.applied_counts: list[int] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _mounted_prompt_bar(self):  # type: ignore[override]
        return None

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        self.applied_counts.append(count)


async def test_mru_history_opens_overlay_on_history_with_home_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`,.` opens the overlay on History with the home/MRU origin."""
    _skip_without_lifecycle_bindings()
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        lambda *a, **k: [("canon", "display")],
    )
    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.mru_prefix_project_name",
        lambda prefix: prefix,
    )
    harness = _EntryHarness()

    harness._start_prompt_history_from_last_selection()
    await _wait_prompt_stash_tasks(harness)

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert modal._active_tab is PromptsTab.HISTORY
    assert modal._origin.kind == "home_mru"


# -- full active → Trash → active round trip ---------------------------------


async def test_stash_dismiss_with_trash_marks_moves_without_confirm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Stash-tab dismiss with discards moves them to Trash with no dialog."""
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
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._apply_prompts_stash_result(StashRestoreResult(trash_ids=["a"]))

    # No confirmation dialog is pushed and no confirm callback is invoked.
    assert harness.pushed == []
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["b"]
    assert [r.entry.id for r in lifecycle.trash] == ["a"]
    assert any("Trash" in msg for msg, _sev in harness.notifications)


async def test_trash_requested_in_place_moves_without_confirm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partial discard moves the staged row to Trash with no dialog."""
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
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    harness.on_stashed_prompts_modal_trash_requested(TrashRequested(["a"]))
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["b"]
    assert [r.entry.id for r in lifecycle.trash] == ["a"]
    assert any("Trash" in msg for msg, _sev in harness.notifications)


async def test_stash_dismiss_moves_pinned_without_confirm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pinned discard moves to Trash with no dialog and stays pinned."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "", True),
            ("b", "2026-06-16T11:00:00", "beta", ""),
        ],
    )
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._apply_prompts_stash_result(StashRestoreResult(trash_ids=["a"]))

    assert harness.pushed == []
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["b"]
    assert [r.entry.id for r in lifecycle.trash] == ["a"]
    assert lifecycle.trash[0].entry.pinned is True


async def test_stash_dismiss_evicting_batch_moves_without_confirm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An overflowing discard batch moves with no dialog; toast names evictions."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    monkeypatch.setattr("sase.ace.config.get_ace_prompt_stash_trash_limit", lambda: 1)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
            ("b", "2026-06-16T11:00:00", "beta", ""),
            ("old", "2026-06-16T09:00:00", "older", ""),
        ],
    )
    _seed_trash(path, "old")

    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._apply_prompts_stash_result(StashRestoreResult(trash_ids=["a", "b"]))

    assert harness.pushed == []
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert lifecycle.active == []
    # The over-limit batch evicts the oldest rows first, including one of the
    # newly trashed rows; only the newest survives in Trash.
    assert [r.entry.id for r in lifecycle.trash] == ["b"]
    toast = harness.notifications[-1][0]
    assert "Moved 1 draft to Trash" in toast
    assert "permanently deleted 2 oldest drafts" in toast
    assert "sase prompt stash-archive" in toast


async def test_stash_dismiss_stale_trash_id_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale trash id is a no-op: no write and no move toast."""
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", ""),
        ],
    )
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._apply_prompts_stash_result(StashRestoreResult(trash_ids=["ghost"]))

    assert harness.pushed == []
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["a"]
    assert lifecycle.trash == []
    assert not any(msg.startswith("Moved") for msg, _sev in harness.notifications)


async def test_stash_dismiss_empty_trash_preflight_keeps_mixed_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty trash preflight must not skip a mixed dismiss's pop ids."""
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

    await harness._apply_prompts_stash_result(
        StashRestoreResult(pop_ids=["b"], trash_ids=["ghost"])
    )

    assert harness.pushed == []
    assert bar.restored is not None
    assert [(pane.text, pane.frontmatter) for pane in bar.restored] == [("beta", "")]
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["a"]
    assert lifecycle.trash == []


async def test_stash_dismiss_trash_read_failure_toasts_and_skips_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A snapshot read failure toasts the read error and writes nothing."""
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
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    def _boom() -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(harness, "_read_prompt_stash_overlay_snapshot", _boom)

    await harness._apply_prompts_stash_result(StashRestoreResult(trash_ids=["a"]))

    assert harness.pushed == []
    assert any(
        msg.startswith("Failed to read stashed prompts") and sev == "error"
        for msg, sev in harness.notifications
    )
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["a", "b"]
    assert lifecycle.trash == []


async def test_trash_restore_request_moves_back_to_stash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Trash restores land back in Stash; the overlay stays open."""
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
    _seed_trash(path, "a")
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness.action_open_prompt_stash()
    await _wait_prompt_stash_tasks(harness)
    modal, _callback = _overlay(harness)

    harness.on_trash_pane_trash_restore_requested(TrashRestoreRequested(["a"]))
    await _wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    lifecycle = read_prompt_stash_lifecycle(path)
    assert {e.id for e in lifecycle.active} == {"a", "b"}
    assert lifecycle.trash == []
    # Authoritative repaint: the tracked overlay follows the store outcome.
    assert modal._stash_count == 2
    assert harness.notifications[-1][0] == "Restored 1 draft to Stash"


async def test_overlay_result_dispatch_is_tab_typed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A History-tab outcome never triggers a Stash restore."""
    _skip_without_lifecycle_bindings()
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    from tests.ace.tui.test_prompt_bar_history_requests import (
        _HistoryRequestHarness,
        _history_outcome,
        _open_history,
    )
    from sase.ace.tui.modals import PromptHistoryAction

    harness = _HistoryRequestHarness()
    event = PromptInputBar.HistoryRequested(preserve_prompt_bar=True)
    _modal, overlay_cb = await _open_history(harness, event)

    overlay_cb(_history_outcome(PromptHistoryAction.LOAD, "loaded body"))  # type: ignore[operator]

    assert harness.bar.load_calls == [(harness.text_area, "", "loaded body")]
    assert harness.notifications == []
