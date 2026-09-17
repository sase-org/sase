"""Boot identity helpers for boot-scoped service state."""

from __future__ import annotations

import platform
import subprocess
from functools import cache
from pathlib import Path

_LINUX_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
_MACOS_BOOT_ID_TIMEOUT_SECONDS = 0.5


@cache
def current_boot_id() -> str | None:
    """Return the current machine boot id, when the platform exposes one."""
    system = platform.system()
    if system == "Linux":
        try:
            value = _LINUX_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "kern.bootsessionuuid"],
                check=True,
                capture_output=True,
                text=True,
                timeout=_MACOS_BOOT_ID_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        value = result.stdout.strip()
        return value or None
    return None


__all__ = ["current_boot_id"]
