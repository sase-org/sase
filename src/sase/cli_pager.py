"""Terminal pager support for already-rendered CLI text."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from types import FrameType

from rich.cells import cell_len

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


class PagerMode(StrEnum):
    """User-facing pager modes."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


SignalHandler = int | signal.Handlers | Callable[[int, FrameType | None], object]


def resolve_pager_mode(value: str) -> PagerMode:
    """Resolve the parser string into one concrete pager mode."""
    return PagerMode(value)


def _resolve_pager_argv() -> list[str] | None:
    """Resolve the configured pager command, without adding SASE options."""
    for name in ("SASE_PAGER", "PAGER"):
        value = os.environ.get(name)
        if value is None:
            continue
        if not value.strip():
            return None
        try:
            argv = shlex.split(value)
        except ValueError:
            return None
        return argv or None

    pager = shutil.which("less")
    return [pager] if pager else None


def page_or_print(text: str, *, mode: PagerMode | str) -> None:
    """Write *text* directly or hand it to a terminal pager."""
    resolved_mode = mode if isinstance(mode, PagerMode) else resolve_pager_mode(mode)
    decision = _paging_decision(text, mode=resolved_mode)
    if decision is None:
        _write_direct(text)
        return

    argv, env = decision
    previous_handler = _ignore_sigint()
    try:
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError:
            _write_direct(text)
            return

        if process.stdin is not None:
            try:
                process.stdin.write(text)
            except BrokenPipeError:
                pass
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        process.wait()
    finally:
        _restore_sigint(previous_handler)


def _paging_decision(
    text: str,
    *,
    mode: PagerMode,
) -> tuple[list[str], dict[str, str]] | None:
    if mode is PagerMode.NEVER:
        return None
    if not sys.stdout.isatty() or not _term_supports_paging():
        return None

    argv = _resolve_pager_argv()
    if argv is None:
        if mode is PagerMode.ALWAYS:
            print(
                "warning: no pager configured or found; writing directly",
                file=sys.stderr,
            )
        return None

    if mode is PagerMode.AUTO:
        if os.environ.get("SASE_AGENT") is not None:
            return None
        size = shutil.get_terminal_size(fallback=(80, 24))
        if _estimated_display_rows(text, columns=size.columns) <= size.lines - 1:
            return None

    pager_argv = _argv_with_required_options(argv, mode=mode)
    env = _pager_env(pager_argv, mode=mode)
    return pager_argv, env


def _term_supports_paging() -> bool:
    term = os.environ.get("TERM")
    return term is not None and term != "dumb"


def _argv_with_required_options(argv: list[str], *, mode: PagerMode) -> list[str]:
    resolved = list(argv)
    if Path(resolved[0]).name != "less":
        return resolved

    if not _less_has_raw_control_flag(resolved):
        resolved.append("-R")
    if mode is PagerMode.AUTO and not _less_has_quit_if_one_screen_flag(resolved):
        resolved.append("-F")
    return resolved


def _pager_env(argv: list[str], *, mode: PagerMode) -> dict[str, str]:
    env = os.environ.copy()
    if Path(argv[0]).name == "less" and "LESS" not in env:
        env["LESS"] = "FRX" if mode is PagerMode.AUTO else "RX"
    return env


def _less_has_raw_control_flag(argv: list[str]) -> bool:
    return any(
        arg in {"-r", "--RAW-CONTROL-CHARS"} or _short_option_contains(arg, "R")
        for arg in argv[1:]
    )


def _less_has_quit_if_one_screen_flag(argv: list[str]) -> bool:
    return any(
        arg == "--quit-if-one-screen" or _short_option_contains(arg, "F")
        for arg in argv[1:]
    )


def _short_option_contains(arg: str, option: str) -> bool:
    return arg.startswith("-") and not arg.startswith("--") and option in arg[1:]


def _estimated_display_rows(text: str, *, columns: int) -> int:
    columns = max(columns, 1)
    rows = 0
    for line in text.splitlines():
        plain = _SGR_RE.sub("", line)
        rows += max(1, math.ceil(cell_len(plain) / columns))
    return rows


def _write_direct(text: str) -> None:
    sys.stdout.write(text)


def _ignore_sigint() -> SignalHandler | None:
    try:
        return signal.signal(signal.SIGINT, signal.SIG_IGN)
    except ValueError:
        return None


def _restore_sigint(previous_handler: SignalHandler | None) -> None:
    if previous_handler is None:
        return
    try:
        signal.signal(signal.SIGINT, previous_handler)
    except ValueError:
        pass


__all__ = [
    "PagerMode",
    "page_or_print",
    "resolve_pager_mode",
]
