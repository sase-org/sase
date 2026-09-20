"""Sound-file playback for notification delivery.

Presentation-side: picks a platform audio player and plays one file. Playback
blocks until the player exits, so callers run it on a worker thread (as the tmux
bell does). No failure ever raises into the caller.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

# Players tried in order; the first one found on PATH wins.
_MACOS_PLAYERS: tuple[tuple[str, ...], ...] = (("afplay",),)
_LINUX_PLAYERS: tuple[tuple[str, ...], ...] = (
    ("paplay",),
    ("aplay",),
    ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"),
)

# Notification sounds are short; never let a wedged player pin a worker thread.
_PLAYBACK_TIMEOUT_SECONDS = 30.0


def _candidate_players() -> Sequence[tuple[str, ...]]:
    if sys.platform == "darwin":
        return _MACOS_PLAYERS
    if sys.platform.startswith("linux"):
        return _LINUX_PLAYERS
    return ()


def resolve_sound_player() -> tuple[str, ...] | None:
    """Return the player argv prefix (without the file) for this platform.

    The executable is resolved to its full path. Returns ``None`` when no
    supported player is installed.
    """
    for argv in _candidate_players():
        executable = shutil.which(argv[0])
        if executable:
            return (executable, *argv[1:])
    return None


def play_sound_file(path: str | Path) -> bool:
    """Play ``path`` with the platform player, blocking until it finishes.

    ``$VAR`` and ``~`` in ``path`` are expanded first.

    Returns ``True`` only when a player ran and exited zero. A missing file, a
    missing player, a timeout, or a non-zero exit all return ``False``; nothing
    is ever raised.
    """
    try:
        player = resolve_sound_player()
        if player is None:
            return False
        sound_path = Path(os.path.expandvars(path)).expanduser()
        if not sound_path.is_file():
            return False
        result = subprocess.run(
            [*player, str(sound_path)],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_PLAYBACK_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except Exception:
        return False
