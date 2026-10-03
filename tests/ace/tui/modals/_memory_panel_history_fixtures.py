"""Shared history-summary fixture builders for memory-panel tests."""

from __future__ import annotations


def _version(
    ordinal: int,
    class_name: str = "authored",
    volume: int = 10,
    bead: str | None = "sase-1bc.12",
) -> dict:
    return {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790085780,
        "class": class_name,
        "hidden": False,
        "summary": {
            "section_paths": ["Default Keymap Config"],
            "words_added": 31,
            "words_removed": 4,
            "frontmatter_phrase": None,
            "created_words": None,
            "volume": volume,
        },
        "provenance": {"agent": "athena", "bead": bead},
        "cause": {},
        "path": "sase/memory/gotchas.md",
        "blob_oid": "abcd",
    }


def history_summary(**override: object) -> dict:
    base: dict = {
        "selector": "sase/memory/gotchas.md",
        "core_selector": "sase/memory/gotchas.md",
        "scope_key": "project:sase",
        "state": "tracked",
        "tip": "abc123",
        "now_epoch": 1790769600,
        "versions": [_version(1), _version(2)],
        "total": 2,
    }
    base.update(override)
    return base
