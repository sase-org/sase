"""Footprint recording mode and its atomic user-facing switch."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from sase.footprint.paths import MODE_LOCAL, MODE_OFF, MODE_TEST, effective_mode
from sase.footprint.paths import footprint_dir, mode_path

DISCLOSURE = (
    "Records allowlisted feature IDs, actor, outcome, local date, and duration; "
    "never command arguments or their values."
)


def set_mode(mode: str) -> None:
    """Atomically persist ``off`` or ``local`` as the configured mode."""
    if mode not in {MODE_OFF, MODE_LOCAL}:
        raise ValueError(f"unsupported Footprint mode: {mode}")
    directory = footprint_dir()
    target = mode_path()
    _guard_pytest_write(target)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".mode-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            fd = -1
            stream.write(mode + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        if mode == MODE_OFF and effective_mode() == MODE_OFF:
            from sase.footprint._cli import disable_active

            disable_active()
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def current_mode() -> str:
    """Return the effective mode, including env and pytest overrides."""
    return effective_mode()


def _guard_pytest_write(target: Path) -> None:
    if "PYTEST_CURRENT_TEST" not in os.environ and "PYTEST_VERSION" not in os.environ:
        return
    from sase.core.state_write_guard import assert_test_state_write_isolated

    assert_test_state_write_isolated(target, category="Footprint mode")


__all__ = ["DISCLOSURE", "current_mode", "set_mode"]
