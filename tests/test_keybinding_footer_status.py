"""Tests for sase's TUI keybinding footer status utilities and axe state."""

import inspect

from sase.ace.tui.actions.axe_display._render_dashboard import AxeDisplayDashboardMixin
from sase.ace.tui.actions.axe_display._render_footer import AxeDisplayFooterMixin
from sase.ace.tui.widgets import KeybindingFooter


class _FooterHarness(AxeDisplayFooterMixin):
    def __init__(
        self,
        footer: KeybindingFooter,
        *,
        first_load_done: bool,
        running: bool,
    ) -> None:
        self._footer = footer
        self.axe_running = running
        self._axe_first_load_done = first_load_done
        self._service_status = None
        self._service_restart_transition = None
        self._service_health_notified = None

    def query_one(
        self, selector: str, widget_type: object | None = None
    ) -> KeybindingFooter:
        del selector, widget_type
        return self._footer

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        return (0, 0)

    def notify(self, *_args: object, **_kwargs: object) -> None:
        return

    def _push_service_health(self, footer: KeybindingFooter) -> None:
        """Leave the axe chip visible; this tale does not cover the health pill."""
        del footer


# --- Status Utility Tests ---


# --- Axe Status Indicator Tests ---


def test_keybinding_footer_status_indicator_starting() -> None:
    """Test status indicator shows STARTING when axe is starting."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    footer._axe_running = False
    footer._axe_starting = True
    footer._axe_stopping = False

    text = footer._get_status_text()
    text_str = str(text)

    assert "SVC" in text_str
    assert "STARTING" in text_str


def test_keybinding_footer_status_indicator_stopping() -> None:
    """Test status indicator shows STOPPING when axe is stopping."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    footer._axe_running = False
    footer._axe_starting = False
    footer._axe_stopping = True

    text = footer._get_status_text()
    text_str = str(text)

    assert "SVC" in text_str
    assert "STOPPING" in text_str


def test_keybinding_footer_status_indicator_restarting() -> None:
    """Test status indicator labels axe while it is restarting."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    footer._axe_restarting = True

    text_str = str(footer._get_status_text())

    assert "SVC" in text_str
    assert "RESTARTING" in text_str


def test_keybinding_footer_status_indicator_running() -> None:
    """Test status indicator labels axe while it is running."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    footer._axe_status_known = True
    footer._axe_running = True

    text_str = str(footer._get_status_text())

    assert "SVC" in text_str
    assert "RUNNING" in text_str


def test_keybinding_footer_status_indicator_stopped() -> None:
    """Test status indicator labels axe while it is stopped."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()

    loading = str(footer._get_status_text())
    assert "SVC" in loading
    assert "STOPPED" not in loading
    assert "…" in loading

    footer._axe_status_known = True
    text_str = str(footer._get_status_text())

    assert "SVC" in text_str
    assert "STOPPED" in text_str


def test_update_axe_keybinding_before_first_load_keeps_neutral_chip() -> None:
    """Services entry before the first axe load must not claim STOPPED."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    harness = _FooterHarness(footer, first_load_done=False, running=False)

    harness._update_axe_keybinding()

    text = str(footer._get_status_text())
    assert "SVC" in text
    assert "…" in text
    assert "STOPPED" not in text
    assert "RUNNING" not in text
    assert footer._axe_status_known is False


def test_update_axe_keybinding_after_first_load_pushes_real_state() -> None:
    """The first completed axe load still publishes RUNNING or STOPPED."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    harness = _FooterHarness(footer, first_load_done=True, running=True)

    harness._update_axe_keybinding()

    text = str(footer._get_status_text())
    assert "SVC" in text
    assert "RUNNING" in text
    assert footer._axe_status_known is True

    harness.axe_running = False
    harness._update_axe_keybinding()
    text = str(footer._get_status_text())
    assert "STOPPED" in text


def test_axe_dashboard_refresh_guards_set_axe_running_on_first_load() -> None:
    """Switching to Services before the first axe load uses the same chip gate."""
    source = inspect.getsource(AxeDisplayDashboardMixin._refresh_axe_display)
    assert 'getattr(self, "_axe_first_load_done", True)' in source
    assert "footer.set_axe_running(self.axe_running)" in source


def test_keybinding_footer_startup_indicator_is_labeled() -> None:
    """Test the startup stopwatch is identified as axe status."""
    footer = KeybindingFooter()

    text_str = str(footer._get_status_text())

    assert "SVC" in text_str
    assert "starting" in text_str


def test_keybinding_footer_set_axe_stopping() -> None:
    """Test set_axe_stopping updates the state."""
    footer = KeybindingFooter()
    assert footer._axe_stopping is False

    footer.set_axe_stopping(True)
    assert footer._axe_stopping is True

    footer.set_axe_stopping(False)
    assert footer._axe_stopping is False


def test_keybinding_footer_axe_bindings() -> None:
    """Test that Services tab shows only entry-dependent bindings (x start/stop/kill)."""
    footer = KeybindingFooter()

    # Default: no service proc selected, on services view. Bare x is a
    # no-op there (the host toggle is !x), so no x binding is advertised.
    bindings = footer._compute_axe_bindings("axe")
    assert bindings == []

    # Host running, still no selection: still no x binding.
    footer._axe_running = True
    bindings = footer._compute_axe_bindings("axe")
    assert bindings == []

    # Selected service proc: x toggles it.
    bindings = footer._compute_axe_bindings(
        "axe", service_selected=True, service_running=False
    )
    assert bindings[0] == ("x", "start service")
    bindings = footer._compute_axe_bindings(
        "axe", service_selected=True, service_running=True
    )
    assert bindings[0] == ("x", "stop service")

    # On bgcmd view
    bindings = footer._compute_axe_bindings(1)
    assert bindings[0] == ("x", "kill")


def test_keybinding_footer_status_with_bgcmd_running() -> None:
    """Test status indicator shows running badge when bgcmds running."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    footer._axe_status_known = True
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
    footer.end_startup_stopwatch()
    footer._axe_status_known = True
    footer._axe_running = True
    footer._bgcmd_running_count = 0
    footer._bgcmd_done_count = 3

    text = footer._get_status_text()
    text_str = str(text)

    assert "RUNNING" in text_str
    assert "[*" not in text_str
    assert "[✓3]" in text_str
