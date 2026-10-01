"""History entry points for the Memory panel (phase `memory-panel`).

Pure helpers plus thin service wiring for the ``H`` (history) and ``C``
(changes) bindings and the History card row (epic design
``plan:202609/memory_history.md`` §4.8 and §16).

- Selectors come from the selected rail node, never from free text.
- Scopes come from the panel's scope ring
  (``MemoryScopeRef.content_root``), never from the current working
  directory.
- Everything that touches git or the Rust core runs off the event loop;
  callers schedule :func:`fetch_history_summary` in a worker and render
  the pure :func:`history_value_text` result.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

_HISTORY_SPARKLINE_WIDTH = 8


def history_enabled() -> bool:
    """Return whether the ``memory_history`` beta flag is on."""
    try:
        from sase.feature_flags import current_flags
        from sase.feature_flags.registry import FeatureFlag

        return bool(current_flags().enabled(FeatureFlag.memory_history))
    except Exception:
        return False


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


def history_scope_for_panel_ref(ref: Any, service: Any) -> Any | None:
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
        scope = history_scope_for_panel_ref(ref, service)
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


def fetch_history_summary(
    service: Any, scope: Any, raw_selector: str
) -> dict[str, Any] | None:
    """Sync one scope and return the panel summary for *raw_selector*.

    Fail-open: any error returns ``None`` so the card keeps its
    placeholder instead of blocking or crashing the worker.
    """
    try:
        core_selector = _core_selector_for(raw_selector, scope)
        try:
            sync = service.sync(scope)
        except Exception:
            sync = {}
        tip = ""
        if isinstance(sync, dict):
            tip = str(sync.get("tip", "") or sync.get("head", "") or "")
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
        summary: dict[str, Any] = {
            "selector": raw_selector,
            "core_selector": core_selector,
            "scope_key": str(getattr(scope, "scope_key", "") or ""),
            "state": state,
            "tip": tip,
            "now_epoch": int(time.time()),
            "versions": versions,
            "total": len(versions),
        }
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


def _format_age(now_epoch: int, then_epoch: int) -> str:
    """Return a compact relative age (``3d``, ``8d``, ``5mo``)."""
    delta = max(0, int(now_epoch) - int(then_epoch))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 30 * 86400:
        return f"{delta // 86400}d"
    if delta < 365 * 86400:
        return f"{delta // (30 * 86400)}mo"
    return f"{delta // (365 * 86400)}y"


def _sparkline_renderable(volumes: list[int], classes: list[str]) -> Any:
    """Render the mini sparkline without a current highlight."""
    try:
        from sase.pager._time_band import render_sparkline

        return render_sparkline(volumes, classes, None, _HISTORY_SPARKLINE_WIDTH)
    except Exception:
        return None


def _format_history_row(summary: dict[str, Any] | None) -> tuple[str, str]:
    """Return ``(plain_text, style)`` for the History property row.

    ``style`` is ``""`` for the normal row, ``"yellow"`` (amber) for
    untracked/ignored states, and ``"dim"`` for loading/unavailable
    states. ``None`` means the row is omitted (flag off is handled by
    callers; this covers only data-driven omission).
    """
    if summary is None:
        return ("…", "dim")
    state = str(summary.get("state", "tracked") or "tracked")
    normalized = state.lower().replace("_", "").replace(" ", "")
    if "untracked" in normalized:
        return ("untracked", "yellow")
    if "ignored" in normalized or "excluded" in normalized:
        return ("ignored", "yellow")
    if normalized in ("novcs", "norepo", "nogit") or "no vcs" in state.lower():
        return ("NO VCS", "dim")
    versions = summary.get("versions", ())
    if not isinstance(versions, list) or not versions:
        return ("untracked", "yellow")
    volumes: list[int] = []
    classes: list[str] = []
    for row in versions:
        if not isinstance(row, dict):
            continue
        details = row.get("summary")
        detail_map = dict(details) if isinstance(details, dict) else {}
        try:
            volumes.append(int(detail_map.get("volume", 0) or 0))
        except (TypeError, ValueError):
            volumes.append(0)
        classes.append(str(row.get("class", "") or "unclassified"))
    spark_text = _sparkline_renderable(volumes, classes)
    spark_plain = ""
    try:
        spark_plain = spark_text.plain if spark_text is not None else ""
    except Exception:
        spark_plain = ""
    total = int(summary.get("total", len(versions)) or len(versions))
    newest = versions[-1]
    try:
        then = int(newest.get("committer_time", 0) or 0)
    except (TypeError, ValueError):
        then = 0
    now_epoch = int(summary.get("now_epoch", 0) or 0) or int(time.time())
    age = _format_age(now_epoch, then) if then else "?"
    provenance = newest.get("provenance")
    provenance_map = dict(provenance) if isinstance(provenance, dict) else {}
    bead = str(provenance_map.get("bead", "") or "")
    agent = str(provenance_map.get("agent", "") or "")
    who = bead or agent
    version_word = "version" if total == 1 else "versions"
    parts = f"{total} {version_word} · changed {age} ago"
    if who:
        parts = f"{parts} · {who}"
    if spark_plain:
        return (f"{spark_plain}  {parts}", "")
    return (parts, "")


def history_value_text(summary: dict[str, Any] | None, *, accent: str) -> Any:
    """Return the History row value as Rich text, reusing the sparkline.

    The mini sparkline is the pager ``render_sparkline`` renderable
    itself (with its per-class styles); the trailing summary uses
    *accent* normally and amber/dim for honest/loading states.
    """
    from rich.text import Text as _Text

    plain, style_key = _format_history_row(summary)
    if summary is None:
        return _Text(plain, style="dim")
    state = str(summary.get("state", "tracked") or "tracked")
    normalized = state.lower().replace("_", "").replace(" ", "")
    if "untracked" in normalized or "ignored" in normalized or "excluded" in normalized:
        return _Text(plain, style="yellow")
    if normalized in ("novcs", "norepo", "nogit") or "no vcs" in state.lower():
        return _Text(plain, style="dim")
    versions = summary.get("versions", ())
    if not isinstance(versions, list) or not versions:
        return _Text(plain, style="yellow")
    volumes: list[int] = []
    classes: list[str] = []
    for row in versions:
        if not isinstance(row, dict):
            continue
        details = row.get("summary")
        detail_map = dict(details) if isinstance(details, dict) else {}
        try:
            volumes.append(int(detail_map.get("volume", 0) or 0))
        except (TypeError, ValueError):
            volumes.append(0)
        classes.append(str(row.get("class", "") or "unclassified"))
    spark = _sparkline_renderable(volumes, classes)
    # Split the plain row into its sparkline prefix and the summary
    # suffix so the sparkline keeps its own cell styles.
    try:
        spark_plain = spark.plain if spark is not None else ""
    except Exception:
        spark = None
        spark_plain = ""
    suffix = plain
    if spark_plain and plain.startswith(spark_plain):
        suffix = plain[len(spark_plain) :].lstrip()
    combined = _Text(no_wrap=True)
    if spark is not None and spark_plain:
        combined.append(spark)
        if suffix:
            combined.append("  ")
    if suffix:
        combined.append(suffix, style=accent or "")
    elif not combined.plain:
        combined.append(plain, style=accent or "")
    void_style = style_key
    if void_style and void_style != "":
        return _Text(plain, style=void_style)
    return combined


__all__ = [
    "fetch_history_summary",
    "history_cache_key",
    "history_enabled",
    "history_scope_for_panel_ref",
    "history_scopes_for_ring",
    "history_value_text",
    "selector_for_node",
]
