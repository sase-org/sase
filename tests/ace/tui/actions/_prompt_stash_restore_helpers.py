"""Shared fixtures for prompt-stash restore action tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
    PromptBarStashMixin,
)
from sase.ace.tui.prompt_stash_entries import RestoredStashPane
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
        self.restored: list[RestoredStashPane] | None = None

    def restore_stashed_entries(self, entries: list[RestoredStashPane]) -> None:
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
        self.home_mount_selected_panes: list[int | None] = []
        self.home_mount_cursors: list[tuple[int, int] | None] = []
        self.applied_counts: list[int] = []
        self.applied_pinned_counts: list[int] = []

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
        initial_selected_pane: int | None = None,
        initial_cursor: tuple[int, int] | None = None,
        **kwargs: object,
    ) -> None:
        del kwargs
        self.home_mounts.append(initial_text)
        self.home_mount_xprompt_markdown.append(as_xprompt_markdown)
        self.home_mount_selected_panes.append(initial_selected_pane)
        self.home_mount_cursors.append(initial_cursor)

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        self.applied_counts.append(count)
        self.applied_pinned_counts.append(pinned_count)


def _restore_pairs(bar: _FakeBar) -> list[tuple[str, str]]:
    """Return ``(text, frontmatter)`` pairs from a fake bar restore."""
    assert bar.restored is not None
    return [(pane.text, pane.frontmatter) for pane in bar.restored]


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
