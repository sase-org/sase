"""Selector translation for ``sase memory history``.

``translate_history_selector`` is the shared public entry point used by the
command, the pager provider, and TUI history panels.
"""

from __future__ import annotations

from pathlib import Path

from sase.memory.history.scopes import HistoryScopeError
from sase.memory.history.service import HistoryNotFoundError
from sase.memory.selector_models import (
    NoteSelector,
    StrandSelector,
    WebSelector,
    classify_selector,
)


def _translate_strand_selector(selector: StrandSelector, repo_root: Path) -> str:
    """Translate ``web:keyword`` to a repo-relative strand path."""
    from sase.memory.web.discovery import discover_memory_webs
    from sase.memory.web.lookup import (
        MemoryWebLookupError,
        resolve_memory_strand,
    )

    try:
        discovery = discover_memory_webs(repo_root)
    except Exception as exc:
        raise HistoryNotFoundError(
            f"history selector {selector.raw!r}: cannot discover memory webs: {exc}"
        ) from exc
    for web in discovery.webs:
        if web.slug != selector.web_slug:
            continue
        try:
            strand = resolve_memory_strand(web, selector.keyword)
        except MemoryWebLookupError:
            # Possibly a deleted strand: let core try its historical
            # path aliases before giving up.
            return f"{selector.web_slug}/{selector.keyword}.md"
        try:
            return strand.path.relative_to(repo_root).as_posix()
        except ValueError:
            return strand.relative_path
    raise HistoryNotFoundError(
        f"history selector {selector.raw!r}: unknown memory web {selector.web_slug!r}"
    )


def _translate_selector(raw: str, repo_root: Path) -> str:
    """Translate a CLI selector to a core selector.

    ``web:keyword`` selectors are resolved through strand keyword and
    alias lookup; everything else passes through to
    ``memory_history_resolve``, which owns historical paths and unique
    basenames.
    """
    classified = classify_selector(raw)
    if isinstance(classified, StrandSelector):
        return _translate_strand_selector(classified, repo_root)
    if isinstance(classified, WebSelector):
        return f"{classified.web_slug}.md"
    if isinstance(classified, NoteSelector):
        return classified.path
    raise HistoryScopeError(f"invalid history selector: {raw!r}")


def translate_history_selector(raw: str, repo_root: Path) -> str:
    """Translate a CLI selector to a core selector (shared with the pager)."""
    return _translate_selector(raw, repo_root)


__all__ = ["translate_history_selector"]
