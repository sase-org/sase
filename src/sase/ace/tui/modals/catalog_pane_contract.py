"""Host and session contracts for reusable catalog content panes.

Glossary, Memory, and Snippets each extract a content widget that can mount
inside a standalone modal adapter now and inside the Admin Center Config hub
later. The three extraction phases share this shape so they do not fork
close, focus, visibility, or selection-bookmark wiring.

A catalog pane exposes the methods Config Center already duck-types on
working tabs:

* ``focus_default()`` — put keyboard focus on the pane's browse control.
* ``on_center_tab_visibility_changed(active)`` — hidden cached panes must
  not steal focus or paint over another sub-tab. Worker and debouncer
  teardown stays on unmount, not on hide.
* ``action_close()`` — ask the host to dismiss the enclosing surface.

The host implements ``request_close()``. A standalone adapter dismisses
itself; an embedded host closes the Admin Center.

Session injection is a single mutable bookmark: ``scope_key`` is the
Glossary/Snippets project key or the Memory scope key, and ``entry_id`` is
the selected term, trigger, or note stem. Explicit constructor seeds still
win over these fields on first load; later selection changes write through
the injected object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class CatalogPaneHost(Protocol):
    """Close contract a catalog pane calls instead of dismissing itself."""

    def request_close(self) -> None:
        """Dismiss the enclosing surface (standalone modal or Admin Center)."""
        ...


@dataclass
class CatalogPaneSession:
    """Injected bookmark for one catalog pane's active scope and entry."""

    scope_key: str | None = None
    entry_id: str | None = None

    def record_scope(self, scope_key: str | None) -> None:
        """Remember the active project or Memory scope."""
        self.scope_key = scope_key

    def record_entry(self, entry_id: str | None) -> None:
        """Remember the selected term, trigger, or note stem."""
        self.entry_id = entry_id


__all__ = ["CatalogPaneHost", "CatalogPaneSession"]
