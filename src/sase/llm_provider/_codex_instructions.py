"""Codex instruction, handoff, and executable helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sase.feature_flags import FeatureFlag, current_flags

from ._subprocess import CODEX_TURN_INTEGRITY_ERROR_PREFIX
from ._subprocess_codex import CodexStreamResult, CodexStrandedCommand

# Reasoning-effort levels Codex honors via ``-c model_reasoning_effort=...``.
# Codex rejects ``none``/``max`` (epic sase-55 provider support matrix). The
# quoted value mirrors the ``SASE_CODEX_LARGE_ARGS`` escape hatch exactly.
EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["-c", f'model_reasoning_effort="{level}"']
    for level in ("minimal", "low", "medium", "high", "xhigh")
}
CODEX_PATH_ENV = "SASE_CODEX_PATH"
CODEX_MAX_WAIT_CONTINUATIONS_ENV = "SASE_CODEX_MAX_WAIT_CONTINUATIONS"
DEFAULT_CODEX_MAX_WAIT_CONTINUATIONS = 2


def explicit_instructions_enabled() -> bool:
    """Return the current sunset-flag value for Codex instruction delivery."""
    return current_flags().enabled(FeatureFlag.codex_explicit_instructions)


def single_turn_directive() -> str:
    """Return the Codex developer instruction for unified-exec handoffs."""
    return (
        "SASE single-turn instructions for Codex: this session is exactly one turn, "
        "and nothing can wake you after you end it. `exec_command` returns control "
        "after its `yield_time_ms` even while the command keeps running. An empty or "
        "partial yielded result means the command is still running, not done. Anything "
        "still running when your turn ends is killed, so its intended effects never "
        "happen. Handoff commands such as `sase monitor start`, `sase plan propose`, "
        "`sase pipe`, and `sase questions` can take up to a minute before they hand off. "
        "Wait for the handoff command itself to exit: if a yielded exec session remains "
        "running, repeatedly call `write_stdin` with empty input until it reports an "
        "exit code. Never end your turn while one is running. The monitored command is "
        "different: let SASE monitor that command after `sase monitor start` exits."
    )


def max_wait_continuations() -> int:
    """Return the bounded stranded-handoff continuation budget."""
    raw_value = os.environ.get(CODEX_MAX_WAIT_CONTINUATIONS_ENV)
    if raw_value is None:
        return DEFAULT_CODEX_MAX_WAIT_CONTINUATIONS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return DEFAULT_CODEX_MAX_WAIT_CONTINUATIONS


def stranded_handoff_continuation_nudge(
    commands: tuple[CodexStrandedCommand, ...],
) -> str:
    """Tell a fresh Codex invocation how to recover the killed handoff."""
    command = next((fact.command for fact in commands if fact.command), None)
    command_label = command or commands[0].command_id
    return (
        "Your previous Codex turn ended while this SASE handoff command was still "
        f"running: `{command_label}`. It was killed when the turn ended, and no monitor "
        "or handoff took effect. Re-run the identical command so fingerprint replay can "
        "adopt any partially started monitor. Keep waiting on the same exec session: if "
        "the tool yields before an exit code, repeatedly call `write_stdin` with empty "
        "input until the command exits. Do not end the turn while it is running."
    )


def coerce_stream_result(
    value: CodexStreamResult | tuple[str, str, int],
) -> CodexStreamResult:
    """Preserve test and plugin compatibility with legacy parser triples."""
    if isinstance(value, CodexStreamResult):
        return value
    content, stderr_content, return_code = value
    return CodexStreamResult(content, stderr_content, return_code)


def resolve_codex_executable() -> str:
    """Return the Codex executable SASE should launch."""
    explicit_path = os.environ.get(CODEX_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which("codex")
    if path_result:
        return path_result

    nvm_bin = os.environ.get("NVM_BIN")
    if nvm_bin:
        nvm_codex = Path(nvm_bin) / "codex"
        if nvm_codex.exists():
            return str(nvm_codex)

    return "codex"


def codex_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Codex diagnostic."""
    return FileNotFoundError(
        "Unable to launch Codex CLI executable "
        f"{command!r}. Set SASE_CODEX_PATH to the Codex binary, ensure "
        "'codex' is discoverable on PATH, or set NVM_BIN so SASE can try "
        "NVM_BIN/codex."
    )


def log_interrupt(message: str, cycle: int) -> None:
    """Append an entry to the interrupt log in the artifacts directory."""
    import json
    import time

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    log_path = Path(artifacts_dir) / "interrupt_log.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(
                {"message": message, "timestamp": time.time(), "cycle": cycle},
                f,
            )
            f.write("\n")
    except OSError:
        pass


__all__ = [
    "CODEX_MAX_WAIT_CONTINUATIONS_ENV",
    "CODEX_PATH_ENV",
    "CODEX_TURN_INTEGRITY_ERROR_PREFIX",
    "DEFAULT_CODEX_MAX_WAIT_CONTINUATIONS",
    "EFFORT_CLI_ARGS",
    "coerce_stream_result",
    "codex_executable_not_found_error",
    "explicit_instructions_enabled",
    "log_interrupt",
    "max_wait_continuations",
    "resolve_codex_executable",
    "single_turn_directive",
    "stranded_handoff_continuation_nudge",
]
