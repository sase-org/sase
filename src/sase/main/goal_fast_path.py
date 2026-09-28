"""Early dispatch for common ``sase goal`` commands.

Stdlib only: this module must not import ``argparse``, ``rich``, or
``sase.config`` (an import-isolation test enforces it). It resolves the
project from the nearest ``.sase/checkout.json``, loads one binding,
and lets the Rust core do the rest.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys


def _fast_path_color() -> bool:
    """Decide ANSI styling with stdlib only (mirrors term_color)."""
    env = os.environ
    if env.get("NO_COLOR"):
        return False
    if env.get("FORCE_COLOR") not in (None, "", "0"):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:  # noqa: BLE001 - color never fails a command.
        return False


def _fast_path_agent() -> bool:
    """Detect an agent run with stdlib only (env, no identity lookup)."""
    return bool(os.environ.get("SASE_AGENT") or os.environ.get("SASE_AGENT_NAME"))


def _fast_path_compact() -> bool:
    if _fast_path_agent():
        return True
    try:
        return not sys.stdout.isatty()
    except Exception:  # noqa: BLE001 - layout never fails a command.
        return False


def try_handle_goal_fast_path(argv: list[str]) -> int | None:
    """Handle a fast-pathed goal command.

    Returns an exit code when handled, or ``None`` when argparse should
    handle the command through the slow path.
    """
    if not argv or any(arg in {"-h", "--help"} for arg in argv):
        return None
    try:
        from sase.core.rust import require_rust_binding

        goal_fast_path = require_rust_binding("goal_fast_path")
    except Exception:
        return None
    now = (
        datetime.datetime.now(datetime.UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    try:
        response = goal_fast_path(
            {
                "argv": list(argv),
                "cwd": os.getcwd(),
                "sase_home": os.environ.get("SASE_HOME", os.path.expanduser("~/.sase")),
                "color": _fast_path_color(),
                "agent": _fast_path_compact(),
                "now": now,
            }
        )
    except Exception:
        return None
    if not isinstance(response, dict) or not response.get("handled"):
        return None
    project = str(response.get("project") or "")
    if response.get("spawn_fetch") and project:
        _spawn_fetch_worker(project)
    stdout = str(response.get("stdout") or "")
    stderr = str(response.get("stderr") or "")
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    try:
        return int(response.get("exit_code", 0))
    except (TypeError, ValueError):
        return 0


def _spawn_fetch_worker(project: str) -> None:
    """Spawn the TTL fetch worker; failures stay silent (fail-open)."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "sase.goals.fetch_worker", project],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001 - spawn fails open.
        pass
