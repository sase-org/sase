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
    """Test that AXE tab shows only entry-dependent bindings (x start/stop/kill)."""
    footer = KeybindingFooter()

    # Default: axe not running, on axe view
    bindings = footer._compute_axe_bindings("axe")
    assert len(bindings) == 1
    assert bindings[0] == ("x", "start axe")

    # Axe running, on axe view
    footer._axe_running = True
    bindings = footer._compute_axe_bindings("axe")
    assert bindings[0] == ("x", "stop axe")

    # On bgcmd view
    bindings = footer._compute_axe_bindings(1)
    assert bindings[0] == ("x", "kill")


def test_keybinding_footer_status_with_bgcmd_running() -> None:
    """Test status indicator shows running badge when bgcmds running."""
    footer = KeybindingFooter()
    footer._axe_running = True
    footer._bgcmd_running_count = 2
    footer._bgcmd_done_count = 0

    text = footer._get_status_text()
    text_str = str(text)

    assert "RUNNING" in text_str
    assert "[*2]" in text_str
    assert "[✓" not in text_str


def test_keybinding_footer_status_with_bgcmd_done() -> None:
    """Test status indicator shows done badge when bgcmds done."""
    footer = KeybindingFooter()
    footer._axe_running = True
    footer._bgcmd_running_count = 0
    footer._bgcmd_done_count = 3

    text = footer._get_status_text()
    text_str = str(text)

    assert "RUNNING" in text_str
    assert "[*" not in text_str
    assert "[✓3]" in text_str
