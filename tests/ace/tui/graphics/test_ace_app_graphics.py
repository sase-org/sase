from __future__ import annotations

from sase.ace.tui import AceApp
from sase.ace.tui.graphics import GraphicsCapability


def test_ace_app_stores_graphics_capability() -> None:
    capability = GraphicsCapability(
        supported=True,
        protocol="kitty",
        passthrough="tmux",
        reason="test",
        terminal="kitty",
        truecolor=True,
        probed=True,
    )

    app = AceApp(auto_start_axe=False, graphics_capability=capability)

    assert app.graphics_capability is capability
