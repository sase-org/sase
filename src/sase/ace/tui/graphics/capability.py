"""Terminal graphics capability detection for the ace TUI.

The active Kitty probe must run before Textual starts its input loop. Once
``App.run()`` owns stdin, probe replies are indistinguishable from user input.
"""

from __future__ import annotations

import fcntl
import os
import select
import termios
import time
import tty
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from .kitty import build_apc_sequence, tmux_passthrough_wrap

GraphicsProtocol = Literal["kitty"]
PassthroughMode = Literal["none", "tmux"]


@dataclass(frozen=True)
class GraphicsCapability:
    """Detected terminal graphics support for a TUI session."""

    supported: bool
    protocol: GraphicsProtocol | None
    passthrough: PassthroughMode
    reason: str
    terminal: str | None = None
    truecolor: bool = False
    probed: bool = False

    @classmethod
    def unavailable(
        cls,
        reason: str,
        *,
        passthrough: PassthroughMode = "none",
        terminal: str | None = None,
        truecolor: bool = False,
        probed: bool = False,
    ) -> GraphicsCapability:
        """Build an unsupported capability with a stable shape."""
        return cls(
            supported=False,
            protocol=None,
            passthrough=passthrough,
            reason=reason,
            terminal=terminal,
            truecolor=truecolor,
            probed=probed,
        )


ProbeFunc = Callable[[PassthroughMode, float], bool]


def has_truecolor(env: Mapping[str, str] | None = None) -> bool:
    """Return whether the environment advertises 24-bit color support."""
    env = os.environ if env is None else env
    colorterm = env.get("COLORTERM", "").lower()
    term = env.get("TERM", "").lower()
    return colorterm in {"truecolor", "24bit"} or "truecolor" in term


def _passthrough_mode(env: Mapping[str, str]) -> PassthroughMode:
    return "tmux" if env.get("TMUX") else "none"


def _terminal_family(env: Mapping[str, str]) -> str | None:
    term_program = env.get("TERM_PROGRAM", "").lower()
    term = env.get("TERM", "").lower()
    if env.get("KITTY_WINDOW_ID") or term_program == "kitty" or "kitty" in term:
        return "kitty"
    if term_program == "ghostty" or env.get("GHOSTTY_RESOURCES_DIR"):
        return "ghostty"
    return None


def detect_graphics_capability(
    env: Mapping[str, str] | None = None,
    *,
    probe: bool = True,
    timeout: float = 0.08,
    probe_func: ProbeFunc | None = None,
) -> GraphicsCapability:
    """Detect whether Kitty graphics placeholders should be enabled.

    Detection is intentionally conservative for generic terminals, but lets an
    active Kitty probe prove support when tmux hides the outer terminal identity
    or the user explicitly forces Kitty probing.
    """
    env = os.environ if env is None else env
    passthrough = _passthrough_mode(env)
    terminal = _terminal_family(env)
    truecolor = has_truecolor(env)
    override = env.get("SASE_TUI_GRAPHICS", "").strip().lower()

    if override in {"0", "false", "no", "off", "disable", "disabled"}:
        return GraphicsCapability.unavailable(
            "terminal graphics disabled by SASE_TUI_GRAPHICS",
            passthrough=passthrough,
            terminal=terminal,
            truecolor=truecolor,
        )

    force_kitty = override in {"1", "true", "yes", "on", "kitty", "force"}
    probe_eligible = terminal is not None or passthrough == "tmux" or force_kitty
    if not probe_eligible:
        return GraphicsCapability.unavailable(
            "terminal family is unknown outside tmux; Kitty graphics probe was not attempted",
            passthrough=passthrough,
            terminal=terminal,
            truecolor=truecolor,
        )

    if not truecolor and passthrough == "none" and not force_kitty:
        return GraphicsCapability.unavailable(
            "Kitty placeholders require truecolor foreground encoding",
            passthrough=passthrough,
            terminal=terminal,
            truecolor=False,
        )

    if not probe:
        return GraphicsCapability(
            supported=True,
            protocol="kitty",
            passthrough=passthrough,
            reason="Kitty graphics assumed from environment",
            terminal=terminal or "kitty",
            truecolor=truecolor,
            probed=False,
        )

    active_probe = probe_func or _probe_kitty_graphics
    if not active_probe(passthrough, timeout):
        return GraphicsCapability.unavailable(
            "Kitty graphics probe did not receive a supported response",
            passthrough=passthrough,
            terminal=terminal,
            truecolor=truecolor,
            probed=True,
        )

    return GraphicsCapability(
        supported=True,
        protocol="kitty",
        passthrough=passthrough,
        reason="Kitty graphics probe succeeded",
        terminal=terminal or "kitty",
        truecolor=truecolor,
        probed=True,
    )


def _probe_kitty_graphics(passthrough: PassthroughMode, timeout: float = 0.08) -> bool:
    """Actively probe Kitty graphics support on the controlling terminal."""
    stdin_fd = 0
    stdout_fd = 1
    if not os.isatty(stdin_fd) or not os.isatty(stdout_fd):
        return False

    query = build_apc_sequence(
        {"i": 31337, "a": "q", "t": "d", "f": 24, "s": 1, "v": 1},
        b"AAAA",
    )
    if passthrough == "tmux":
        query = tmux_passthrough_wrap(query)
    # Primary DA helps distinguish "unsupported APC" from "terminal silent".
    query += "\x1b[c"

    old_attrs = termios.tcgetattr(stdin_fd)
    old_flags = fcntl.fcntl(stdin_fd, fcntl.F_GETFL)
    data = bytearray()
    deadline = time.monotonic() + timeout
    try:
        tty.setcbreak(stdin_fd)
        fcntl.fcntl(stdin_fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)
        os.write(stdout_fd, query.encode("ascii"))
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([stdin_fd], [], [], remaining)
            if not readable:
                break
            try:
                chunk = os.read(stdin_fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                break
            data.extend(chunk)
            if _kitty_probe_response_supported(bytes(data)):
                return True
    finally:
        fcntl.fcntl(stdin_fd, fcntl.F_SETFL, old_flags)
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)

    return _kitty_probe_response_supported(bytes(data))


def _kitty_probe_response_supported(data: bytes) -> bool:
    """Return whether a captured terminal response contains Kitty probe OK."""
    return b"\x1b_G" in data and b"OK" in data
