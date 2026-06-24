"""App-handler tests for prompt-stash restore flows.

Pin the app glue that turns a ``RestoreRequested`` into an opened picker and, on
confirm, applies per-entry pop/keep/delete choices through
``prompt_stash_facade`` plus a load back into the bar (boundary rule D6). The
global ``@`` action shares the restore transport, but auto-restores a lone stash
entry while leaving prompt-local ``Ctrl+G p`` as the panel-only path:

- The mode guard toasts a no-op for feedback / approve-prompt bars.
- An empty store toasts instead of opening an empty modal.
- ``@`` restores a lone unpinned entry and pops it.
- ``@`` restores a lone pinned entry and keeps it stashed.
- ``Ctrl+G p`` and multi-entry ``@`` open the unified picker.
- Confirm pops only pop+delete ids, loads pop+keep drafts (append to a mounted
  bar, or mount the home bar pre-filled when none is shown), expands bundle rows
  into panes, discards delete-marked ids, toasts a count-aware summary, and
  refreshes the badge only when the stash changed.
"""

from __future__ import annotations

import asyncio
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


def _skip_without_pinned_binding() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "set_prompt_stash_pinned"):
        pytest.skip("sase_core_rs is too old (no set_prompt_stash_pinned binding).")


async def _wait_prompt_stash_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_prompt_stash_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


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
        self.home_mount_xprompt_markdown: list[bool] = []
        self.applied_counts: list[int] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _mounted_prompt_bar(self):  # type: ignore[override]
        return self._bar

    def _show_prompt_input_bar_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
        *,
        as_xprompt_markdown: bool = False,
    ) -> None:
        self.home_mounts.append(initial_text)
        self.home_mount_xprompt_markdown.append(as_xprompt_markdown)

    def _apply_prompt_stash_count(self, count: int) -> None:
        self.applied_counts.append(count)


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


type _SeedRow = tuple[str, str, str, str] | tuple[str, str, str, str, bool]


def _seed(path: Path, rows: list[_SeedRow]) -> None:
    """Append ``(id, created_at, text, frontmatter[, pinned])`` rows."""
    from sase.core.prompt_stash_facade import (
        PromptStashEntryWire,
        append_prompt_stash,
    )

    for idx, row in enumerate(rows):
        if len(row) == 5:
            entry_id, created_at, text, frontmatter, pinned = row
        else:
            entry_id, created_at, text, frontmatter = row
            pinned = False
        append_prompt_stash(
            path,
            PromptStashEntryWire(
                id=entry_id,
                created_at=created_at,
                text=text,
                frontmatter=frontmatter,
                pane_index=idx,
                pinned=pinned,
            ),
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


async def test_empty_store_toasts_and_skips_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    await harness._open_prompt_stash_panel()

    assert harness.pushed == []
    assert harness.notifications == [("No stashed prompts to restore", None)]


async def test_open_pushes_modal_with_snapshot_entries(
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

    await harness._open_prompt_stash_panel()

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, StashedPromptsModal)
    # Newest first.
    assert [e.id for e in modal._entries] == ["b", "a"]


async def test_action_restore_prompt_stash_opens_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The global ``@`` action opens the unified picker for multiple entries."""
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

    await harness.action_restore_prompt_stash()

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, StashedPromptsModal)
    assert [e.id for e in modal._entries] == ["b", "a"]


async def test_action_restore_prompt_stash_single_unpinned_restores_and_pops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone unpinned stash entry restores directly and is removed."""
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()

    assert harness.pushed == []
    assert bar.restored == [("alpha", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.applied_counts == [0]
    assert harness.notifications == [("Restored prompt", None)]


async def test_action_restore_prompt_stash_single_pinned_restores_and_keeps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone pinned stash entry restores directly and stays stashed."""
    _skip_without_prompt_stash_bindings()
    _skip_without_pinned_binding()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "model: c", True)])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()

    assert harness.pushed == []
    assert bar.restored == [("alpha", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [(entry.id, entry.pinned) for entry in remaining] == [("a", True)]
    assert harness.applied_counts == []
    assert harness.notifications == [("Restored prompt", None)]


async def test_action_restore_prompt_stash_single_unpinned_mounts_home_and_pops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone unpinned stash entry restores into a new home prompt bar."""
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    harness = _RestoreHarness(bar=None)

    await harness.action_restore_prompt_stash()

    assert harness.pushed == []
    assert harness.home_mounts == ["alpha"]
    assert harness.home_mount_xprompt_markdown == [True]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.applied_counts == [0]
    assert harness.notifications == [("Restored prompt", None)]


async def test_action_restore_prompt_stash_single_bundle_restores_panes_and_pops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lone bundle row counts as one stash entry and restores all panes."""
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "model: c")],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.action_restore_prompt_stash()

    assert harness.pushed == []
    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert read_prompt_stash_snapshot(path).entries == []
    assert harness.applied_counts == [0]
    assert harness.notifications == [("Restored 2 prompts", None)]


async def test_action_restore_prompt_stash_empty_store_toasts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The global ``@`` action toasts instead of opening an empty picker."""
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _RestoreHarness()

    await harness.action_restore_prompt_stash()

    assert harness.pushed == []
    assert harness.notifications == [("No stashed prompts to restore", None)]


async def test_restore_requested_single_entry_still_opens_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prompt-local ``Ctrl+G p`` stays the panel path for a single entry."""
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness.on_prompt_input_bar_restore_requested(
        PromptInputBar.RestoreRequested("prompt")
    )

    assert len(harness.pushed) == 1
    modal, _callback = harness.pushed[0]
    assert isinstance(modal, StashedPromptsModal)
    assert [e.id for e in modal._entries] == ["a"]
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
    assert harness.pushed == []
    assert harness.notifications[-1][1] == "warning"


async def test_non_restore_event_ignored() -> None:
    harness = _RestoreHarness()
    await harness.on_prompt_input_bar_restore_requested(PromptInputBar.Submitted("x"))
    assert harness.notifications == []
    assert harness.pushed == []


# --- confirm: pop / keep / delete ------------------------------------------


async def test_confirm_restores_into_mounted_bar_in_order(
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

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["b"], keep_ids=["a"], delete_ids=[])
    )

    # Loaded oldest-first regardless of selection order; frontmatter preserved.
    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    # Only pop ids are removed; keep ids stay stashed.
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["a", "c"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == [2]  # badge reflects remaining count


async def test_confirm_restores_bundle_row_into_mounted_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "model: c"),
            ("keep", "2026-06-16T11:00:00", "gamma", ""),
        ],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["bundle"], delete_ids=[])
    )

    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["keep"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    assert harness.applied_counts == [1]


async def test_confirm_without_bar_mounts_home_with_combined_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [
            ("a", "2026-06-16T10:00:00", "first\n---\nsecond", "model: c"),
            ("b", "2026-06-16T11:00:00", "third", ""),
        ],
    )
    harness = _RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a", "b"], delete_ids=[])
    )

    assert harness.home_mounts == ["model: c\nfirst\n---\nsecond\n---\nthird"]
    assert harness.home_mount_xprompt_markdown == [True]
    assert harness.notifications == [("Restored 3 prompts", None)]


async def test_confirm_without_bar_mounts_single_body_as_xprompt_markdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    frontmatter = "---\nxprompts:\n  _stash_helper: Use restored helper\n---"
    _seed(
        path,
        [
            (
                "a",
                "2026-06-16T10:00:00",
                "single body",
                frontmatter,
            )
        ],
    )
    harness = _RestoreHarness(bar=None)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a"], delete_ids=[])
    )

    assert harness.home_mounts == [f"{frontmatter}\nsingle body"]
    assert harness.home_mount_xprompt_markdown == [True]
    assert harness.notifications == [("Restored prompt", None)]


async def test_confirm_delete_only_pops_without_loading(
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

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(delete_ids=["a"])
    )

    assert bar.restored is None  # nothing loaded
    assert harness.home_mounts == []
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["b"]
    assert harness.notifications == [("Deleted stashed prompt", None)]


async def test_confirm_restore_and_delete_mixed_summary(
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

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(pop_ids=["a"], delete_ids=["b"])
    )

    assert bar.restored == [("alpha", "")]
    assert harness.notifications == [("Restored prompt, deleted 1", None)]


async def test_confirm_none_is_noop() -> None:
    harness = _RestoreHarness(bar=_FakeBar())
    await harness._on_prompt_stash_restore_confirmed(None)
    assert harness.notifications == []
    assert harness.applied_counts == []


async def test_pin_toggled_persists_without_badge_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_pinned_binding()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    harness = _RestoreHarness()

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    entry = read_prompt_stash_snapshot(path).entries[0]
    harness.on_stashed_prompts_modal_pin_toggled(
        StashedPromptsModal.PinToggled(entry, True)
    )
    await _wait_prompt_stash_tasks(harness)

    assert read_prompt_stash_snapshot(path).entries[0].pinned is True
    assert harness.notifications == []
    assert harness.applied_counts == []

    harness.on_stashed_prompts_modal_pin_toggled(
        StashedPromptsModal.PinToggled(entry, False)
    )
    await _wait_prompt_stash_tasks(harness)

    assert read_prompt_stash_snapshot(path).entries[0].pinned is False
    assert harness.notifications == []
    assert harness.applied_counts == []


# --- keep-only confirm: load without popping -------------------------------


async def test_confirm_keep_only_loads_without_popping(
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

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(keep_ids=["b", "a"])
    )

    # Loaded oldest-first regardless of selection order, but the store keeps
    # every entry.
    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    remaining = read_prompt_stash_snapshot(path).entries
    assert [e.id for e in remaining] == ["a", "b", "c"]
    assert harness.notifications == [("Restored 2 prompts", None)]
    # Badge unchanged: the entries are still stashed.
    assert harness.applied_counts == []


async def test_confirm_keep_only_single_restore_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(path, [("a", "2026-06-16T10:00:00", "alpha", "")])
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(StashRestoreResult(keep_ids=["a"]))

    assert bar.restored == [("alpha", "")]
    assert harness.notifications == [("Restored prompt", None)]
    assert harness.applied_counts == []


async def test_confirm_keep_only_expands_bundle_without_popping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    _seed(
        path,
        [("bundle", "2026-06-16T10:00:00", "alpha\n---\nbeta", "model: c")],
    )
    bar = _FakeBar(mode="prompt")
    harness = _RestoreHarness(bar=bar)

    await harness._on_prompt_stash_restore_confirmed(
        StashRestoreResult(keep_ids=["bundle"])
    )

    assert bar.restored == [("alpha", "model: c"), ("beta", "model: c")]
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    assert [e.id for e in read_prompt_stash_snapshot(path).entries] == ["bundle"]
    assert harness.notifications == [("Restored 2 prompts", None)]
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


def test_stash_entries_to_prompt_text_expands_bundle_rows() -> None:
    from sase.core.prompt_stash_wire import PromptStashEntryWire

    entries = [
        PromptStashEntryWire(
            id="a",
            created_at="t1",
            text="one\n---\ntwo",
            frontmatter="model: c",
        ),
        PromptStashEntryWire(id="b", created_at="t2", text="three"),
    ]
    assert (
        PromptBarStashMixin._stash_entries_to_prompt_text(entries)
        == "model: c\none\n---\ntwo\n---\nthree"
    )
