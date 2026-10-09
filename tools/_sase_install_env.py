#!/usr/bin/env python3
"""Guards and environment probes for the ``sase_install`` engine (stdlib-only).

This module never imports ``sase``: the installer must work when the installed
``sase`` is missing or broken. Anything shared with ``sase`` (the ephemeral
checkout classification, the managed-workspace root rules) is mirrored here as
plain functions, and parity is enforced by tests that *may* import ``sase``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


#: Environment variables whose presence marks this process as a SASE agent run.
AGENT_ENV_VARS = ("SASE_AGENT", "SASE_MONITOR_ID")

#: Escape hatch: a non-empty reason that lets an agent run a global installer.
BYPASS_ENV_VAR = "SASE_GLOBAL_INSTALL_BYPASS"

#: Lets a dev pairing proceed with a stale core (consequential; dev-core-prep).
STALE_CORE_ENV_VAR = "SASE_ALLOW_STALE_CORE"

#: Disables the code-swap lock (engine-pypi honors this; recorded here).
DISABLE_LOCK_ENV_VAR = "SASE_DISABLE_CODE_SWAP_LOCK"

#: Overrides the managed-workspace root used by the ephemeral classifier.
WORKSPACE_ROOT_ENV_VAR = "SASE_WORKSPACE_ROOT"

#: Overrides the SASE state root.
SASE_HOME_ENV_VAR = "SASE_HOME"

#: Pins the sase-core checkout a dev install pairs with.
CORE_DIR_ENV_VAR = "SASE_CORE_DIR"

#: Overrides the sase-core clone URL (tests point this at local bare repos).
CORE_REMOTE_ENV_VAR = "SASE_INSTALL_CORE_REMOTE"

#: Mirror of ``sase._linked_repo_paths`` (kept literal so this stays stdlib-only).
LINKED_REPO_CLONES_SUBDIR = ("sase", "repos", "linked")
EXTERNAL_REPO_CLONES_SUBDIR = ("sase", "repos", "external")

#: Where to send a human who needs uv.
UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"

_GIT_TIMEOUT_SECONDS = 10.0
_UV_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class AgentGuard:
    """Outcome of the human-only gate for the global installers."""

    refused: bool
    bypass_reason: str | None = None


def agent_guard(env: Mapping[str, str] | None = None) -> AgentGuard:
    """Return whether this process must refuse to run a global installer."""
    source = os.environ if env is None else env
    inside_agent = any((source.get(var) or "").strip() for var in AGENT_ENV_VARS)
    if not inside_agent:
        return AgentGuard(refused=False)
    reason = (source.get(BYPASS_ENV_VAR) or "").strip()
    if reason:
        return AgentGuard(refused=False, bypass_reason=reason)
    return AgentGuard(refused=True)


def agent_refusal_text(prog: str) -> str:
    """Render the human-only refusal block for *prog*."""
    return (
        f"\u2717 {prog} won't run inside a SASE agent \u2014 it replaces "
        "the global `sase` that every agent and the scheduler run.\n"
        "  repair this workspace's .venv      just install-venv\n"
        "  the user asked for a reinstall     propose it with /sase_gate "
        f"and {BYPASS_ENV_VAR}='<reason>'"
    )


def agent_bypass_note(reason: str) -> str:
    """Render the one-line note naming an explicit bypass reason."""
    return (
        f"note: proceeding with a global install inside a SASE agent "
        f"because {BYPASS_ENV_VAR}='{reason}'"
    )


def non_tty_text(prog: str) -> str:
    """Render the non-TTY refusal: without a terminal every run needs ``-y``."""
    return (
        f"\u2717 {prog} needs -y without a terminal \u2014 a stray reinstall "
        "must never silently replace somebody's `sase`.\n"
        f"  preview the plan                    {prog} -n\n"
        f"  run it non-interactively            {prog} -y"
    )


def managed_workspace_root(env: Mapping[str, str] | None = None) -> str:
    """Return the base directory holding managed workspace checkouts.

    Mirrors ``sase.workspace_provider.store.managed_workspace_root``: the
    ``SASE_WORKSPACE_ROOT`` override wins, otherwise the platform
    state-directory default applies.
    """
    source = os.environ if env is None else env
    override = (source.get(WORKSPACE_ROOT_ENV_VAR) or "").strip()
    if override:
        return override
    xdg = source.get("XDG_STATE_HOME")
    if xdg:
        return str(Path(xdg) / "sase" / "workspaces")
    if sys.platform == "darwin":
        return str(
            Path.home() / "Library" / "Application Support" / "sase" / "workspaces"
        )
    if sys.platform == "win32":
        local = source.get("LOCALAPPDATA")
        if local:
            return str(Path(local) / "sase" / "workspaces")
        return str(Path.home() / "AppData" / "Local" / "sase" / "workspaces")
    return str(Path.home() / ".local" / "state" / "sase" / "workspaces")


def _normalized_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _contains_parts(parts: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    width = len(needle)
    return any(parts[index : index + width] == needle for index in range(len(parts)))


def is_ephemeral_path(
    path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether *path* lives in an ephemeral agent workspace checkout.

    Mirrors ``sase.uv_tool.preflight._is_ephemeral_plugin_path``: under the
    managed workspace root, or containing a ``sase/repos/linked`` or
    ``sase/repos/external`` path segment.
    """
    candidate = _normalized_path(path)
    root = _normalized_path(
        workspace_root
        if workspace_root is not None
        else managed_workspace_root(env=env)
    )
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        pass
    return _contains_parts(
        candidate.parts, LINKED_REPO_CLONES_SUBDIR
    ) or _contains_parts(candidate.parts, EXTERNAL_REPO_CLONES_SUBDIR)


def durable_dev_refusal_text(
    *, prog: str, bad_root: str, durable_sase: str | None
) -> str:
    """Render the dev-only durable-source refusal (exit 2)."""
    lines = [
        f"\u2717 {prog} needs a durable sase checkout \u2014 {bad_root} "
        "is an ephemeral agent workspace that may disappear.",
    ]
    if durable_sase:
        lines.append(
            f"  run it from the durable checkout      just -f {durable_sase}/Justfile "
            "install-dev"
        )
    else:
        lines.append(
            "  run it from a durable checkout      just -f <checkout>/Justfile "
            "install-dev"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class ProbeResult:
    """One prerequisite probe: a binary on PATH plus its version, if known."""

    name: str
    ok: bool
    version: str | None = None
    detail: str = ""


def _probe_version(argv: list[str], *, timeout: float) -> str | None:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    first_line = (completed.stdout.strip() or completed.stderr.strip()).splitlines()
    return first_line[0].strip() if first_line else None


def probe_uv() -> ProbeResult:
    """Probe the ``uv`` binary (required by both installer modes)."""
    path = shutil.which("uv")
    if path is None:
        return ProbeResult(
            name="uv",
            ok=False,
            detail=f"uv is not on PATH; install it from {UV_INSTALL_URL}",
        )
    version = _probe_version(["uv", "--version"], timeout=_UV_TIMEOUT_SECONDS)
    return ProbeResult(name="uv", ok=True, version=version, detail=path)


def probe_git() -> ProbeResult:
    """Probe the ``git`` binary (required by dev mode)."""
    path = shutil.which("git")
    if path is None:
        return ProbeResult(name="git", ok=False, detail="git is not on PATH")
    version = _probe_version(["git", "--version"], timeout=_GIT_TIMEOUT_SECONDS)
    return ProbeResult(name="git", ok=True, version=version, detail=path)


def probe_cargo() -> ProbeResult:
    """Probe the ``cargo`` binary (required by dev mode)."""
    path = shutil.which("cargo")
    if path is None:
        return ProbeResult(
            name="cargo",
            ok=False,
            detail="cargo is not on PATH; install rustup, or use `just install`",
        )
    version = _probe_version(["cargo", "--version"], timeout=_GIT_TIMEOUT_SECONDS)
    return ProbeResult(name="cargo", ok=True, version=version, detail=path)


def uv_tool_dir(*, uv: str = "uv") -> str | None:
    """Return ``uv tool dir`` stdout, or None when uv cannot answer."""
    try:
        completed = subprocess.run(
            [uv, "tool", "dir"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_UV_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    return text or None


def uv_tool_bin_dir(*, uv: str = "uv") -> str | None:
    """Return ``uv tool dir --bin`` stdout, or None when uv cannot answer."""
    try:
        completed = subprocess.run(
            [uv, "tool", "dir", "--bin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_UV_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    return text or None


def sase_home(env: Mapping[str, str] | None = None) -> Path:
    """Return the SASE state root (``$SASE_HOME`` or ``~/.sase``)."""
    source = os.environ if env is None else env
    raw = (source.get(SASE_HOME_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".sase"


def editable_overrides_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the uv editable-overrides path (mirrors ``sase``'s location)."""
    return sase_home(env=env) / "uv" / "editable-overrides.txt"


def colors_enabled(
    env: Mapping[str, str] | None = None, stream: object = None
) -> bool:
    """Return whether ANSI styling may be emitted."""
    source = os.environ if env is None else env
    if (source.get("NO_COLOR") or "") != "":
        return False
    if (source.get("TERM") or "") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    if callable(isatty):
        try:
            return bool(isatty())
        except (OSError, ValueError):
            return False
    return False


def terminal_width(
    env: Mapping[str, str] | None = None,
    stream: object = None,
    *,
    default: int = 80,
) -> int:
    """Return the panel width, clamped to 60\u2013100 columns."""
    source = os.environ if env is None else env
    raw = (source.get("COLUMNS") or "").strip()
    if raw.isdigit():
        width = int(raw)
    else:
        try:
            width = shutil.get_terminal_size(fallback=(default, 24)).columns
        except (OSError, ValueError):
            width = default
    return max(60, min(100, width))


def checkout_root_from_here(here: str | Path | None = None) -> Path:
    """Return the sase checkout root for a file inside ``tools/``."""
    anchor = Path(here) if here is not None else Path(__file__).resolve()
    if anchor.is_file():
        anchor = anchor.parent
    # ``tools/sase_install`` lives directly under the checkout root.
    if anchor.name == "tools":
        return anchor.parent
    return anchor


def resolve_core_dir(
    checkout_root: str | Path, env: Mapping[str, str] | None = None
) -> Path:
    """Return the sase-core checkout a dev install pairs with."""
    source = os.environ if env is None else env
    raw = (source.get(CORE_DIR_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(checkout_root) / ".." / "sase-core"


def read_pin_text(checkout_root: str | Path) -> str | None:
    """Return the raw ``sase-core-revision.txt`` contents, if readable."""
    try:
        text = (Path(checkout_root) / "sase-core-revision.txt").read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    return text.strip() or None


__all__ = [
    "AGENT_ENV_VARS",
    "BYPASS_ENV_VAR",
    "CORE_DIR_ENV_VAR",
    "CORE_REMOTE_ENV_VAR",
    "DISABLE_LOCK_ENV_VAR",
    "EXTERNAL_REPO_CLONES_SUBDIR",
    "LINKED_REPO_CLONES_SUBDIR",
    "SASE_HOME_ENV_VAR",
    "STALE_CORE_ENV_VAR",
    "UV_INSTALL_URL",
    "WORKSPACE_ROOT_ENV_VAR",
    "AgentGuard",
    "ProbeResult",
    "agent_bypass_note",
    "agent_guard",
    "agent_refusal_text",
    "checkout_root_from_here",
    "colors_enabled",
    "durable_dev_refusal_text",
    "editable_overrides_path",
    "is_ephemeral_path",
    "managed_workspace_root",
    "non_tty_text",
    "probe_cargo",
    "probe_git",
    "probe_uv",
    "read_pin_text",
    "resolve_core_dir",
    "sase_home",
    "terminal_width",
    "uv_tool_bin_dir",
    "uv_tool_dir",
]
