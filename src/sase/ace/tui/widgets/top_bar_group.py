"""Labeled top-bar indicator cluster base and pure helpers.

The TUI top bar (the row with the ``Agents | Artifacts | Services`` tabs)
speaks the same visual language as the status-row cluster beneath it
(``load: 5/8 · model: opus@high · project: +sase``): every indicator group
renders as a dim ``<type>: <body>`` group, and visible groups are joined by
a dim ``·`` separator.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Literal

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from ._text_signature import text_signature

TopBarDensity = Literal["full", "compact"]

TOP_BAR_SEPARATOR = " · "

TOP_BAR_MIN_GAP = 2


def filled_count_chip(count: int, hue: str) -> Text:
    """Build a filled `` N `` count chip in *hue*.

    Shared body for procs, monitors, and prompts. A zero or negative count
    renders as an empty (hidden) body so the hosting group collapses.
    """
    if count <= 0:
        return Text("")
    return Text(f" {count} ", style=f"bold #1a1a1a on {hue}")


def separator_visibility(visible: Sequence[bool]) -> tuple[bool, ...]:
    """Return one flag per gap between groups.

    The separator before group *i* shows iff group *i* is visible and some
    group before *i* is visible, so the cluster never renders a leading,
    trailing, or doubled separator.
    """
    items = list(visible)
    result: list[bool] = []
    for index in range(1, len(items)):
        result.append(bool(items[index] and any(items[:index])))
    return tuple(result)


def choose_top_bar_density(free_cells: int, *, full_cells: int) -> TopBarDensity:
    """Return ``full`` when the full cluster fits, else ``compact``."""
    if free_cells >= full_cells:
        return "full"
    return "compact"


class TopBarGroup(Static):
    """One labeled ``<type>: <body>`` group in the top-bar cluster.

    Subclasses keep their existing static ``_build_content`` builders, which
    now return the body only; this base adds the dim micro-label. The label
    is part of the widget, so hovering or clicking it behaves like the value.
    """

    GROUP_LABEL: ClassVar[str] = ""
    CLICK_ACTION: ClassVar[str | None] = None

    def __init__(
        self, *args: Any, density: TopBarDensity = "full", **kwargs: Any
    ) -> None:
        self._density: TopBarDensity = density
        self._body = Text("")
        self._body_signature = text_signature(self._body)
        super().__init__(Text(""), *args, **kwargs)

    @property
    def density(self) -> TopBarDensity:
        """Return the currently rendered density."""
        return self._density

    @property
    def group_visible(self) -> bool:
        """Return whether the group currently has a body to show."""
        return self._body.plain != ""

    @property
    def full_cells(self) -> int:
        """Return the cell width of the full group as currently resolved."""
        if not self.group_visible:
            return 0
        return cell_len(f"{self.GROUP_LABEL}: ") + cell_len(self._body.plain)

    @property
    def compact_cells(self) -> int:
        """Return the cell width of the compact group as currently resolved."""
        if not self.group_visible:
            return 0
        return cell_len(self._body.plain)

    @property
    def content_cells(self) -> int:
        """Return the cell width at the current density."""
        if self._density == "compact":
            return self.compact_cells
        return self.full_cells

    def _store_content(self, content: Text) -> None:
        """Store *content* without requiring an active app when unmounted."""
        if self.is_mounted:
            self.update(content)
            return
        # Mimic Static.__init__ storage: set the private content without
        # visualizing, so the first mounted render is already correct.
        self._Static__content = content  # type: ignore[attr-defined]
        try:
            self._Static__visual = None  # type: ignore[attr-defined]
        except AttributeError:
            pass

    def set_density(self, density: TopBarDensity) -> bool:
        """Render *density*, returning True only when it actually changed."""
        if density == self._density:
            return False
        self._density = density
        self._store_content(self._composed_text())
        return True

    def _composed_text(self) -> Text:
        """Compose the rendered text from the label, body, and density."""
        if not self.group_visible:
            return Text("")
        if self._density == "compact":
            return self._body.copy()
        text = Text(f"{self.GROUP_LABEL}: ", style="dim")
        text.append_text(self._body)
        return text

    def _set_body(self, body: Text) -> bool:
        """Repaint from *body*, resyncing the cluster on shape change.

        No-ops when the body's signature is unchanged. When visibility or
        cell widths changed, asks the hosting cluster to resync by walking
        ``parent`` for a ``sync_top_bar_groups`` callable.
        """
        signature = text_signature(body)
        if signature == self._body_signature:
            return False
        old_visible = self.group_visible
        old_full = self.full_cells
        old_compact = self.compact_cells
        self._body = body.copy()
        self._body_signature = signature
        self._store_content(self._composed_text())
        new_visible = self.group_visible
        if (
            new_visible != old_visible
            or self.full_cells != old_full
            or self.compact_cells != old_compact
        ):
            self._request_cluster_sync()
        return True

    def _request_cluster_sync(self) -> None:
        """Ask the hosting cluster to recompute separators and density."""
        node = self.parent
        while node is not None:
            sync = getattr(node, "sync_top_bar_groups", None)
            if callable(sync):
                sync()
                return
            node = node.parent

    async def on_click(self, event: object | None = None) -> None:
        """Run the group's home action when one is configured."""
        del event
        if self.CLICK_ACTION is None:
            return
        await self.app.run_action(self.CLICK_ACTION)


__all__ = [
    "TOP_BAR_MIN_GAP",
    "TOP_BAR_SEPARATOR",
    "TopBarDensity",
    "TopBarGroup",
    "choose_top_bar_density",
    "filled_count_chip",
    "separator_visibility",
]
