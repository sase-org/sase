"""Pinned-document injection for the Agents metadata panel.

Tests that need the Agents metadata panel to hold a known corpus cannot
simply write it and pause. The panel's document is derived from the
selected agent by the app itself, and every derivation path -- the
150 ms detail debouncer, the immediate header repaint, the async
detail-header enrichment message, the slow-tool render tick -- can land
after the write and replace the injected text with the real agent
document. Under contention those repaints arrive late enough to land in
the pause that follows the write, which is what made the inline
metadata-search nodes flaky.

Waiting for the debouncer to be idle before writing does not close the
window: the next repaint can be scheduled after the check. Re-applying
the text until it survives a turn only shortens it. So this module
suppresses the competing render instead: once a document is pinned, the
app may no longer re-derive it, and the only writer is this helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text

from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text

if TYPE_CHECKING:
    from .ace_page import AcePage

_PIN_ATTR = "_sase_pinned_document"


class _DocumentPin:
    """Gate on ``AgentPromptPanel.update`` that only this module opens."""

    def __init__(self, panel: AgentPromptPanel) -> None:
        self._write = panel.update
        self.open = False

    def __call__(self, content: Any = "", *, layout: bool = True) -> None:
        """Drop app-driven repaints; apply only authorized pinned writes."""
        if self.open:
            self._write(content, layout=layout)

    def apply(self, content: Any) -> None:
        """Write *content* through the gate."""
        self.open = True
        try:
            self(content)
        finally:
            self.open = False


def _pin(panel: AgentPromptPanel) -> _DocumentPin:
    """Return the panel's document pin, installing it on first use."""
    pin: _DocumentPin | None = getattr(panel, _PIN_ATTR, None)
    if pin is None:
        pin = _DocumentPin(panel)
        setattr(panel, _PIN_ATTR, pin)
        panel.update = pin  # type: ignore[method-assign]
    return pin


async def set_agent_prompt_document(
    page: AcePage,
    content: str,
    *,
    timeout: float = 5.0,
) -> AgentPromptPanel:
    """Pin the Agents metadata document to *content* and return its panel.

    The first call installs the pin, after which no app-driven repaint of
    ``#agent-prompt-panel`` can change the document -- neither the
    debounced detail update, nor the immediate header path, nor a
    header-enrichment or slow-tool repaint. Later calls replace the
    pinned document, which is how a test simulates a background refresh
    landing under a frozen search overlay.

    The pin lasts for the lifetime of the panel, so it belongs only in
    tests that own the document. Tests asserting what the app renders
    for an agent must wait for the real document instead (see
    ``AcePage.wait_for``).

    Args:
        page: The running ``AcePage``.
        content: Plain text to install as the panel's document.
        timeout: Seconds to wait for the write to be observable.

    Returns:
        The pinned ``AgentPromptPanel``.

    Raises:
        AssertionError: If the document is not readable back within
            *timeout*, which means the pin is not holding.
    """
    panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
    document = Text(content)
    expected = renderable_to_text(document) or ""
    _pin(panel).apply(document)
    await page.pause()
    await page.wait_for(
        lambda _state: (renderable_to_text(panel.content) or "") == expected,
        timeout=timeout,
    )
    return panel


__all__ = ["set_agent_prompt_document"]
