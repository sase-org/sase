"""Shared Memory pane history PNG snapshot fixtures and panel helpers.

Public helpers for the ``test_ace_png_snapshots_memory_pane_history_states``
split. This module is private (``_``-prefixed); the helpers are public so each
split test module can import them without importing a ``_``-prefixed name
across modules.
"""

from __future__ import annotations

import copy
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import memory_pane_rail_glance_mixin as glance_mixin_module
from sase.ace.tui.modals import memory_pane_rail_glance_rendering as glance_rows_module
from sase.ace.tui.modals import (
    _memory_pane_timeline_lens_shared as timeline_lens_shared_module,
)
from sase.ace.tui.modals import (
    memory_pane_timeline_lens_rail as timeline_lens_rail_module,
)
from sase.ace.tui.modals.memory_pane_history import MemoryPaneHistoryMixin
from sase.ace.tui.modals.memory_panel import MemoryPanel, MemoryPane
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    scope_ref,
    scope_snapshot,
)
from tests.ace.tui.visual._ace_memory_pane_history_png_snapshot_wires import (
    GOTCHAS,
    GOTCHAS_DESCRIPTION,
    GOTCHAS_FILES,
    GOTCHAS_NOW_BODY,
    OLD_TIPS,
    OLD_TIPS_FILES,
    ROOT_AGENTS,
    ROOT_AGENTS_NOW,
    ROOT_INSTRUCTIONS_ID,
    T_ALWAYS_PROMOTED,
    T_GOTCHAS_V4,
    T_OLD_DELETED,
    T_TUI,
    WIRE_SCOPE_KEY,
    empty_comparison,
    gotchas_timeline,
    gotchas_v1_v2_comparison,
    old_tips_timeline,
    root_agents_timeline,
    single_version_timeline,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

NOW = 1790769600  # 2026-09-30 12:00 UTC, pinned for goldens
SCOPE_KEY = "sase"


def _note_subject(stem: str) -> dict[str, Any]:
    return {
        "id": f"note:project:sase/{stem}",
        "kind": "note",
        "display_name": f"{stem}.md",
        "paths": [f"sase/memory/{stem}.md"],
    }


def _instruction_subject(
    subject_id: str,
    paths: list[str],
    *,
    managed: bool,
    diverged_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": subject_id,
        "kind": "instructions",
        "display_name": "AGENTS.md",
        "managed": managed,
        "template": False,
        "diverged_count": diverged_count,
        "paths": paths,
        "versions": [],
    }


def _subjects(*, include_instructions: bool) -> dict[str, Any]:
    rows = [
        _note_subject("always_note"),
        _note_subject("gotchas"),
        _note_subject("old_tips"),
        _note_subject("tui"),
    ]
    if include_instructions:
        rows.extend(
            [
                _instruction_subject(
                    ROOT_INSTRUCTIONS_ID,
                    [ROOT_AGENTS, "CLAUDE.md", "GEMINI.md", "QWEN.md"],
                    managed=True,
                ),
                _instruction_subject(
                    "instructions:project:sase/src/sase/ace",
                    ["src/sase/ace/AGENTS.md", "src/sase/ace/CLAUDE.md"],
                    managed=False,
                    diverged_count=2,
                ),
            ]
        )
    return {"subjects": rows}


def _feed_entry(stem: str, class_name: str, ordinal: int) -> dict[str, Any]:
    return {
        "subject_id": f"note:project:sase/{stem}",
        "ordinal": ordinal,
        "class": class_name,
        "summary": {"section_paths": [], "words_added": 4, "words_removed": 1},
        "path": f"sase/memory/{stem}.md",
    }


def _changeset(
    commit: str,
    committer_time: int,
    subject: str,
    authored: list[dict[str, Any]],
    *,
    rendered: bool = False,
) -> dict[str, Any]:
    consequences: list[dict[str, Any]] = []
    if rendered:
        consequences.append(
            {
                "subject_id": ROOT_INSTRUCTIONS_ID,
                "ordinal": 3,
                "class": "rendered",
                "summary": {},
                "path": ROOT_AGENTS,
            }
        )
    return {
        "scope_key": WIRE_SCOPE_KEY,
        "commit": commit * 40,
        "committer_time": committer_time,
        "provenance": {"subject": subject, "bead": "sase-1ev.8", "agent": "athena"},
        "regen_only": False,
        "authored": authored,
        "consequences": consequences,
    }


def _feed() -> dict[str, Any]:
    """Return the scope feed, newest first (one deletion for ``D``)."""
    return {
        "changesets": [
            _changeset(
                "e",
                T_TUI,
                "docs(tui): document PNG golden helpers",
                [_feed_entry("tui", "authored", 2)],
                rendered=True,
            ),
            _changeset(
                "d",
                T_OLD_DELETED,
                "chore(memory): retire old_tips note",
                [_feed_entry("old_tips", "deleted", 3)],
            ),
            _changeset(
                "c",
                T_GOTCHAS_V4,
                "fix(keymaps): name every configuration value",
                [_feed_entry("gotchas", "authored", 4)],
                rendered=True,
            ),
            _changeset(
                "a",
                T_ALWAYS_PROMOTED,
                "feat(memory): promote always_note to core",
                [_feed_entry("always_note", "promoted", 2)],
                rendered=True,
            ),
        ]
    }


# --- fake history service --------------------------------------------------------


class _FakeHistory:
    """Deterministic stand-in for the app-scoped ``AceMemoryHistory``."""

    def __init__(self, *, include_instructions: bool) -> None:
        self._subjects = _subjects(include_instructions=include_instructions)
        self._feed = _feed()
        self._timelines = {
            GOTCHAS: gotchas_timeline(),
            OLD_TIPS: old_tips_timeline(),
            ROOT_AGENTS: root_agents_timeline(),
        }
        self._files = {
            GOTCHAS: GOTCHAS_FILES,
            OLD_TIPS: OLD_TIPS_FILES,
            ROOT_AGENTS: {"now": ROOT_AGENTS_NOW},
        }
        self._scope = SimpleNamespace(
            scope_key=WIRE_SCOPE_KEY,
            repo_root="/tmp/memory",
            instruction_files=(
                SimpleNamespace(
                    agents_path=ROOT_AGENTS,
                    shim_paths=("CLAUDE.md", "GEMINI.md", "QWEN.md"),
                    template=False,
                    managed=True,
                ),
            ),
        )
        self.service = SimpleNamespace(forget_scopes=lambda: None)

    def scope_for_ref(self, _ref: Any) -> Any:
        return self._scope

    def timeline(
        self, _scope: Any, selector: str, include_hidden: bool = False
    ) -> dict[str, Any]:
        del include_hidden
        wire = self._timelines.get(selector)
        if wire is None:
            wire = single_version_timeline(selector)
        return copy.deepcopy(wire)

    def version_body(self, _scope: Any, selector: str, version: str) -> dict[str, Any]:
        files = self._files.get(selector, {})
        body = files.get(version) or files.get("now") or "# Note\n\nBody.\n"
        return {
            "body": body,
            "body_missing": False,
            "blob_oid": f"blob-{version}",
        }

    def comparison(
        self, _scope: Any, selector: str, base: str, target: str
    ) -> dict[str, Any]:
        if (selector, base, target) == (GOTCHAS, "v1", "v2"):
            return gotchas_v1_v2_comparison()
        return empty_comparison()

    def subjects(self, _scope: Any) -> dict[str, Any]:
        return copy.deepcopy(self._subjects)

    def feed(self, _scopes: list[Any]) -> dict[str, Any]:
        return copy.deepcopy(self._feed)

    def poll_changed(self, _scope: Any, _selector: str) -> bool:
        return False

    def invalidate_scope(self, _scope_key: str) -> None:
        return None

    def invalidate_subject(self, _scope_key: str, _selector: str) -> None:
        return None


# --- setup -------------------------------------------------------------------


def _setup_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref(SCOPE_KEY, "sase")
    notes = (
        memory_note("always_note", note_type="core", description="Always loaded."),
        memory_note("gotchas", description=GOTCHAS_DESCRIPTION, body=GOTCHAS_NOW_BODY),
        memory_note(
            "tui",
            description="TUI screenshot tips.",
            body="Capture PNG goldens with the shared visual helpers.\n",
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {SCOPE_KEY: scope_snapshot(ref, notes)})


def _pin_history_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pane's wall-clock reads (ages, picker cells) to ``NOW``."""
    glance_suffix = glance_rows_module.glance_suffix
    deleted_age = glance_rows_module._deleted_age_text
    lens_rows = timeline_lens_shared_module.timeline_lens_rows
    hidden_rows = timeline_lens_rail_module._timeline_hidden_rows
    strip_snapshot = MemoryPaneHistoryMixin._time_strip_snapshot_for_node

    def pinned_glance_suffix(
        class_name: str, committer_time: int, *, now_epoch: int = 0
    ) -> str:
        del now_epoch
        return glance_suffix(class_name, committer_time, now_epoch=NOW)

    def pinned_deleted_age(committer_time: int, *, now_epoch: int = 0) -> str:
        del now_epoch
        return deleted_age(committer_time, now_epoch=NOW)

    def pinned_lens_rows(
        timeline: dict[str, Any] | None, *, now_epoch: int, show_hidden: bool
    ) -> tuple[tuple[dict[str, Any], ...], int, int]:
        del now_epoch
        return lens_rows(timeline, now_epoch=NOW, show_hidden=show_hidden)

    def pinned_hidden_rows(
        timeline: dict[str, Any] | None, *, now_epoch: int
    ) -> tuple[dict[str, Any], ...]:
        del now_epoch
        return hidden_rows(timeline, now_epoch=NOW)

    def pinned_strip_snapshot(self: MemoryPane, node: Any | None) -> Any | None:
        snapshot = strip_snapshot(self, node)
        if snapshot is None:
            return None
        return dataclasses.replace(snapshot, now_epoch=NOW)

    monkeypatch.setattr(glance_mixin_module, "glance_suffix", pinned_glance_suffix)
    monkeypatch.setattr(glance_rows_module, "_deleted_age_text", pinned_deleted_age)
    monkeypatch.setattr(
        timeline_lens_shared_module, "timeline_lens_rows", pinned_lens_rows
    )
    monkeypatch.setattr(
        timeline_lens_rail_module, "_timeline_hidden_rows", pinned_hidden_rows
    )
    monkeypatch.setattr(
        MemoryPane, "_time_strip_snapshot_for_node", pinned_strip_snapshot
    )


def install_history(
    monkeypatch: pytest.MonkeyPatch, *, include_instructions: bool = False
) -> None:
    patch_startup_loaders(monkeypatch)
    _setup_notes(monkeypatch)
    _pin_history_clock(monkeypatch)
    history = _FakeHistory(include_instructions=include_instructions)
    # Class-level so every worker, from the first render on, sees the fake.
    monkeypatch.setattr(MemoryPane, "_ace_history", lambda _self: history)


def _panel_pane(page: AcePage) -> MemoryPane | None:
    screen = page.app.screen
    if isinstance(screen, MemoryPanel):
        return screen.pane
    if isinstance(screen, MemoryPane):
        return screen
    return None


def _require_pane(page: AcePage) -> MemoryPane:
    pane = _panel_pane(page)
    assert pane is not None
    return pane


async def open_memory_pane(page: AcePage, theme: str) -> MemoryPane:
    """Open the Memory panel on ``gotchas`` with history and glance landed."""
    await wait_for_startup(page)
    page.app.theme = theme
    page.app.push_screen(MemoryPanel(initial_note=GOTCHAS))
    await page.expect_modal("MemoryPanel")
    await wait_for_state(
        page,
        lambda: _panel_pane(page) is not None and not _require_pane(page)._loading,
        description="panel load",
    )
    pane = _require_pane(page)
    await wait_for_state(
        page, lambda: bool(pane._glance_map), description="rail glance column"
    )
    await wait_for_state(
        page,
        lambda: (SCOPE_KEY, GOTCHAS) in pane._history_latest,
        description="gotchas timeline",
    )
    await wait_for_svg_contains(page, "NOW")
    return pane


async def capture(
    page: AcePage,
    ace_png_visual: AcePngSnapshotFixture,
    snapshot_name: str,
    title: str,
) -> None:
    # Step/base toasts are transient; the goldens pin the resting pane.
    page.app.clear_notifications()
    await wait_for_visual_idle(page)
    ace_png_visual.assert_page_png(page, snapshot_name, title=title)
