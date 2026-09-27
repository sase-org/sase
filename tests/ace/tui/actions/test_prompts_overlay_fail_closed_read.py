"""Fail-closed lifecycle reads for the tabbed Prompts overlay.

The overlay snapshot read is authoritative: a missing lifecycle binding
(stale wheel), parse failure, or store read/lock error surfaces the actual
error and never opens a misleading overlay with empty Trash. The lifecycle
read is faked here so the failure paths run without Rust bindings; the
real-core happy path is covered by the entry-point and restore-open suites.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals.prompts_modal import PromptsOrigin, PromptsTab
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.core.prompt_stash_wire import (
    PROMPT_STASH_LIFECYCLE_WIRE_SCHEMA_VERSION,
    PromptStashEntryWire,
    PromptStashLifecycleSnapshotWire,
    PromptStashTrashRecordWire,
)

from ._prompt_stash_restore_helpers import (
    _FakeBar,
    _RestoreHarness,
    _point_store_at,
    _restore_pairs,
    _seed,
    _skip_without_prompt_stash_bindings,
    _wait_prompt_stash_tasks,
)


def _fail_lifecycle_with(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Make the lifecycle read raise *exc*, like a stale wheel or bad store."""
    from sase.core import prompt_stash_facade

    def _boom(path: object) -> PromptStashLifecycleSnapshotWire:
        raise exc

    monkeypatch.setattr(prompt_stash_facade, "read_prompt_stash_lifecycle", _boom)


def _fake_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: PromptStashLifecycleSnapshotWire,
) -> None:
    """Serve *snapshot* from the lifecycle read instead of the Rust store."""
    from sase.core import prompt_stash_facade

    def _serve(path: object) -> PromptStashLifecycleSnapshotWire:
        return snapshot

    monkeypatch.setattr(prompt_stash_facade, "read_prompt_stash_lifecycle", _serve)


def _snapshot(
    active: list[PromptStashEntryWire],
    trash: list[PromptStashTrashRecordWire],
) -> PromptStashLifecycleSnapshotWire:
    return PromptStashLifecycleSnapshotWire(
        schema_version=PROMPT_STASH_LIFECYCLE_WIRE_SCHEMA_VERSION,
        active=list(active),
        trash=list(trash),
    )


def _entry(entry_id: str, text: str = "alpha") -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=entry_id, created_at="2026-06-16T10:00:00", text=text
    )


# -- failure paths: no overlay, truthful error --------------------------------


async def test_stale_binding_surfaces_error_without_opening_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale wheel names its missing binding instead of showing empty Trash."""
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    _fail_lifecycle_with(
        monkeypatch,
        AttributeError(
            "sase_core_rs is importable but does not expose binding "
            "'read_prompt_stash_lifecycle'; the installed wheel is stale."
        ),
    )
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._open_prompt_stash_panel()

    assert harness.pushed == []  # no overlay, so no empty Trash pane
    assert len(harness.notifications) == 1
    message, severity = harness.notifications[0]
    assert severity == "error"
    assert "read_prompt_stash_lifecycle" in message


async def test_store_read_error_surfaces_without_opening_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A store read failure surfaces its cause instead of empty collections."""
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    _fail_lifecycle_with(monkeypatch, OSError("disk boom"))
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness.action_open_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert len(harness.notifications) == 1
    message, severity = harness.notifications[0]
    assert severity == "error"
    assert "Failed to read stashed prompts" in message
    assert "disk boom" in message


async def test_lock_timeout_reports_busy_without_opening_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A busy store reports retry instead of opening with stale rows."""
    from sase.core.prompt_stash_facade import PromptStashLockTimeoutError

    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    _fail_lifecycle_with(
        monkeypatch, PromptStashLockTimeoutError("prompt stash lock timed out")
    )
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness.on_prompt_input_bar_restore_requested(
        PromptInputBar.RestoreRequested("prompt")
    )
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    assert harness.notifications == [("Prompt stash is busy — retry", "error")]


async def test_history_tab_open_fails_closed_on_lifecycle_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """History entry points share the fail-closed funnel; nothing opens."""
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    _fail_lifecycle_with(monkeypatch, OSError("disk boom"))
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._open_prompts_overlay_async(
        initial_tab="history",
        origin=PromptsOrigin(kind="live_bar"),
    )

    assert harness.pushed == []
    assert len(harness.notifications) == 1
    message, severity = harness.notifications[0]
    assert severity == "error"
    assert "disk boom" in message


# -- authoritative read: Trash is never hidden --------------------------------


async def test_lifecycle_snapshot_opens_overlay_with_trash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A successful read presents both collections; Trash is not emptied."""
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    _fake_lifecycle(
        monkeypatch,
        _snapshot(
            [_entry("b", "beta"), _entry("a")],
            [
                PromptStashTrashRecordWire(
                    trashed_at="2026-09-26T14:00:00+00:00", entry=_entry("t")
                )
            ],
        ),
    )
    harness = _RestoreHarness(bar=_FakeBar(mode="prompt"))

    await harness._open_prompt_stash_panel()

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert modal._active_tab is PromptsTab.STASH
    assert [e.id for e in modal._stash_pane._entries] == ["b", "a"]
    assert [r.entry.id for r in modal._trash_records] == ["t"]
    assert harness.notifications == []


async def test_bare_at_fast_path_restores_single_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bare-``@`` fast path restores a lone entry through the same read."""
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c")])
    _fake_lifecycle(monkeypatch, _snapshot([_entry("a")], []))
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()
    await _wait_prompt_stash_tasks(harness)

    assert harness.pushed == []
    # The restore loads the stored v1 row, frontmatter included.
    assert _restore_pairs(bar) == [("alpha", "model: c")]
    assert harness.notifications == [("Restored prompt", None)]
