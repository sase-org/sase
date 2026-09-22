"""Decide the proc argv for a monitor command under ``monitor.tool_wrap``.

The wrap goes only into the argv the proc supervisor execs. ``monitor_command``
and ``monitor_execution_argv`` stay byte-identical to what the starter wrote,
because ``monitor/host_completion_state.py::_command_argv`` reads those for
prepared-completion ``-f`` bindings.

Policy (see ``docs/monitors.md``):

- host-owned ``execution_argv`` launch: never wrapped;
- a command that is already exactly one ``sase tool run ...``: untouched;
- a simple command equal to a catalog tool's argv, with the monitor's cwd at
  that catalog's project root: named upgrade to ``<sase> tool run <name>``;
- anything else under ``-p verify`` (or under ``all`` regardless of profile):
  ad-hoc ``<sase> tool run -- /bin/sh -c CMD``;
- ``SASE_TOOL_BYPASS`` set, ``monitor.tool_wrap: off``, an unavailable
  catalog, or (under ``verify``) a missing/non-verify profile: unchanged,
  plus one ``sase: running unwrapped (<reason>)`` line in the monitor log.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from collections.abc import Callable

from sase.content_layout import discover_project_root

from .proc_adapter import monitor_proc_argv

VERIFY_MONITOR_PROFILE_NAME = "verify"

UNWRAPPED_LOG_PREFIX = "sase: running unwrapped"


def _sase_argv() -> list[str]:
    """Return the supervisor's own ``sase`` invocation (never ``PATH``)."""
    return [sys.executable, "-m", "sase"]


def format_unwrapped_log_line(reason: str) -> str:
    """Return the single self-explaining log line for an unwrapped monitor."""
    one_line = " ".join(str(reason).split())
    return f"{UNWRAPPED_LOG_PREFIX} ({one_line})\n"


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_SIMPLE_BANNED_CHARS = frozenset("|&;<>()$`\"'\\*?[]~#{}!" + "\n")


def _has_wrapped_shape(parts: Sequence[str]) -> bool:
    """Return whether split *parts* hold a ``sase tool run`` invocation.

    Detected by argv shape (``tool`` followed by ``run`` with a ``sase``
    path in front, for any path to ``sase``), never by string prefix, so
    ``python -m sase tool run check`` and ``/usr/bin/sase tool run ...``
    count while ``tool run`` without ``sase`` does not.
    """
    for index in range(len(parts) - 1):
        if parts[index] == "tool" and parts[index + 1] == "run":
            if any(Path(token).name == "sase" for token in parts[:index]):
                return True
    return False


def _is_simple_command(parts: Sequence[str]) -> bool:
    """Return whether split *parts* run identically without a shell.

    A named upgrade execs the catalog argv directly, so any word the shell
    would interpret — operators, redirects, globs, expansions, comments, or
    a leading ``NAME=value`` assignment — keeps the command inside an ad-hoc
    ``/bin/sh -c`` wrapper instead. Conservative: quoted metacharacters
    count too, because re-quoting them exactly is not worth the risk.
    """
    if not parts:
        return False
    if _ENV_ASSIGN.match(parts[0]):
        return False
    return not any(char in _SIMPLE_BANNED_CHARS for token in parts for char in token)


def _split_command(command: str) -> list[str] | None:
    try:
        return shlex.split(command)
    except ValueError:
        return None


def _match_catalog_entry(
    parts: Sequence[str], entries: Sequence[Any]
) -> tuple[Any, tuple[str, ...]] | None:
    """Match shell-split *parts* against catalog entry argv.

    Exact argv equality always matches; a longer command matches only when
    that entry's ``args: allow`` policy permits extra arguments. Exact
    matches win over prefix matches.
    """
    prefix_match: tuple[Any, tuple[str, ...]] | None = None
    for entry in entries:
        definition = entry.definition if isinstance(entry.definition, dict) else {}
        base = [str(part) for part in (definition.get("argv") or ())]
        if not base:
            continue
        if list(parts) == base:
            return entry, ()
        policy = str(definition.get("args") or "deny")
        if (
            prefix_match is None
            and policy == "allow"
            and len(parts) > len(base)
            and list(parts[: len(base)]) == base
        ):
            prefix_match = (entry, tuple(parts[len(base) :]))
    return prefix_match


def _same_dir(first: Path | str | None, second: Path | str | None) -> bool:
    if not first or not second:
        return False
    try:
        return os.path.realpath(first) == os.path.realpath(second)
    except (OSError, ValueError):
        return False


def resolve_monitor_tool_wrap(
    command: str,
    execution_argv: Sequence[str] | None,
    profile: str | None,
    cwd: str | None,
    tool_wrap: str | None,
    *,
    env: Mapping[str, str] | None = None,
    load_catalog: Callable[[Path | str | None], Any] | None = None,
) -> tuple[list[str], str | None]:
    """Return ``(proc_argv, unwrapped_reason)`` for one monitor start.

    *proc_argv* is what the proc supervisor execs; *unwrapped_reason* is
    ``None`` when the command is wrapped (or is already wrapped, or is a
    host-owned launch) and a one-line reason when policy leaves the raw
    ``/bin/sh -c`` argv in place. The caller writes exactly one
    :func:`format_unwrapped_log_line` line for a non-``None`` reason.
    """
    raw_argv = [
        str(part) for part in monitor_proc_argv(command, execution_argv=execution_argv)
    ]
    if execution_argv:
        # Host-owned execution_argv launch (an epic `sase bead work`):
        # unchanged, never wrapped.
        return raw_argv, None
    parts = _split_command(command)
    if parts is not None and _has_wrapped_shape(parts) and _is_simple_command(parts):
        # Exactly one `sase tool run ...`: untouched, so one semantic run
        # never records twice. A compound command that merely contains one
        # falls through to an outer ad-hoc run; the inner run records as
        # its child through the inherited parent run id.
        return raw_argv, None

    environ = os.environ if env is None else env
    if environ.get("SASE_TOOL_BYPASS"):
        return raw_argv, "SASE_TOOL_BYPASS is set"

    mode = (tool_wrap or "").strip() or "verify"
    if mode not in ("off", "verify", "all"):
        mode = "verify"
    if mode == "off":
        return raw_argv, "monitor.tool_wrap is off"

    profile_name = (profile or "").strip() or None
    if mode == "verify" and profile_name != VERIFY_MONITOR_PROFILE_NAME:
        if profile_name is None:
            return raw_argv, "no profile (monitor.tool_wrap is verify)"
        return raw_argv, (
            f"profile {profile_name!r} is not wrapped (monitor.tool_wrap is verify)"
        )

    loader = load_catalog
    if loader is None:
        from sase.config.tools import load_project_tool_catalog_at

        loader = load_project_tool_catalog_at
    try:
        catalog = loader(cwd)
    except Exception as exc:  # noqa: BLE001 - wrap fails open to raw.
        detail = " ".join(str(exc).split()) or "unknown error"
        return raw_argv, f"tool catalog unavailable ({detail})"
    entries = list(getattr(catalog, "entries", None) or ())

    if parts and _is_simple_command(parts):
        matched = _match_catalog_entry(parts, entries)
        if matched is not None:
            entry, extra = matched
            root = discover_project_root(cwd)
            if root is not None and _same_dir(cwd, root):
                named = [*_sase_argv(), "tool", "run", str(entry.name)]
                if extra:
                    named += ["--", *extra]
                return named, None

    return [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", command], None


__all__ = [
    "UNWRAPPED_LOG_PREFIX",
    "VERIFY_MONITOR_PROFILE_NAME",
    "format_unwrapped_log_line",
    "resolve_monitor_tool_wrap",
]
