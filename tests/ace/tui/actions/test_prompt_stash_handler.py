"""App-handler tests for Phase 2 prompt-stash capture persistence.

These pin the app glue that turns a presentation-only
``PromptInputBar.Stashed`` message into persisted store rows + a refreshed
top-bar badge (boundary rule D6):

- An empty capture toasts a no-op and never touches the store or badge.
- A real capture appends one row per pane (with project / source / pane_index
  metadata), toasts a count-aware message, refreshes the badge, and — when the
  bar emptied — unmounts via the post-submit path (no cancelled-history save)
  and clears the prompt context.
- A keep-bar capture leaves the bar + context intact.
"""

from __future__ import annotations

from pathlib import Path

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

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_after_submit_calls += 1

    # Avoid the real widget query; record what the badge would show.
    def _apply_prompt_stash_count(self, count: int) -> None:
        self.applied_counts.append(count)


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


# --- real persistence (needs the Rust store binding) -----------------------


def test_stash_all_persists_each_pane_with_metadata(
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
    assert [e.text for e in snapshot.entries] == ["first", "second"]
    assert [e.pane_index for e in snapshot.entries] == [0, 1]
    assert all(e.project == "proj-a" for e in snapshot.entries)
    assert all(e.source == "all" for e in snapshot.entries)
    assert all(e.frontmatter == "model: c\n" for e in snapshot.entries)
    # Each entry gets a distinct minted id.
    assert len({e.id for e in snapshot.entries}) == 2

    assert harness.notifications == [("Stashed 2 prompts", None)]
    assert harness.applied_counts == [2]  # badge reflects total on disk
    assert harness.unmount_after_submit_calls == 1
    assert harness._prompt_context is None


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
