"""Memory pane history PNG snapshot wire fixtures.

Public constants and builders for the
``test_ace_png_snapshots_memory_pane_history_states`` split. This module is
private (``_``-prefixed); the helpers are public so the shared setup module
can import them without importing a ``_``-prefixed name across modules.
"""

from __future__ import annotations

from typing import Any


T_ALWAYS_PROMOTED = 1788940800  # 2026-09-09 08:00 UTC
_T_GOTCHAS_V1 = 1789031700  # 2026-09-10 09:15 UTC
_T_GOTCHAS_V2 = 1789905600  # 2026-09-20 12:00 UTC
_T_GOTCHAS_V3 = 1789986600  # 2026-09-21 10:30 UTC
T_GOTCHAS_V4 = 1790085780  # 2026-09-22 14:03 UTC
_T_OLD_V1 = 1786701600  # 2026-08-14 10:00 UTC
_T_OLD_V2 = 1788256800  # 2026-09-01 10:00 UTC
T_OLD_DELETED = 1790421600  # 2026-09-26 11:20 UTC
T_TUI = 1790700300  # 2026-09-29 16:45 UTC

WIRE_SCOPE_KEY = "project:sase"
GOTCHAS = "sase/memory/gotchas.md"
OLD_TIPS = "sase/memory/old_tips.md"
ROOT_AGENTS = "AGENTS.md"
ROOT_INSTRUCTIONS_ID = "instructions:project:sase/."


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
GOTCHAS_DESCRIPTION = "Code conventions."
_GOTCHAS_V1_BODY = _gotchas_body(
    "Update the default config when changing keymaps.",
    "Pin clocks in goldens.",
    star_imports=True,
)
_GOTCHAS_V2_BODY = _gotchas_body(
    "Update src/sase/default_config.yml when changing keymaps or leader keys.",
    "Pin clocks in goldens.",
)
GOTCHAS_NOW_BODY = _gotchas_body(
    "Update src/sase/default_config.yml when changing keymaps, leader keys, "
    "or any configuration values.",
    "Pin the wall clock in visual goldens.",
)

GOTCHAS_FILES: dict[str, str] = {
    "v1": _note_file(GOTCHAS_DESCRIPTION, _GOTCHAS_V1_BODY),
    "v2": _note_file(GOTCHAS_DESCRIPTION, _GOTCHAS_V2_BODY),
    # v3 is a hidden reflow of v2: identical words, re-wrapped.
    "v3": _note_file(GOTCHAS_DESCRIPTION, _GOTCHAS_V2_BODY + "\n"),
    "v4": _note_file(GOTCHAS_DESCRIPTION, GOTCHAS_NOW_BODY),
    "now": _note_file(GOTCHAS_DESCRIPTION, GOTCHAS_NOW_BODY),
}

_OLD_TIPS_BODY = (
    "## Legacy TUI tips\n\n"
    "Press F5 to refresh the agent list.\n"
    "Use the old leader map for quick jumps.\n"
)
OLD_TIPS_FILES: dict[str, str] = {
    "v1": _note_file("Tips for the legacy TUI.", _OLD_TIPS_BODY),
    "v2": _note_file("Retired tips for the legacy TUI.", _OLD_TIPS_BODY),
    # The deletion version shows the last content (§4.6 tombstone card).
    "v3": _note_file("Retired tips for the legacy TUI.", _OLD_TIPS_BODY),
}

ROOT_AGENTS_NOW = (
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
        "scope_key": WIRE_SCOPE_KEY,
        "state": "tracked",
        "tip": "1a2b3c4",
        "versions": versions,
        "total": len(versions),
    }


def gotchas_timeline() -> dict[str, Any]:
    return _timeline_wire(
        GOTCHAS,
        "note:project:sase/gotchas",
        [
            _version(
                1,
                "created",
                _T_GOTCHAS_V1,
                "docs(memory): add gotchas note",
                path=GOTCHAS,
                created_words=58,
                volume=58,
            ),
            _version(
                2,
                "authored",
                _T_GOTCHAS_V2,
                "tend keymap and import gotchas",
                path=GOTCHAS,
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
                path=GOTCHAS,
                volume=1,
            ),
            _version(
                4,
                "authored",
                T_GOTCHAS_V4,
                "fix(keymaps): name every configuration value",
                path=GOTCHAS,
                section_paths=("Default Keymap Config", "Tests"),
                words_added=9,
                words_removed=3,
                volume=12,
            ),
        ],
    )


def old_tips_timeline() -> dict[str, Any]:
    return _timeline_wire(
        OLD_TIPS,
        "note:project:sase/old_tips",
        [
            _version(
                1,
                "created",
                _T_OLD_V1,
                "docs(memory): add legacy TUI tips",
                path=OLD_TIPS,
                created_words=19,
                volume=19,
                bead="sase-1ah.2",
            ),
            _version(
                2,
                "authored",
                _T_OLD_V2,
                "mark legacy TUI tips retired",
                path=OLD_TIPS,
                words_added=1,
                volume=1,
                bead="sase-1ah.2",
            ),
            _version(
                3,
                "deleted",
                T_OLD_DELETED,
                "chore(memory): retire old_tips note",
                path=OLD_TIPS,
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


def root_agents_timeline() -> dict[str, Any]:
    versions = [
        _version(
            1,
            "rendered",
            T_ALWAYS_PROMOTED,
            "chore(memory): regenerate AGENTS.md",
            path=ROOT_AGENTS,
            words_added=12,
            volume=12,
            cause=_rendered_cause("always_note"),
        ),
        _version(
            2,
            "rendered",
            T_GOTCHAS_V4,
            "fix(keymaps): name every configuration value",
            path=ROOT_AGENTS,
            section_paths=("1.1 Code Conventions and Gotchas",),
            words_added=4,
            words_removed=1,
            volume=5,
            cause=_rendered_cause("gotchas"),
        ),
        _version(
            3,
            "rendered",
            T_TUI,
            "docs(tui): document PNG golden helpers",
            path=ROOT_AGENTS,
            section_paths=("1.2 TUI Conventions",),
            words_added=8,
            volume=8,
            cause=_rendered_cause("tui", "gotchas"),
        ),
    ]
    for row in versions:
        row["diverged"] = False
        row["aliased_paths"] = ["CLAUDE.md", "GEMINI.md", "QWEN.md"]
    wire = _timeline_wire(ROOT_AGENTS, ROOT_INSTRUCTIONS_ID, versions)
    wire["managed"] = True
    return wire


def single_version_timeline(selector: str) -> dict[str, Any]:
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


def gotchas_v1_v2_comparison() -> dict[str, Any]:
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


def empty_comparison() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "frontmatter": {"entries": []},
        "word_ops": [],
        "hunks": [],
        "removal_anchors": [],
        "stats": {},
        "unified_diff": "",
    }
