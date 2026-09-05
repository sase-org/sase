"""Launch-time resolution for clan summary scripts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
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
CLAN_SUMMARY_KILL_GRACE_SECONDS = 3.0
CLAN_SUMMARY_STDERR_LOG = "clan_summary_stderr.log"
DEFAULT_CLAN_SUMMARY_ATTEMPT_LABEL = "directive-extraction"
POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL = "post-workspace-preparation"

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
    artifacts_dir: str | None = None,
    attempt_label: str = DEFAULT_CLAN_SUMMARY_ATTEMPT_LABEL,
    timeout_seconds: float | None = None,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Run *script* once and return its bounded summary, or ``None``.

    Every discovery and execution failure is downgraded to a warning so a
    decorative clan summary can never prevent the clan member from launching.
    """
    subprocess_env = _summary_subprocess_env(
        environment=environment,
        clan_name=clan_name,
        clan_generation=clan_generation,
        clan_tribe=clan_tribe,
    )
    try:
        script_argv = _resolve_summary_script_argv(script, workspace_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        diagnostic = f"resolution error: {exc}\n"
        _record_summary_attempt(
            artifacts_dir=artifacts_dir,
            attempt_label=attempt_label,
            script_argv=None,
            outcome="not-found",
            env=subprocess_env,
            stderr_text=diagnostic,
        )
        log.warning(
            "Clan summary script %r could not be resolved (%s); omitting summary%s",
            script,
            exc,
            _stderr_tail_suffix(diagnostic),
        )
        return None
    if script_argv is None:
        diagnostic = f"summary script {script!r} was not found\n"
        _record_summary_attempt(
            artifacts_dir=artifacts_dir,
            attempt_label=attempt_label,
            script_argv=None,
            outcome="not-found",
            env=subprocess_env,
            stderr_text=diagnostic,
        )
        log.warning(
            "Clan summary script %r was not found; omitting summary%s",
            script,
            _stderr_tail_suffix(diagnostic),
        )
        return None

    timeout = (
        CLAN_SUMMARY_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
    _ensure_agent_log(agent_log_path)
    try:
        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            process = subprocess.Popen(
                script_argv,
                cwd=workspace_dir,
                env=subprocess_env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=os.name == "posix",
            )
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_process(process)
                stderr_text = _read_temp_file_text(stderr_file)
                _finish_summary_attempt(
                    agent_log_path=agent_log_path,
                    artifacts_dir=artifacts_dir,
                    attempt_label=attempt_label,
                    script_argv=script_argv,
                    outcome="timeout",
                    env=subprocess_env,
                    stderr_text=stderr_text,
                )
                log.warning(
                    "Clan summary script %r timed out after %.1fs; omitting summary%s",
                    script,
                    timeout,
                    _stderr_tail_suffix(stderr_text),
                )
                return None

            stderr_text = _read_temp_file_text(stderr_file)

            if returncode != 0:
                _finish_summary_attempt(
                    agent_log_path=agent_log_path,
                    artifacts_dir=artifacts_dir,
                    attempt_label=attempt_label,
                    script_argv=script_argv,
                    outcome="exit-code",
                    env=subprocess_env,
                    stderr_text=stderr_text,
                )
                log.warning(
                    "Clan summary script %r exited with status %s; omitting summary%s",
                    script,
                    returncode,
                    _stderr_tail_suffix(stderr_text),
                )
                return None

            stdout_file.seek(0)
            raw_output = stdout_file.read(CLAN_SUMMARY_MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        diagnostic = f"execution error: {exc}\n"
        _record_summary_attempt(
            artifacts_dir=artifacts_dir,
            attempt_label=attempt_label,
            script_argv=script_argv,
            outcome="exit-code",
            env=subprocess_env,
            stderr_text=diagnostic,
        )
        log.warning(
            "Clan summary script %r could not run (%s); omitting summary%s",
            script,
            exc,
            _stderr_tail_suffix(diagnostic),
        )
        return None

    summary = normalize_clan_summary(raw_output.decode("utf-8", errors="replace"))
    if summary is None:
        _finish_summary_attempt(
            agent_log_path=agent_log_path,
            artifacts_dir=artifacts_dir,
            attempt_label=attempt_label,
            script_argv=script_argv,
            outcome="empty-output",
            env=subprocess_env,
            stderr_text=stderr_text,
        )
        log.warning(
            "Clan summary script %r produced no output; omitting summary%s",
            script,
            _stderr_tail_suffix(stderr_text),
        )
        return None
    if len(raw_output) > CLAN_SUMMARY_MAX_BYTES:
        log.warning(
            "Clan summary script %r output exceeded 32 KiB and was truncated",
            script,
        )
    _finish_summary_attempt(
        agent_log_path=agent_log_path,
        artifacts_dir=artifacts_dir,
        attempt_label=attempt_label,
        script_argv=script_argv,
        outcome="ok",
        env=subprocess_env,
        stderr_text=stderr_text,
    )
    return summary


def _summary_subprocess_env(
    *,
    environment: Mapping[str, str] | None,
    clan_name: str,
    clan_generation: str,
    clan_tribe: str | None,
) -> dict[str, str]:
    subprocess_env = dict(os.environ if environment is None else environment)
    for env_name in _CLAN_ENV_NAMES:
        subprocess_env.pop(env_name, None)
    subprocess_env["SASE_CLAN_NAME"] = clan_name
    subprocess_env["SASE_CLAN_GENERATION"] = clan_generation
    if clan_tribe:
        subprocess_env["SASE_CLAN_TRIBE"] = clan_tribe
    return subprocess_env


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


def _finish_summary_attempt(
    *,
    agent_log_path: str | None,
    artifacts_dir: str | None,
    attempt_label: str,
    script_argv: list[str],
    outcome: str,
    env: Mapping[str, str],
    stderr_text: str,
) -> None:
    if stderr_text:
        _append_agent_log(agent_log_path, stderr_text)
    if outcome == "ok" and not stderr_text:
        return
    _record_summary_attempt(
        artifacts_dir=artifacts_dir,
        attempt_label=attempt_label,
        script_argv=script_argv,
        outcome=outcome,
        env=env,
        stderr_text=stderr_text,
    )


def _append_agent_log(agent_log_path: str | None, stderr_text: str) -> None:
    if agent_log_path is None or not stderr_text:
        return
    try:
        with open(agent_log_path, "ab") as log_file:
            log_file.write(stderr_text.encode("utf-8", errors="replace"))
    except OSError as exc:
        log.warning(
            "Could not append clan summary stderr to agent log %r (%s)",
            agent_log_path,
            exc,
        )


def _ensure_agent_log(agent_log_path: str | None) -> None:
    if agent_log_path is None:
        return
    try:
        with open(agent_log_path, "ab"):
            pass
    except OSError as exc:
        log.warning(
            "Could not open clan summary stderr agent log %r (%s)",
            agent_log_path,
            exc,
        )


def _record_summary_attempt(
    *,
    artifacts_dir: str | None,
    attempt_label: str,
    script_argv: list[str] | None,
    outcome: str,
    env: Mapping[str, str],
    stderr_text: str,
) -> None:
    if artifacts_dir is None:
        return

    log_path = Path(artifacts_dir) / CLAN_SUMMARY_STDERR_LOG
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    argv = "<not resolved>" if script_argv is None else shlex.join(script_argv)
    env_names = _present_summary_env_names(env)
    env_line = ", ".join(env_names) if env_names else "(none)"
    record = (
        "--- clan summary attempt ---\n"
        f"timestamp: {timestamp}\n"
        f"attempt: {attempt_label}\n"
        f"outcome: {outcome}\n"
        f"argv: {argv}\n"
        f"env: {env_line}\n"
        "stderr:\n"
        f"{stderr_text.rstrip()}\n"
        "\n"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(record)
    except OSError as exc:
        log.warning(
            "Could not write clan summary stderr artifact %r (%s)",
            str(log_path),
            exc,
        )


def _present_summary_env_names(env: Mapping[str, str]) -> list[str]:
    return sorted(
        key
        for key in env
        if key.startswith("SASE_CLAN_") or key.startswith("SASE_EPIC_")
    )


def _read_temp_file_text(file: BinaryIO) -> str:
    file.seek(0)
    raw_stderr = file.read()
    return raw_stderr.decode("utf-8", errors="replace")


def _stderr_tail_suffix(stderr_text: str) -> str:
    tail = _stderr_tail(stderr_text)
    if not tail:
        return ""
    return f"; stderr tail: {tail}"


def _stderr_tail(stderr_text: str, *, max_lines: int = 8) -> str:
    lines = [line.rstrip() for line in stderr_text.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    return " | ".join(lines[-max_lines:])


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM the process group, then SIGKILL leftovers after a short grace."""
    _signal_process_group(process, signal.SIGTERM, fallback_kill=False)
    try:
        process.wait(timeout=CLAN_SUMMARY_KILL_GRACE_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    _signal_process_group(process, signal.SIGKILL, fallback_kill=True)
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _signal_process_group(
    process: subprocess.Popen[bytes],
    sig: int,
    *,
    fallback_kill: bool,
) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
            return
        if fallback_kill:
            process.kill()
        else:
            process.terminate()
    except OSError:
        try:
            if fallback_kill:
                process.kill()
            else:
                process.terminate()
        except OSError:
            pass


__all__ = [
    "CLAN_SUMMARY_KILL_GRACE_SECONDS",
    "CLAN_SUMMARY_MAX_BYTES",
    "CLAN_SUMMARY_STDERR_LOG",
    "CLAN_SUMMARY_TIMEOUT_SECONDS",
    "POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL",
    "normalize_clan_summary",
    "resolve_clan_summary_script",
]
