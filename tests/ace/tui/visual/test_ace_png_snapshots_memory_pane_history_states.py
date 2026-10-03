"""PNG goldens for the Memory pane history states (epic ``sase-1ev``).

Covers the card and rail states of plan ``202610/memory_history_tui.md``
§4.2-§4.6 at 120x40 in dark and light themes:

- ``past_read``: the card pinned to a past version (violet frame,
  ``⟲ PAST`` pill, the historical body).
- ``past_diff``: the same pin after ``=`` (word diff with inserts,
  deletes, a removal marker, and an ``H to expand`` fold).
- ``timeline_lens``: the ``@`` Timeline lens with a hidden version and
  a ``b`` compare base.
- ``rail_glance_deleted``: the recency glance column plus the ``D``
  DELETED group with the tombstone card selected.
- ``instructions_group``: the expanded INSTRUCTIONS group with one
  instruction file card.

History data is injected deterministically through a fake app-scoped
history service: no git, no core, no wall-clock reads. The visual lane
pins ``TZ=UTC``; the few wall-clock reads the pane makes for ages are
pinned to ``_NOW`` below.
"""

from __future__ import annotations

import copy
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import memory_pane_rail_glance as rail_glance_module
from sase.ace.tui.modals import memory_pane_timeline_lens as timeline_lens_module
from sase.ace.tui.modals.memory_pane_history import MemoryPaneHistoryMixin
from sase.ace.tui.modals.memory_panel import MemoryPanel, MemoryPane
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    scope_ref,
    scope_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = 1790769600  # 2026-09-30 12:00 UTC, pinned for goldens
_T_ALWAYS_PROMOTED = 1788940800  # 2026-09-09 08:00 UTC
_T_GOTCHAS_V1 = 1789031700  # 2026-09-10 09:15 UTC
_T_GOTCHAS_V2 = 1789905600  # 2026-09-20 12:00 UTC
_T_GOTCHAS_V3 = 1789986600  # 2026-09-21 10:30 UTC
_T_GOTCHAS_V4 = 1790085780  # 2026-09-22 14:03 UTC
_T_OLD_V1 = 1786701600  # 2026-08-14 10:00 UTC
_T_OLD_V2 = 1788256800  # 2026-09-01 10:00 UTC
_T_OLD_DELETED = 1790421600  # 2026-09-26 11:20 UTC
_T_TUI = 1790700300  # 2026-09-29 16:45 UTC

_SCOPE_KEY = "sase"
_WIRE_SCOPE_KEY = "project:sase"
_GOTCHAS = "sase/memory/gotchas.md"
_OLD_TIPS = "sase/memory/old_tips.md"
_TUI = "sase/memory/tui.md"
_ALWAYS = "sase/memory/always_note.md"
_ROOT_AGENTS = "AGENTS.md"
_ROOT_INSTRUCTIONS_ID = "instructions:project:sase/."


# --- note bodies ---------------------------------------------------------


def _note_file(description: str, body: str, *, note_type: str = "reference") -> str:
    return f"---\ntype: {note_type}\ndescription: {description}\n---\n\n{body}"


def _gotchas_body(
    keymap_line: str, clock_line: str, *, star_imports: bool = False
) -> str:
    lines = [
        "## Default Keymap Config",
        "",
        keymap_line,
        "",
        "## Imports",
        "",
        "Prefer absolute imports in src/.",
        *(("Use star imports for brevity.",) if star_imports else ()),
        "Keep optional imports lazy inside functions.",
        "Never import private names across sibling modules.",
        "",
        "## Tests",
        "",
        "Use the shared wait helpers instead of fixed sleeps.",
        clock_line,
        "Run the scoped lane before finishing a turn.",
    ]
    return "\n".join(lines) + "\n"


# Short descriptions keep the rail rows narrow enough for the recency
# glance column (rows shed the glance before they wrap).
_GOTCHAS_DESCRIPTION = "Code conventions."
_GOTCHAS_V1_BODY = _gotchas_body(
    "Update the default config when changing keymaps.",
    "Pin clocks in goldens.",
    star_imports=True,
)
_GOTCHAS_V2_BODY = _gotchas_body(
    "Update src/sase/default_config.yml when changing keymaps or leader keys.",
    "Pin clocks in goldens.",
)
_GOTCHAS_NOW_BODY = _gotchas_body(
    "Update src/sase/default_config.yml when changing keymaps, leader keys, "
    "or any configuration values.",
    "Pin the wall clock in visual goldens.",
)

_GOTCHAS_FILES: dict[str, str] = {
    "v1": _note_file(_GOTCHAS_DESCRIPTION, _GOTCHAS_V1_BODY),
    "v2": _note_file(_GOTCHAS_DESCRIPTION, _GOTCHAS_V2_BODY),
    # v3 is a hidden reflow of v2: identical words, re-wrapped.
    "v3": _note_file(_GOTCHAS_DESCRIPTION, _GOTCHAS_V2_BODY + "\n"),
    "v4": _note_file(_GOTCHAS_DESCRIPTION, _GOTCHAS_NOW_BODY),
    "now": _note_file(_GOTCHAS_DESCRIPTION, _GOTCHAS_NOW_BODY),
}

_OLD_TIPS_BODY = (
    "## Legacy TUI tips\n\n"
    "Press F5 to refresh the agent list.\n"
    "Use the old leader map for quick jumps.\n"
)
_OLD_TIPS_FILES: dict[str, str] = {
    "v1": _note_file("Tips for the legacy TUI.", _OLD_TIPS_BODY),
    "v2": _note_file("Retired tips for the legacy TUI.", _OLD_TIPS_BODY),
    # The deletion version shows the last content (§4.6 tombstone card).
    "v3": _note_file("Retired tips for the legacy TUI.", _OLD_TIPS_BODY),
}

_ROOT_AGENTS_NOW = (
    "# SASE Agent Instructions\n\n"
    "## Core Memory\n\n"
    "Update src/sase/default_config.yml when changing keymaps.\n"
)


# --- timeline wires --------------------------------------------------------


def _version(
    ordinal: int,
    class_name: str,
    committer_time: int,
    subject: str,
    *,
    path: str,
    section_paths: tuple[str, ...] = (),
    words_added: int = 0,
    words_removed: int = 0,
    created_words: int | None = None,
    volume: int = 0,
    bead: str = "sase-1au.5",
    cause: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ordinal": ordinal,
        "commit": f"{ordinal:x}{path.encode().hex()}"[:40].ljust(40, "0"),
        "committer_time": committer_time,
        "class": class_name,
        "hidden": False,
        "hidden_by_default": class_name in ("reflow", "moved", "whitespace"),
        "summary": {
            "section_paths": list(section_paths),
            "words_added": words_added,
            "words_removed": words_removed,
            "frontmatter_phrase": None,
            "created_words": created_words,
            "volume": volume,
        },
        "provenance": {"subject": subject, "agent": "athena", "bead": bead},
        "cause": dict(cause or {}),
        "path": path,
        "source_path": path,
        "blob_oid": f"b{ordinal}{path.encode().hex()}"[:40].ljust(40, "0"),
    }


def _timeline_wire(
    selector: str, subject_id: str, versions: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "selector": selector,
        "subject_id": subject_id,
        "scope_key": _WIRE_SCOPE_KEY,
        "state": "tracked",
        "tip": "1a2b3c4",
        "versions": versions,
        "total": len(versions),
    }


def _gotchas_timeline() -> dict[str, Any]:
    return _timeline_wire(
        _GOTCHAS,
        "note:project:sase/gotchas",
        [
            _version(
                1,
                "created",
                _T_GOTCHAS_V1,
                "docs(memory): add gotchas note",
                path=_GOTCHAS,
                created_words=58,
                volume=58,
            ),
            _version(
                2,
                "authored",
                _T_GOTCHAS_V2,
                "tend keymap and import gotchas",
                path=_GOTCHAS,
                section_paths=("Default Keymap Config", "Imports"),
                words_added=4,
                words_removed=8,
                volume=12,
            ),
            _version(
                3,
                "reflow",
                _T_GOTCHAS_V3,
                "style(memory): rewrap gotchas",
                path=_GOTCHAS,
                volume=1,
            ),
            _version(
                4,
                "authored",
                _T_GOTCHAS_V4,
                "fix(keymaps): name every configuration value",
                path=_GOTCHAS,
                section_paths=("Default Keymap Config", "Tests"),
                words_added=9,
                words_removed=3,
                volume=12,
            ),
        ],
    )


def _old_tips_timeline() -> dict[str, Any]:
    return _timeline_wire(
        _OLD_TIPS,
        "note:project:sase/old_tips",
        [
            _version(
                1,
                "created",
                _T_OLD_V1,
                "docs(memory): add legacy TUI tips",
                path=_OLD_TIPS,
                created_words=19,
                volume=19,
                bead="sase-1ah.2",
            ),
            _version(
                2,
                "authored",
                _T_OLD_V2,
                "mark legacy TUI tips retired",
                path=_OLD_TIPS,
                words_added=1,
                volume=1,
                bead="sase-1ah.2",
            ),
            _version(
                3,
                "deleted",
                _T_OLD_DELETED,
                "chore(memory): retire old_tips note",
                path=_OLD_TIPS,
                words_removed=21,
                volume=21,
                bead="sase-1ev.8",
            ),
        ],
    )


def _rendered_cause(*sources: str) -> dict[str, Any]:
    return {
        "sources": [{"subject_id": f"note:project:sase/{name}"} for name in sources],
        "config_paths": [],
        "renderer_paths": [],
        "regen_only": False,
    }


def _root_agents_timeline() -> dict[str, Any]:
    versions = [
        _version(
            1,
            "rendered",
            _T_ALWAYS_PROMOTED,
            "chore(memory): regenerate AGENTS.md",
            path=_ROOT_AGENTS,
            words_added=12,
            volume=12,
            cause=_rendered_cause("always_note"),
        ),
        _version(
            2,
            "rendered",
            _T_GOTCHAS_V4,
            "fix(keymaps): name every configuration value",
            path=_ROOT_AGENTS,
            section_paths=("1.1 Code Conventions and Gotchas",),
            words_added=4,
            words_removed=1,
            volume=5,
            cause=_rendered_cause("gotchas"),
        ),
        _version(
            3,
            "rendered",
            _T_TUI,
            "docs(tui): document PNG golden helpers",
            path=_ROOT_AGENTS,
            section_paths=("1.2 TUI Conventions",),
            words_added=8,
            volume=8,
            cause=_rendered_cause("tui", "gotchas"),
        ),
    ]
    for row in versions:
        row["diverged"] = False
        row["aliased_paths"] = ["CLAUDE.md", "GEMINI.md", "QWEN.md"]
    wire = _timeline_wire(_ROOT_AGENTS, _ROOT_INSTRUCTIONS_ID, versions)
    wire["managed"] = True
    return wire


def _single_version_timeline(selector: str) -> dict[str, Any]:
    stem = selector.rsplit("/", 1)[-1].removesuffix(".md")
    return _timeline_wire(
        selector,
        f"note:project:sase/{stem}",
        [
            _version(
                1,
                "created",
                _T_GOTCHAS_V1,
                f"docs(memory): add {stem} note",
                path=selector,
                created_words=12,
                volume=12,
            )
        ],
    )


# --- diff wire ---------------------------------------------------------------


def _gotchas_v1_v2_comparison() -> dict[str, Any]:
    """Return a core prose comparison (v1 → v2) over the full v2 file.

    Target lines count the frontmatter, exactly like ``compare_prose``:
    line 8 is the keymap rule (word inserts and a struck delete), and
    one Imports line was removed after line 12. The unchanged frontmatter
    and Tests runs fold into ``H to expand`` labels.
    """
    return {
        "schema_version": 1,
        "frontmatter": {"entries": []},
        "word_ops": [
            {
                "target_line": 8,
                "ops": [
                    {"kind": "equal", "text": "Update ", "start": 0, "end": 7},
                    {
                        "kind": "delete",
                        "text": "the default config",
                        "start": 7,
                        "end": 7,
                    },
                    {
                        "kind": "insert",
                        "text": "src/sase/default_config.yml",
                        "start": 7,
                        "end": 34,
                    },
                    {
                        "kind": "equal",
                        "text": " when changing keymaps",
                        "start": 34,
                        "end": 56,
                    },
                    {
                        "kind": "insert",
                        "text": " or leader keys",
                        "start": 56,
                        "end": 71,
                    },
                    {"kind": "equal", "text": ".", "start": 71, "end": 72},
                ],
            },
        ],
        "hunks": [
            {
                "target_start": 8,
                "target_end": 9,
                "base_start": 8,
                "base_end": 9,
                "section_path": ["Default Keymap Config"],
            },
        ],
        "removal_anchors": [{"after_target_line": 12, "removed_count": 1}],
        "stats": {
            "words_added": 4,
            "words_removed": 8,
            "lines_added": 1,
            "lines_removed": 2,
            "reflow_only": False,
            "whitespace_only": False,
            "frontmatter_only": False,
        },
        "unified_diff": (
            "--- base\n+++ target\n"
            "@@ -8 +8 @@\n"
            "-Update the default config when changing keymaps.\n"
            "+Update src/sase/default_config.yml when changing keymaps or "
            "leader keys.\n"
            "@@ -12,2 +12 @@\n"
            " Prefer absolute imports in src/.\n"
            "-Use star imports for brevity.\n"
        ),
    }


def _empty_comparison() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "frontmatter": {"entries": []},
        "word_ops": [],
        "hunks": [],
        "removal_anchors": [],
        "stats": {},
        "unified_diff": "",
    }


# --- subjects and feed ---------------------------------------------------------


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
                    _ROOT_INSTRUCTIONS_ID,
                    [_ROOT_AGENTS, "CLAUDE.md", "GEMINI.md", "QWEN.md"],
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
                "subject_id": _ROOT_INSTRUCTIONS_ID,
                "ordinal": 3,
                "class": "rendered",
                "summary": {},
                "path": _ROOT_AGENTS,
            }
        )
    return {
        "scope_key": _WIRE_SCOPE_KEY,
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
                _T_TUI,
                "docs(tui): document PNG golden helpers",
                [_feed_entry("tui", "authored", 2)],
                rendered=True,
            ),
            _changeset(
                "d",
                _T_OLD_DELETED,
                "chore(memory): retire old_tips note",
                [_feed_entry("old_tips", "deleted", 3)],
            ),
            _changeset(
                "c",
                _T_GOTCHAS_V4,
                "fix(keymaps): name every configuration value",
                [_feed_entry("gotchas", "authored", 4)],
                rendered=True,
            ),
            _changeset(
                "a",
                _T_ALWAYS_PROMOTED,
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
            _GOTCHAS: _gotchas_timeline(),
            _OLD_TIPS: _old_tips_timeline(),
            _ROOT_AGENTS: _root_agents_timeline(),
        }
        self._files = {
            _GOTCHAS: _GOTCHAS_FILES,
            _OLD_TIPS: _OLD_TIPS_FILES,
            _ROOT_AGENTS: {"now": _ROOT_AGENTS_NOW},
        }
        self._scope = SimpleNamespace(
            scope_key=_WIRE_SCOPE_KEY,
            repo_root="/tmp/memory",
            instruction_files=(
                SimpleNamespace(
                    agents_path=_ROOT_AGENTS,
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
            wire = _single_version_timeline(selector)
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
        if (selector, base, target) == (_GOTCHAS, "v1", "v2"):
            return _gotchas_v1_v2_comparison()
        return _empty_comparison()

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
    ref = scope_ref(_SCOPE_KEY, "sase")
    notes = (
        memory_note("always_note", note_type="core", description="Always loaded."),
        memory_note(
            "gotchas", description=_GOTCHAS_DESCRIPTION, body=_GOTCHAS_NOW_BODY
        ),
        memory_note(
            "tui",
            description="TUI screenshot tips.",
            body="Capture PNG goldens with the shared visual helpers.\n",
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {_SCOPE_KEY: scope_snapshot(ref, notes)})


def _pin_history_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pane's wall-clock reads (ages, picker cells) to ``_NOW``."""
    glance_suffix = rail_glance_module._glance_suffix
    deleted_age = rail_glance_module._deleted_age_text
    lens_rows = timeline_lens_module._timeline_lens_rows
    hidden_rows = timeline_lens_module._timeline_hidden_rows
    strip_snapshot = MemoryPaneHistoryMixin._time_strip_snapshot_for_node

    def pinned_glance_suffix(
        class_name: str, committer_time: int, *, now_epoch: int = 0
    ) -> str:
        del now_epoch
        return glance_suffix(class_name, committer_time, now_epoch=_NOW)

    def pinned_deleted_age(committer_time: int, *, now_epoch: int = 0) -> str:
        del now_epoch
        return deleted_age(committer_time, now_epoch=_NOW)

    def pinned_lens_rows(
        timeline: dict[str, Any] | None, *, now_epoch: int, show_hidden: bool
    ) -> tuple[tuple[dict[str, Any], ...], int, int]:
        del now_epoch
        return lens_rows(timeline, now_epoch=_NOW, show_hidden=show_hidden)

    def pinned_hidden_rows(
        timeline: dict[str, Any] | None, *, now_epoch: int
    ) -> tuple[dict[str, Any], ...]:
        del now_epoch
        return hidden_rows(timeline, now_epoch=_NOW)

    def pinned_strip_snapshot(self: MemoryPane, node: Any | None) -> Any | None:
        snapshot = strip_snapshot(self, node)
        if snapshot is None:
            return None
        return dataclasses.replace(snapshot, now_epoch=_NOW)

    monkeypatch.setattr(rail_glance_module, "_glance_suffix", pinned_glance_suffix)
    monkeypatch.setattr(rail_glance_module, "_deleted_age_text", pinned_deleted_age)
    monkeypatch.setattr(timeline_lens_module, "_timeline_lens_rows", pinned_lens_rows)
    monkeypatch.setattr(
        timeline_lens_module, "_timeline_hidden_rows", pinned_hidden_rows
    )
    monkeypatch.setattr(
        MemoryPane, "_time_strip_snapshot_for_node", pinned_strip_snapshot
    )


def _install_history(
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


def _applied_ordinal(pane: MemoryPane) -> int:
    return int(pane._time_applied_ordinal(pane._selected_row()))


def _selected_identity(pane: MemoryPane) -> str:
    node = pane._selected_row()
    return str(getattr(node, "identity", "") or "")


async def _open_memory_pane(page: AcePage, theme: str) -> MemoryPane:
    """Open the Memory panel on ``gotchas`` with history and glance landed."""
    await wait_for_startup(page)
    page.app.theme = theme
    page.app.push_screen(MemoryPanel(initial_note=_GOTCHAS))
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
        lambda: (_SCOPE_KEY, _GOTCHAS) in pane._history_latest,
        description="gotchas timeline",
    )
    await wait_for_svg_contains(page, "NOW")
    return pane


async def _step_to_v2(page: AcePage, pane: MemoryPane) -> None:
    """Press ``(`` twice: now → v4, then v2 (the hidden v3 reflow is skipped)."""
    await page.press("(")
    await wait_for_state(page, lambda: _applied_ordinal(pane) == 4, description="v4")
    await page.press("(")
    await wait_for_state(page, lambda: _applied_ordinal(pane) == 2, description="v2")
    await wait_for_svg_contains(page, "PAST")


def _lens_row_index(pane: MemoryPane, label: str) -> int:
    for index, row in enumerate(pane._timeline_listed):
        if str(row.get("label", "")) == label and not row.get("pseudo", False):
            return index
    raise AssertionError(f"no Timeline lens row labelled {label!r}")


async def _press_lens_cursor(page: AcePage, pane: MemoryPane, key: str) -> None:
    expected = pane._timeline_cursor + (1 if key == "j" else -1)
    await page.press(key)
    await wait_for_state(
        page,
        lambda: pane._timeline_cursor == expected,
        description=f"lens cursor row {expected}",
    )


async def _move_lens_cursor(page: AcePage, pane: MemoryPane, ordinal: int) -> None:
    """Walk the lens cursor to ``v<ordinal>`` and wait for its card preview.

    Rows are located by label so the walk does not depend on the lens
    row order.
    """
    target = _lens_row_index(pane, f"v{ordinal}")
    while pane._timeline_cursor != target:
        await _press_lens_cursor(
            page, pane, "j" if pane._timeline_cursor < target else "k"
        )
    await wait_for_state(
        page,
        lambda: _applied_ordinal(pane) == ordinal,
        description=f"lens preview v{ordinal}",
    )


async def _capture(
    page: AcePage,
    ace_png_visual: AcePngSnapshotFixture,
    snapshot_name: str,
    title: str,
) -> None:
    # Step/base toasts are transient; the goldens pin the resting pane.
    page.app.clear_notifications()
    await wait_for_visual_idle(page)
    ace_png_visual.assert_page_png(page, snapshot_name, title=title)


# --- goldens -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_past_read_dark_120x40",
            "ACE memory pane - past version read dark",
        ),
        (
            "textual-light",
            "memory_pane_past_read_light_120x40",
            "ACE memory pane - past version read light",
        ),
    ],
)
async def test_memory_pane_past_read_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await _step_to_v2(page, pane)
        await wait_for_svg_contains(page, "or leader keys.")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_past_diff_dark_120x40",
            "ACE memory pane - past version word diff dark",
        ),
        (
            "textual-light",
            "memory_pane_past_diff_light_120x40",
            "ACE memory pane - past version word diff light",
        ),
    ],
)
async def test_memory_pane_past_diff_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await _step_to_v2(page, pane)
        await page.press("=")
        await wait_for_state(
            page,
            lambda: pane._diff_text_for_node(pane._selected_row()) is not None,
            description="v1 → v2 comparison",
        )
        await wait_for_svg_contains(page, "H to expand")
        await wait_for_svg_contains(page, "1 line removed")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_timeline_lens_dark_120x40",
            "ACE memory pane - Timeline lens with compare base dark",
        ),
        (
            "textual-light",
            "memory_pane_timeline_lens_light_120x40",
            "ACE memory pane - Timeline lens with compare base light",
        ),
    ],
)
async def test_memory_pane_timeline_lens_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        # The lens repaints its row markers only when a preview has to
        # load, so pin the outcome: the now-card prefetch (v2, v4) lands
        # before the cursor moves.
        await wait_for_state(
            page,
            lambda: all(
                (_SCOPE_KEY, _GOTCHAS, ordinal) in pane._time_bodies
                for ordinal in (2, 4)
            ),
            description="now-card prefetch of v2 and v4",
        )
        await page.press("@")
        await wait_for_state(
            page, lambda: pane._lens == "timeline", description="Timeline lens"
        )
        await wait_for_svg_contains(page, "1 hidden")
        await _move_lens_cursor(page, pane, 4)
        await page.press("b")
        await wait_for_state(
            page, lambda: pane._timeline_base == 4, description="compare base v4"
        )
        await _move_lens_cursor(page, pane, 2)
        await wait_for_svg_contains(page, "Compare v2 → v4")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_rail_glance_deleted_dark_120x40",
            "ACE memory pane - rail glance and DELETED tombstone dark",
        ),
        (
            "textual-light",
            "memory_pane_rail_glance_deleted_light_120x40",
            "ACE memory pane - rail glance and DELETED tombstone light",
        ),
    ],
)
async def test_memory_pane_rail_glance_deleted_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await page.press("D")
        await wait_for_state(
            page, lambda: pane._show_deleted, description="DELETED group"
        )
        await page.press("G")
        await wait_for_state(
            page,
            lambda: _selected_identity(pane) == _OLD_TIPS,
            description="tombstone row selected",
        )
        await wait_for_state(
            page, lambda: _applied_ordinal(pane) == 3, description="tombstone pin"
        )
        await wait_for_svg_contains(page, "1 deleted")
        await wait_for_svg_contains(page, "Press F5")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_instructions_group_dark_120x40",
            "ACE memory pane - INSTRUCTIONS group and card dark",
        ),
        (
            "textual-light",
            "memory_pane_instructions_group_light_120x40",
            "ACE memory pane - INSTRUCTIONS group and card light",
        ),
    ],
)
async def test_memory_pane_instructions_group_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch, include_instructions=True)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await wait_for_state(
            page,
            lambda: len(pane._instruction_order) == 2,
            description="instruction subjects",
        )
        await wait_for_svg_contains(page, "INSTRUCTIONS · 2")
        await page.press("G")
        await wait_for_state(
            page,
            lambda: _selected_identity(pane) == "INSTRUCTIONS",
            description="INSTRUCTIONS group row",
        )
        await page.press("space")
        await wait_for_state(
            page,
            lambda: pane._expanded_instructions,
            description="INSTRUCTIONS expanded",
        )
        await page.press("j")
        await wait_for_state(
            page,
            lambda: _selected_identity(pane) == _ROOT_AGENTS,
            description="root AGENTS.md row",
        )
        body_key = (_SCOPE_KEY, _ROOT_AGENTS)
        await wait_for_state(
            page,
            lambda: body_key in pane._instruction_bodies,
            description="rendered AGENTS.md body",
        )
        await wait_for_state(
            page,
            lambda: body_key in pane._history_latest,
            description="AGENTS.md timeline",
        )
        await wait_for_svg_contains(page, "Core Memory")
        await wait_for_svg_contains(page, "MANAGED")
        await _capture(page, ace_png_visual, snapshot_name, title)
