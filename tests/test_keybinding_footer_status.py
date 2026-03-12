"""Tests for the ace TUI keybinding footer status utilities and axe state."""

from sase.ace.tui.widgets import KeybindingFooter

# --- Status Utility Tests ---


# --- Axe Status Indicator Tests ---


def test_keybinding_footer_status_indicator_starting() -> None:
    """Test status indicator shows STARTING when axe is starting."""
    footer = KeybindingFooter()
    footer._axe_running = False
    footer._axe_starting = True
    footer._axe_stopping = False

    text = footer._get_status_text()
    text_str = str(text)

    assert "STARTING" in text_str


def test_keybinding_footer_status_indicator_stopping() -> None:
    """Test status indicator shows STOPPING when axe is stopping."""
    footer = KeybindingFooter()
    footer._axe_running = False
    footer._axe_starting = False
    footer._axe_stopping = True

    text = footer._get_status_text()
    text_str = str(text)

    assert "STOPPING" in text_str


def test_keybinding_footer_set_axe_stopping() -> None:
    """Test set_axe_stopping updates the state."""
    footer = KeybindingFooter()
    assert footer._axe_stopping is False

    footer.set_axe_stopping(True)
    assert footer._axe_stopping is True

    footer.set_axe_stopping(False)
    assert footer._axe_stopping is False


def test_keybinding_footer_axe_bindings() -> None:
    """Test that AXE tab shows clear and start/stop bindings."""
    footer = KeybindingFooter()

    # Default: axe not running, on axe view
    bindings = footer._compute_axe_bindings("axe")
    assert len(bindings) == 2
    assert bindings[0] == ("x", "clear")
    assert bindings[1] == ("X", "start axe")

    # Axe running, on axe view
    footer._axe_running = True
    bindings = footer._compute_axe_bindings("axe")
    assert bindings[1] == ("X", "stop axe")

    # On bgcmd view
    bindings = footer._compute_axe_bindings(1)
    assert bindings[1] == ("X", "kill")


def test_keybinding_footer_status_no_bgcmd_badges() -> None:
    """Test status indicator does not show bgcmd badges (removed feature)."""
    footer = KeybindingFooter()
    footer._axe_running = True

    text = footer._get_status_text()
    text_str = str(text)

    assert "RUNNING" in text_str
    assert "[*" not in text_str
    assert "[✓" not in text_str
