"""App-handler tests for updating pinned prompt-stash rows."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
    PromptBarStashMixin,
)
from sase.ace.tui.modals.update_pinned_stash_modal import UpdatePinnedStashModal
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_update_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    for name in ("append_prompt_stash", "rewrite_prompt_stash"):
        if not hasattr(rust_module, name):
            pytest.skip(f"sase_core_rs is too old (no {name} binding).")


async def _wait_prompt_stash_tasks(harness: object) -> None:
    while tasks := list(getattr(harness, "_prompt_stash_async_tasks", set())):
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)


class _UpdateHarness(PromptBarStashMixin):
    """Drive pinned-stash update handlers without a live Textual DOM."""

    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.applied_counts: list[int] = []
        self.applied_pinned_counts: list[int] = []
        self.unmount_after_submit_calls = 0

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_after_submit_calls += 1

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        self.applied_counts.append(count)
        self.applied_pinned_counts.append(pinned_count)


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


type _SeedRow = tuple[str, str, str, str, bool]


def _seed(path: Path, rows: list[_SeedRow]) -> None:
    from sase.core.prompt_stash_facade import (
        PromptStashEntryWire,
        append_prompt_stash,
    )

    for idx, (entry_id, created_at, text, frontmatter, pinned) in enumerate(rows):
        append_prompt_stash(
            path,
            PromptStashEntryWire(
                id=entry_id,
                created_at=created_at,
                text=text,
                frontmatter=frontmatter,
                project=f"proj-{entry_id}",
                source="seed",
                pane_index=idx,
                pinned=pinned,
            ),
        )


def _panes() -> list[StashedPromptPane]:
    return [
        StashedPromptPane(text="updated first", frontmatter="model: c", pane_index=0),
        StashedPromptPane(text="updated second", frontmatter="model: c", pane_index=1),
    ]


async def test_empty_update_request_toasts_noop() -> None:
    harness = _UpdateHarness()

    await harness.on_prompt_input_bar_update_pinned_requested(
        PromptInputBar.UpdatePinnedRequested([])
    )

    assert harness.notifications == [("Nothing to save", "warning")]
    assert harness.pushed == []
    assert harness.applied_counts == []


async def test_zero_pinned_toasts_warning_without_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_update_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "", False)])
    harness = _UpdateHarness()

    await harness.on_prompt_input_bar_update_pinned_requested(
        PromptInputBar.UpdatePinnedRequested(_panes())
    )
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert harness.applied_counts == []
    assert harness.notifications == [
        (
            "No pinned prompt stash to update — pin one with space in the "
            "stash picker (Ctrl+G p)",
            "warning",
        )
    ]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries[0].text == "alpha"


async def test_single_pinned_updates_in_place_without_dismissing_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_update_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("pin", "2026-06-16T10:00:00", "old", "old: fm", True),
            ("keep", "2026-06-16T11:00:00", "keep", "", False),
        ],
    )
    harness = _UpdateHarness()

    await harness.on_prompt_input_bar_update_pinned_requested(
        PromptInputBar.UpdatePinnedRequested(_panes())
    )
    await _wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    entries = {entry.id: entry for entry in read_prompt_stash_snapshot(path).entries}
    updated = entries["pin"]
    assert updated.text == "updated first\n---\nupdated second"
    assert updated.frontmatter == "model: c"
    assert updated.created_at == "2026-06-16T10:00:00"
    assert updated.project == "proj-pin"
    assert updated.source == "seed"
    assert updated.pane_index == 0
    assert updated.pinned is True
    assert entries["keep"].text == "keep"
    assert harness.notifications == [('Updated pinned prompt 📌 "updated first"', None)]
    assert harness.applied_counts == [2]
    assert harness.applied_pinned_counts == [1]
    assert harness.unmount_after_submit_calls == 0


async def test_multiple_pinned_pushes_picker_and_updates_chosen_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_update_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "", True),
            ("b", "2026-06-16T11:00:00", "beta", "", True),
        ],
    )
    harness = _UpdateHarness()

    await harness.on_prompt_input_bar_update_pinned_requested(
        PromptInputBar.UpdatePinnedRequested(_panes())
    )
    await _wait_prompt_stash_tasks(harness)

    assert len(harness.pushed) == 1
    modal, callback = harness.pushed[0]
    assert isinstance(modal, UpdatePinnedStashModal)
    assert [entry.id for entry in modal._entries] == ["b", "a"]

    assert callable(callback)
    callback("a")
    await _wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    entries = {entry.id: entry for entry in read_prompt_stash_snapshot(path).entries}
    assert entries["a"].text == "updated first\n---\nupdated second"
    assert entries["b"].text == "beta"
    assert harness.notifications == [('Updated pinned prompt 📌 "updated first"', None)]


async def test_cancelled_picker_does_not_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_update_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "", True),
            ("b", "2026-06-16T11:00:00", "beta", "", True),
        ],
    )
    harness = _UpdateHarness()

    await harness._update_pinned_stash(_panes())
    _modal, callback = harness.pushed[0]
    assert callable(callback)
    callback(None)
    await _wait_prompt_stash_tasks(harness)

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [entry.text for entry in read_prompt_stash_snapshot(path).entries] == [
        "alpha",
        "beta",
    ]
    assert harness.notifications == []
    assert harness.applied_counts == []


async def test_update_write_error_toasts_without_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_update_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("pin", "2026-06-16T10:00:00", "old", "", True)])

    def _boom(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("disk full")

    monkeypatch.setattr("sase.core.prompt_stash_facade.rewrite_prompt_stash", _boom)
    harness = _UpdateHarness()

    await harness.on_prompt_input_bar_update_pinned_requested(
        PromptInputBar.UpdatePinnedRequested(_panes())
    )
    await _wait_prompt_stash_tasks(harness)

    assert harness.applied_counts == []
    assert len(harness.notifications) == 1
    message, severity = harness.notifications[0]
    assert severity == "error"
    assert "Failed to update pinned prompt: disk full" == message
