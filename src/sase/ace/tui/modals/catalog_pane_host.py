"""Host and pane contract for reusable catalog content widgets.

Glossary, Memory, and Snippets extract their browse/edit implementation into
a child widget that a standalone modal adapter or a later Config hub can
host. This module is the shared shape those three families agree on before
touching package exports or Admin Center wiring.

Host responsibilities
    ``close_catalog_pane`` — a standalone adapter dismisses itself; an
    embedded Admin Center host closes the center.

Pane responsibilities
    ``focus_default`` — focus the pane's primary control when the host
    shows it.
    ``on_center_tab_visibility_changed`` — Admin Center already calls this
    on working panes. Hidden cached panes must not steal focus; worker and
    debouncer teardown stays on unmount.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CatalogPaneHost(Protocol):
    """Surface that is showing a reusable catalog pane."""

    def close_catalog_pane(self) -> None:
        """Close the surface that is showing this catalog pane."""
        ...


@runtime_checkable
class CatalogPane(Protocol):
    """Reusable catalog content widget hosted by a modal or Config hub."""

    def focus_default(self) -> None:
        """Focus the pane's primary control."""
        ...

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """React to the host showing or hiding this pane."""
        ...


__all__ = ["CatalogPane", "CatalogPaneHost"]
