"""App-handler tests for Phase 2 prompt-stash capture persistence.

These pin the app glue that turns a presentation-only
``PromptInputBar.Stashed`` message into persisted store rows + a refreshed
top-bar badge (boundary rule D6):

- An empty capture toasts a no-op and never touches the store or badge.
- A real capture appends one row per stash event (with project / source /
  pane_index metadata), toasts a count-aware message, refreshes the badge, and
  — when the bar emptied — unmounts via the post-submit path (no
  cancelled-history save) and clears the prompt context.
- A keep-bar capture leaves the bar + context intact.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
    PromptBarStashMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
    StashedPromptPane,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _ctx(project: str = "proj") -> PromptContext:
    return PromptContext(
        project_name=project,
        cl_name="cl",
        project_file="/tmp/proj.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="branch",
        display_name="proj",
        update_target="",
    )


class _StashHarness(PromptBarStashMixin):
    """Drive the stash handler without a live Textual DOM."""

    def __init__(self, project: str | None = "proj") -> None:
        self._prompt_context = _ctx(project) if project is not None else None
        self.notifications: list[tuple[str, str | None]] = []
        self.unmount_after_submit_calls = 0
        self.applied_counts: list[int] = []
        self.applied_pinned_counts: list[int] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_after_submit_calls += 1

    # Avoid the real widget query; record what the badge would show.
    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        self._prompt_stash_cached_counts = (count, pinned_count)
        self.applied_counts.append(count)
        self.applied_pinned_counts.append(pinned_count)

    def _spawn_prompt_stash_task(self, coro: object) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        task = loop.create_task(coro)
        tasks = getattr(self, "_prompt_stash_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._prompt_stash_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


# --- empty / no-op ---------------------------------------------------------


def test_empty_capture_toasts_noop_and_skips_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness()

    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed([], source="current", dismiss_bar=False)
    )

    assert harness.notifications == [("Nothing to stash", "warning")]
    assert harness.applied_counts == []  # badge untouched
    assert harness.unmount_after_submit_calls == 0
    assert not path.exists()  # store never written


def test_non_stashed_event_is_ignored() -> None:
    harness = _StashHarness()
    # A different bar message must not be handled as a stash.
    harness.on_prompt_input_bar_stashed(PromptInputBar.Submitted("x"))
    assert harness.notifications == []


def test_capture_handler_submits_store_write_without_running_it_inline() -> None:
    class _DeferredHarness(_StashHarness):
        def __init__(self) -> None:
            super().__init__()
            self.spawned: list[object] = []

        def _spawn_prompt_stash_task(self, coro: object) -> None:
            self.spawned.append(coro)
            coro.close()

    harness = _DeferredHarness()
    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(
            [StashedPromptPane(text="queued")],
            source="current",
            dismiss_bar=False,
        )
    )

    assert len(harness.spawned) == 1
    assert harness.notifications == [("Stashed prompt", None)]
    assert harness.applied_counts == [1]


# --- real persistence (needs the Rust store binding) -----------------------


def test_stash_all_persists_one_bundle_row_with_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness(project="proj-a")

    panes = [
        StashedPromptPane(text="first", frontmatter="model: c\n", pane_index=0),
        StashedPromptPane(text="second", frontmatter="model: c\n", pane_index=1),
    ]
    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(panes, source="all", dismiss_bar=True)
    )

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    snapshot = read_prompt_stash_snapshot(path)
    assert len(snapshot.entries) == 1
    entry = snapshot.entries[0]
    assert entry.text == "first\n---\nsecond"
    assert entry.pane_index == 0
    assert entry.project == "proj-a"
    assert entry.source == "all"
    assert entry.frontmatter == "model: c\n"
    assert entry.id

    assert harness.notifications == [("Stashed 2 prompts as a bundle", None)]
    assert harness.applied_counts == [1]  # badge reflects total rows on disk
    assert harness.applied_pinned_counts == [0]
    assert harness.unmount_after_submit_calls == 1
    assert harness._prompt_context is None


def test_stash_all_persists_bundle_with_canonical_xprompt_frontmatter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness(project="proj-a")
    frontmatter = "---\nxprompts:\n  _stash_helper: Use saved helper rules\n---"

    panes = [
        StashedPromptPane(text="first", frontmatter=frontmatter, pane_index=0),
        StashedPromptPane(text="second", frontmatter=frontmatter, pane_index=1),
    ]
    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(panes, source="all", dismiss_bar=True)
    )

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    snapshot = read_prompt_stash_snapshot(path)
    assert len(snapshot.entries) == 1
    entry = snapshot.entries[0]
    assert entry.text == "first\n---\nsecond"
    assert entry.frontmatter == frontmatter
    assert "xprompts:\n" in entry.frontmatter
    assert "  _stash_helper: Use saved helper rules\n" in entry.frontmatter


def test_stash_single_pane_singular_toast_and_dismiss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness()

    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(
            [StashedPromptPane(text="solo")], source="current", dismiss_bar=True
        )
    )

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    snapshot = read_prompt_stash_snapshot(path)
    assert [e.text for e in snapshot.entries] == ["solo"]
    assert snapshot.entries[0].source == "current"
    assert harness.notifications == [("Stashed prompt", None)]
    assert harness.applied_counts == [1]
    assert harness.unmount_after_submit_calls == 1


def test_keep_bar_capture_leaves_bar_and_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness()
    base = harness._prompt_context

    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(
            [StashedPromptPane(text="kept")], source="current", dismiss_bar=False
        )
    )

    assert harness.unmount_after_submit_calls == 0
    assert harness._prompt_context is base  # context preserved for more panes
    assert harness.applied_counts == [1]


def test_missing_prompt_context_stores_null_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness(project=None)

    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(
            [StashedPromptPane(text="orphan")], source="current", dismiss_bar=True
        )
    )

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    snapshot = read_prompt_stash_snapshot(path)
    assert snapshot.entries[0].project is None


# --- Phase 4 hardening: concurrent-instance refresh on app focus -----------


async def test_app_focus_reconciles_badge_from_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regaining focus re-reads the shared pile so a sibling instance shows.

    The store is the single per-user pile, so a second ACE could append while
    this app was unfocused. ``on_app_focus`` re-reads the count off-thread and
    pushes it to the badge — without any local stash/restore op.
    """
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness()

    # Simulate a *concurrent* instance stashing two prompts on disk.
    from sase.core.prompt_stash_facade import (
        PromptStashEntryWire,
        append_prompt_stash,
    )

    append_prompt_stash(
        path,
        PromptStashEntryWire(id="x", created_at="2026-06-16T10:00:00", text="a"),
    )
    append_prompt_stash(
        path,
        PromptStashEntryWire(id="y", created_at="2026-06-16T10:01:00", text="b"),
    )

    await harness.on_app_focus(None)
    await _wait_prompt_stash_tasks(harness)

    assert harness.applied_counts == [2]
    assert harness.applied_pinned_counts == [0]


async def test_app_focus_is_a_noop_on_empty_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)
    harness = _StashHarness()

    await harness.on_app_focus(None)
    await _wait_prompt_stash_tasks(harness)

    # No rows on disk → badge driven to zero, never a crash.
    assert harness.applied_counts == [0]
    assert harness.applied_pinned_counts == [0]


# --- Phase 4 hardening: graceful degradation without the Rust binding ------


def test_capture_toasts_error_when_binding_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed persist degrades to an error toast, not a crash.

    With ``sase_core_rs`` unavailable the append raises inside
    ``_persist_stashed_panes``; the handler must catch it, toast an error, and
    leave the badge and bar untouched.
    """
    path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, path)

    def _boom(_name: str) -> object:
        raise ImportError("sase_core_rs is not importable in this environment")

    monkeypatch.setattr("sase.core.prompt_stash_facade.require_rust_binding", _boom)
    harness = _StashHarness()

    harness.on_prompt_input_bar_stashed(
        PromptInputBar.Stashed(
            [StashedPromptPane(text="x")], source="current", dismiss_bar=True
        )
    )

    assert len(harness.notifications) == 2
    message, severity = harness.notifications[-1]
    assert severity == "error"
    assert "Failed to stash prompt" in message
    assert harness.applied_counts == [1, 0]  # optimistic count was rolled back
    assert harness.unmount_after_submit_calls == 1
    assert not path.exists()  # nothing written


async def _wait_prompt_stash_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_prompt_stash_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)
