"""Launch-time resolution for clan summary scripts."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import os
from pathlib import Path
import signal
import shlex
import subprocess
import tempfile
from typing import BinaryIO

from sase.axe.chop_script_runner import discover_chop_script

log = logging.getLogger(__name__)

CLAN_SUMMARY_MAX_BYTES = 32 * 1024
CLAN_SUMMARY_TIMEOUT_SECONDS = 20.0

_CLAN_ENV_NAMES = (
    "SASE_CLAN_NAME",
    "SASE_CLAN_GENERATION",
    "SASE_CLAN_TRIBE",
)


def normalize_clan_summary(summary: str) -> str | None:
    """Strip trailing whitespace and cap one summary to 32 KiB of UTF-8."""
    normalized = summary.rstrip()
    if not normalized:
        return None
    encoded = normalized.encode("utf-8")
    if len(encoded) <= CLAN_SUMMARY_MAX_BYTES:
        return normalized
    return encoded[:CLAN_SUMMARY_MAX_BYTES].decode("utf-8", errors="ignore").rstrip()


def resolve_clan_summary_script(
    script: str,
    *,
    workspace_dir: str,
    clan_name: str,
    clan_generation: str,
    clan_tribe: str | None,
    agent_log_path: str | None = None,
    timeout_seconds: float | None = None,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Run *script* once and return its bounded summary, or ``None``.

    Every discovery and execution failure is downgraded to a warning so a
    decorative clan summary can never prevent the declaring agent from
    launching.
    """
    try:
        script_argv = _resolve_summary_script_argv(script, workspace_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning(
            "Clan summary script %r could not be resolved (%s); omitting summary",
            script,
            exc,
        )
        return None
    if script_argv is None:
        log.warning("Clan summary script %r was not found; omitting summary", script)
        return None

    subprocess_env = dict(os.environ if environment is None else environment)
    for env_name in _CLAN_ENV_NAMES:
        subprocess_env.pop(env_name, None)
    subprocess_env["SASE_CLAN_NAME"] = clan_name
    subprocess_env["SASE_CLAN_GENERATION"] = clan_generation
    if clan_tribe:
        subprocess_env["SASE_CLAN_TRIBE"] = clan_tribe

    timeout = (
        CLAN_SUMMARY_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
    try:
        with tempfile.TemporaryFile() as stdout_file:
            log_file = _open_agent_log(agent_log_path)
            try:
                process = subprocess.Popen(
                    script_argv,
                    cwd=workspace_dir,
                    env=subprocess_env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=log_file,
                    start_new_session=os.name == "posix",
                )
                try:
                    returncode = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_process(process)
                    log.warning(
                        "Clan summary script %r timed out after %.1fs; "
                        "omitting summary",
                        script,
                        timeout,
                    )
                    return None
            finally:
                if log_file is not None:
                    log_file.close()

            if returncode != 0:
                log.warning(
                    "Clan summary script %r exited with status %s; omitting summary",
                    script,
                    returncode,
                )
                return None

            stdout_file.seek(0)
            raw_output = stdout_file.read(CLAN_SUMMARY_MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        log.warning(
            "Clan summary script %r could not run (%s); omitting summary",
            script,
            exc,
        )
        return None

    summary = normalize_clan_summary(raw_output.decode("utf-8", errors="replace"))
    if summary is None:
        log.warning(
            "Clan summary script %r produced no output; omitting summary", script
        )
        return None
    if len(raw_output) > CLAN_SUMMARY_MAX_BYTES:
        log.warning(
            "Clan summary script %r output exceeded 32 KiB and was truncated",
            script,
        )
    return summary


def _discover_summary_script(script: str, workspace_dir: str) -> Path | None:
    if "/" not in script:
        return discover_chop_script(script, [])

    expanded = Path(script).expanduser()
    candidate = expanded if expanded.is_absolute() else Path(workspace_dir) / expanded
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def _resolve_summary_script_argv(
    script: str,
    workspace_dir: str,
) -> list[str] | None:
    """Resolve a literal executable first, then shell-quote argv without a shell."""
    literal = _discover_summary_script(script, workspace_dir)
    if literal is not None:
        return [str(literal)]

    tokens = shlex.split(script)
    if not tokens:
        raise ValueError("summary_script produced an empty argv")
    executable = _discover_summary_script(tokens[0], workspace_dir)
    if executable is None:
        return None
    return [str(executable), *tokens[1:]]


def _open_agent_log(agent_log_path: str | None) -> BinaryIO | None:
    if agent_log_path is None:
        return None
    try:
        return open(agent_log_path, "ab")
    except OSError as exc:
        log.warning(
            "Could not append clan summary stderr to agent log %r (%s)",
            agent_log_path,
            exc,
        )
        return None


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


__all__ = [
    "CLAN_SUMMARY_MAX_BYTES",
    "CLAN_SUMMARY_TIMEOUT_SECONDS",
    "normalize_clan_summary",
    "resolve_clan_summary_script",
]
