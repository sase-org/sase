"""Shared fixtures for the pager time-band test package."""

from __future__ import annotations

from typing import Any


NOW = 1_791_000_000


def make_version(
    ordinal: int,
    *,
    class_name: str = "authored",
    volume: int = 4,
    hidden: bool = False,
    commit: str = "",
    bead: str | None = None,
    agent: str | None = None,
    words: tuple[int, int] = (3, 1),
    sections: tuple[str, ...] = (),
    phrase: str | None = None,
    sources: tuple[tuple[str, str], ...] = (),
    config_paths: tuple[str, ...] = (),
    regen_only: bool = False,
    diverged: bool = False,
    aliased: tuple[str, ...] = (),
    committer_time: int = 1_790_510_400,
    path: str = "sase/memory/note.md",
) -> dict[str, Any]:
    sha = commit or (f"{ordinal:040d}".replace("0", "ab")[0:40])
    return {
        "ordinal": ordinal,
        "commit": sha,
        "committer_time": committer_time,
        "class": class_name,
        "hidden": hidden,
        "summary": {
            "section_paths": list(sections),
            "words_added": words[0],
            "words_removed": words[1],
            "frontmatter_phrase": phrase,
            "created_words": 8 if class_name == "created" else None,
            "volume": volume,
        },
        "provenance": {"agent": agent, "bead": bead},
        "cause": {
            "sources": [{"subject_id": subject_id} for subject_id, _ in sources],
            "config_paths": list(config_paths),
            "renderer_paths": [],
            "regen_only": regen_only,
        },
        "diverged": diverged,
        "aliased_paths": list(aliased),
        "path": path,
        "source_path": path,
    }


def make_timeline(
    *versions: dict[str, Any],
    state: str = "tracked",
    upstream_ahead: int | None = None,
    health: dict[str, Any] | None = None,
    error: str | None = None,
    is_template: bool = False,
    managed: bool = True,
) -> dict[str, Any]:
    timeline: dict[str, Any] = {
        "subject_id": "note:project:demo/note",
        "state": state,
        "versions": list(versions),
        "managed": managed,
    }
    if upstream_ahead is not None:
        timeline["upstream_ahead"] = upstream_ahead
    if health is not None:
        timeline["health"] = health
    if error is not None:
        timeline["error"] = error
    if is_template:
        timeline["is_template"] = True
    return timeline
