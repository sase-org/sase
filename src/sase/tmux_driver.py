"""Request modifyOtherKeys mode 2 inside tmux for CSI-u chords.

Only the real Linux terminal driver is wrapped, and only when ``TMUX`` is
set. Headless and test drivers, and non-tmux sessions, are untouched. The
module imports nothing but the stdlib and the Textual Linux driver so the
pager cold-path import diet is unaffected.
"""

from __future__ import annotations

import os

try:
    from textual.drivers.linux_driver import LinuxDriver
except Exception:  # pragma: no cover - non-Linux platforms
    LinuxDriver = None  # type: ignore[assignment,misc]


MODIFY_OTHER_KEYS_ON = "\x1b[>4;2m"
MODIFY_OTHER_KEYS_OFF = "\x1b[>4;0m"


def _tmux_modify_other_keys_active() -> bool:
    """Return whether the CSI-u request should be sent."""
    try:
        return bool(os.environ.get("TMUX"))
    except Exception:
        return False


if LinuxDriver is not None:

    class TmuxModifyOtherKeysDriver(LinuxDriver):  # type: ignore[valid-type,misc]
        """Linux driver that requests modifyOtherKeys=2 inside tmux."""

        def start_application_mode(self) -> None:
            super().start_application_mode()
            if not _tmux_modify_other_keys_active():
                return
            try:
                self.write(MODIFY_OTHER_KEYS_ON)
                self.flush()
            except Exception:
                pass

        def stop_application_mode(self) -> None:
            if _tmux_modify_other_keys_active():
                try:
                    self.write(MODIFY_OTHER_KEYS_OFF)
                    self.flush()
                except Exception:
                    pass
            super().stop_application_mode()

else:  # pragma: no cover - non-Linux platforms

    class TmuxModifyOtherKeysDriver:  # type: ignore[no-redef]
        """Placeholder when the Linux driver is unavailable."""


def maybe_tmux_driver_class(base: type) -> type:
    """Return the tmux-aware driver when *base* is the Linux driver."""
    try:
        if LinuxDriver is not None and base is LinuxDriver:
            return TmuxModifyOtherKeysDriver
    except Exception:
        pass
    return base


__all__ = [
    "MODIFY_OTHER_KEYS_OFF",
    "MODIFY_OTHER_KEYS_ON",
    "TmuxModifyOtherKeysDriver",
    "maybe_tmux_driver_class",
]
