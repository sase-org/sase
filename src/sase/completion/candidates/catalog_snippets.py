"""Snippet candidate fetcher backed by the Rust editor catalog loader."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.completion.candidates.catalog_support import dedupe
from sase.completion.candidates.protocol import Candidate


def snippet_source_path(_project: str | None) -> Path | None:
    """Return a cheap local invalidation path for snippet candidates."""
    root = Path.cwd() / "sase"
    for candidate in (root / "sase.yml", root / "xprompts", root):
        if candidate.exists():
            return candidate
    return None


def snippet_candidates(project: str | None) -> list[Candidate]:
    """Return effective snippet triggers, including generated aliases."""
    from sase.core.rust import require_rust_binding

    try:
        load_catalog = require_rust_binding("load_editor_snippet_catalog")
        payload: Any = load_catalog(project, str(Path.cwd()))
    except Exception:
        return []
    if not isinstance(payload, Mapping):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []

    candidates: list[Candidate] = []
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        trigger = item.get("trigger")
        if not isinstance(trigger, str) or not trigger:
            continue
        candidates.append(Candidate(trigger, _snippet_description(item)))
    return dedupe(candidates)


def _snippet_description(item: Mapping[str, object]) -> str:
    source = item.get("source")
    xprompt_name = item.get("xprompt_name")
    source_path = item.get("source_path_display")
    parts = [
        part
        for part in (source, xprompt_name, source_path)
        if isinstance(part, str) and part
    ]
    return " · ".join(parts)


__all__ = ["snippet_candidates", "snippet_source_path"]
