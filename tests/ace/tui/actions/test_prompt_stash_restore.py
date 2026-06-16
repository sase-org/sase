"""App-handler tests for Phase 3 prompt-stash restore.

Pin the app glue that turns a ``RestoreRequested`` / leader ``,P`` into an
opened picker and, on confirm, a ``pop`` through ``prompt_stash_facade`` plus a
load back into the bar (boundary rule D6):

- The mode guard toasts a no-op for feedback / approve-prompt bars.
- An empty store toasts instead of opening an empty modal.
- Opening reads the snapshot and pushes the picker with those entries.
- Confirm pops the chosen ids, loads restored drafts (append to a mounted bar,
  or mount the home bar pre-filled when none is shown), discards delete-marked
  ids, toasts a count-aware summary, and refreshes the badge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
    PromptBarStashMixin,
)
from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "pop_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no pop_prompt_stash binding).")


class _FakeBar:
    """Stand-in for a mounted prompt bar in ``prompt`` mode."""

    def __init__(self, mode: str = "prompt") -> None:
        self._mode = mode
        self.restored: list[tuple[str, str]] | None = None

    def restore_stashed_entries(self, entries: list[tuple[str, str]]) -> None:
        self.restored = entries


class _RestoreHarness(PromptBarStashMixin):
    """Drive the restore handlers without a live Textual DOM."""

    def __init__(self, bar: _FakeBar | None = None) -> None:
        self._prompt_context = None
        self._bar = bar
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.home_mounts: list[str] = []
        self.applied_counts: list[int] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _mounted_prompt_bar(self):  # type: ignore[override]
        return self._bar

    def _show_prompt_input_bar_for_home(self, initial_text: str = "") -> None:
        self.home_mounts.append(initial_text)

    def _apply_prompt_stash_count(self, count: int) -> None:
        self.applied_counts.append(count)


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _seed(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """Append ``(id, created_at, text, frontmatter)`` rows to the store."""
    from sase.core.prompt_stash_facade import (
        PromptStashEntryWire,
        append_prompt_stash,
    )

    for idx, (entry_id, created_at, text, frontmatter) in enumerate(rows):
        append_prompt_stash(
            path,
            PromptStashEntryWire(
                id=entry_id,
                created_at=created_at,
                text=text,
                frontmatter=frontmatter,
                pane_index=idx,
            ),
        )


# --- open / guards ---------------------------------------------------------


def test_feedback_mode_is_noop_with_toast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    harness._open_prompt_stash_restore(bar_mode="feedback")

    assert harness.pushed == []
    assert harness.notifications == [
        ("Restore is only available for agent prompts", "warning")
    ]


def test_empty_store_toasts_and_skips_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    harness._open_prompt_stash_restore()

    assert harness.pushed == []
    assert harness.notifications == [("No stashed prompts to restore", None)]


def test_open_pushes_modal_with_snapshot_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
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

    harness._open_prompt_stash_restore()

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, StashedPromptsModal)
    # Newest first.
    assert [e.id for e in modal._entries] == ["b", "a"]


def test_restore_requested_event_routes_through_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    # A non-prompt bar mode is guarded before any store read.
    harness.on_prompt_input_bar_restore_requested(
        PromptInputBar.RestoreRequested("approve_prompt")
    )
    assert harness.pushed == []
    assert harness.notifications[-1][1] == "warning"


def test_non_restore_event_ignored() -> None:
    harness = _RestoreHarness()
    harness.on_prompt_input_bar_restore_requested(PromptInputBar.Submitted("x"))
    assert harness.notifications == []
    assert harness.pushed == []


# --- confirm: pop + load ---------------------------------------------------


def test_confirm_restores_into_mounted_bar_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "alpha", "model: c"),
            ("b", "2026-06-16T11:00:00", "beta", "model: c"),
            ("c", "2026-06-16T12:00:00", "gamma", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(restore_ids=["b", "a"], delete_ids=[])
    )

    # Loaded oldest-first regardless of selection order; frontmatter preserved.
    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    # Popped from disk; only the untouched entry remains.
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["c"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == [1]  # badge reflects remaining count


def test_confirm_without_bar_mounts_home_with_combined_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "first", "model: c"),
            ("b", "2026-06-16T11:00:00", "second", ""),
        ],
    )
    harness = _RestoreHarness(bar=None)

    harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(restore_ids=["a", "b"], delete_ids=[])
    )

    assert harness.home_mounts == ["model: c\nfirst\n---\nsecond"]
    assert harness.notifications == [("Restored 2 prompts", None)]


def test_confirm_delete_only_pops_without_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
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

    harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(restore_ids=[], delete_ids=["a"])
    )

    assert bar.restored is None  # nothing loaded
    assert harness.home_mounts == []
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["b"]
    assert harness.notifications == [("Deleted stashed prompt", None)]


def test_confirm_restore_and_delete_mixed_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
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

    harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(restore_ids=["a"], delete_ids=["b"])
    )

    assert bar.restored == [("alpha", "")]
    assert harness.notifications == [("Restored prompt, deleted 1", None)]


def test_confirm_none_is_noop() -> None:
    harness = _RestoreHarness(bar=_FakeBar())
    harness._on_prompt_stash_restore_confirmed(None)
    assert harness.notifications == []
    assert harness.applied_counts == []


# --- combine helper --------------------------------------------------------


def test_stash_entries_to_prompt_text_first_frontmatter_wins() -> None:
    from sase.core.prompt_stash_wire import PromptStashEntryWire

    entries = [
        PromptStashEntryWire(
            id="a", created_at="t1", text="one", frontmatter="model: c"
        ),
        PromptStashEntryWire(
            id="b", created_at="t2", text="two", frontmatter="model: d"
        ),
    ]
    assert (
        PromptBarStashMixin._stash_entries_to_prompt_text(entries)
        == "model: c\none\n---\ntwo"
    )


def test_stash_entries_to_prompt_text_no_frontmatter() -> None:
    from sase.core.prompt_stash_wire import PromptStashEntryWire

    entries = [
        PromptStashEntryWire(id="a", created_at="t1", text="solo"),
    ]
    assert PromptBarStashMixin._stash_entries_to_prompt_text(entries) == "solo"
