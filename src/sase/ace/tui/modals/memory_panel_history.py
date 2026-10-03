"""History entry points for the Memory panel (phase `memory-panel`).

Pure helpers plus thin service wiring for the ``H`` (history) and ``C``
(changes) bindings and the pinned time strip (epic design
``plan:202610/memory_history_tui.md`` §9).

- Selectors come from the selected rail node, never from free text.
- Scopes come from the panel's scope ring
  (``MemoryScopeRef.content_root``), never from the current working
  directory.
- Everything that touches git or the Rust core runs off the event loop;
  callers schedule :func:`fetch_history_summary` in a worker and render
  the time strip from the kit.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def selector_for_node(node: Any) -> str | None:
    """Return the history selector for a rail *node*, if any.

    Notes and web descriptors resolve by their repo-relative path;
    strands resolve as ``web:slug`` so strand keyword/alias lookup in
    core applies. Web descriptor rows intentionally resolve by path so
    the descriptor note itself opens.
    """
    try:
        strand = getattr(node, "strand", None)
        web = getattr(node, "web", None)
        note = getattr(node, "note", None)
        if strand is not None and web is not None:
            slug = getattr(strand, "slug", "") or ""
            keyword = getattr(strand, "keyword", "") or ""
            web_slug = getattr(web, "slug", "") or ""
            if not web_slug:
                return None
            ref = slug or keyword
            if not ref:
                return None
            return f"{web_slug}:{ref}"
        if note is not None:
            relative = getattr(note, "relative_path", "") or ""
            if relative:
                return str(relative)
            path = getattr(note, "path", None)
            if path is not None:
                return str(path)
            return None
        return None
    except Exception:
        return None


def _history_scope_for_panel_ref(ref: Any, service: Any) -> Any | None:
    """Return the history scope for a panel scope-ring entry.

    Project entries build from ``content_root``; the home entry uses the
    chezmoi home scope (``None`` when home has no VCS). Returns ``None``
    when the scope cannot be built.
    """
    try:
        kind = getattr(ref, "kind", "project")
        if kind == "home":
            try:
                return service.home_scope()
            except Exception:
                return None
        content_root = getattr(ref, "content_root", "") or ""
        if not content_root:
            return None
        return service.project_scope(Path(content_root))
    except Exception:
        return None


def history_scopes_for_ring(ring: tuple[Any, ...], service: Any) -> list[Any]:
    """Return enabled history scopes for the panel's scope ring."""
    scopes: list[Any] = []
    seen: set[str] = set()
    for ref in ring:
        scope = _history_scope_for_panel_ref(ref, service)
        if scope is None:
            continue
        key = str(getattr(scope, "scope_key", "") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        scopes.append(scope)
    return scopes


def _core_selector_for(raw_selector: str, scope: Any, service: Any = None) -> str:
    """Translate a panel selector to the core selector for *scope*."""
    try:
        from sase.memory.history.cli_history import translate_history_selector

        repo_root = Path(str(getattr(scope, "repo_root", ".") or "."))
        return translate_history_selector(raw_selector, repo_root)
    except Exception:
        return raw_selector


def _instruction_file_traits(
    scope: Any, raw_selector: str
) -> tuple[bool | None, bool | None]:
    """Return ``(is_template, managed)`` for an instruction file selector.

    Mirrors the pager provider's traits lookup so instruction cards
    render the TEMPLATE chip and managed cause rows in the pager's own
    words. ``(None, None)`` means "not an instruction file".
    """
    try:
        normalized = str(raw_selector or "").replace("\\", "/").strip().lstrip("./")
    except Exception:
        return (None, None)
    if not normalized:
        return (None, None)
    try:
        files = getattr(scope, "instruction_files", ()) or ()
    except Exception:
        return (None, None)
    candidates = [normalized, normalized.removesuffix(".tmpl")]
    try:
        for entry in files:
            agents_path = str(getattr(entry, "agents_path", "") or "").lstrip("./")
            try:
                shim_paths = [
                    str(path).lstrip("./")
                    for path in (getattr(entry, "shim_paths", ()) or ())
                ]
            except Exception:
                shim_paths = []
            for candidate in candidates:
                if candidate == agents_path or candidate in shim_paths:
                    is_template = bool(getattr(entry, "template", False))
                    if candidate != normalized:
                        is_template = True
                    return (is_template, bool(getattr(entry, "managed", False)))
    except Exception:
        return (None, None)
    return (None, None)


def fetch_history_summary(
    service: Any, scope: Any, raw_selector: str
) -> dict[str, Any] | None:
    """Return the panel summary for *raw_selector* via ``timeline()``.

    Never calls ``sync()`` first: core queries sync internally, and
    the app-scoped history service memoizes timelines, so the row
    never pays a redundant sync per selection.

    Fail-open: any error returns ``None`` so the card keeps its
    placeholder instead of blocking or crashing the worker.
    """
    try:
        core_selector = _core_selector_for(raw_selector, scope)
        tip = ""
        try:
            timeline = service.timeline(scope, core_selector, include_hidden=True)
        except Exception:
            return None
        if not isinstance(timeline, dict):
            return None
        if not tip:
            tip = str(timeline.get("tip", "") or "")
        versions = [
            row
            for row in timeline.get("versions", ())
            if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
        ]
        versions.sort(key=lambda row: int(row.get("ordinal", 0) or 0))
        state = str(timeline.get("state", "tracked") or "tracked")
        try:
            from sase.pager.history_kit import dirty_now_from_timeline

            dirty = bool(dirty_now_from_timeline(timeline))
        except Exception:
            dirty = False
        summary: dict[str, Any] = {
            "selector": raw_selector,
            "core_selector": core_selector,
            "scope_key": str(getattr(scope, "scope_key", "") or ""),
            "state": state,
            "tip": tip,
            "now_epoch": int(time.time()),
            "versions": versions,
            "total": len(versions),
            "dirty": dirty,
        }
        try:
            summary["subject_id"] = str(timeline.get("subject_id", "") or "")
        except Exception:
            pass
        try:
            is_template, managed = _instruction_file_traits(scope, core_selector)
            if is_template is None:
                is_template, managed = _instruction_file_traits(scope, raw_selector)
            if is_template is not None:
                summary["is_template"] = bool(is_template)
            if managed is not None:
                summary["managed"] = bool(managed)
        except Exception:
            pass
        return summary
    except Exception:
        return None


def history_cache_key(summary: dict[str, Any] | None) -> tuple[str, str, str]:
    """Return the ``(scope, subject, index tip)`` cache key."""
    if not isinstance(summary, dict):
        return ("", "", "")
    return (
        str(summary.get("scope_key", "") or ""),
        str(summary.get("selector", "") or summary.get("core_selector", "") or ""),
        str(summary.get("tip", "") or ""),
    )


__all__ = [
    "fetch_history_summary",
    "history_cache_key",
    "history_scopes_for_ring",
    "selector_for_node",
]
