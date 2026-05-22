"""Compatibility-only provider-native commit stop hook.

SASE-owned agent runs now use the provider-neutral commit finalizer in the
LLM invocation layer. This script remains for older external hook configs and
for tests that exercise the compatibility wrapper directly.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.commit_instructions import (
    build_commit_instruction_message as _build_commit_instruction_message,
    build_name_instruction_text as _build_name_instruction,
    build_commit_details as _build_commit_details,
    changed_files_from_diff as _changed_files_from_diff,
    get_changed_files_for_commit as _get_changed_files,
    normalize_diff_path as _normalize_diff_path,
    normalize_provider_token as _normalize_provider,
    resolve_commit_skill_name as _resolve_commit_skill,
)
from sase.core.time import get_timezone

LOG_FILE = os.path.expanduser("~/.sase_commit_stop_hook.jsonl")

__all__ = [
    "_build_commit_instruction_message",
    "_build_name_instruction",
    "_changed_files_from_diff",
    "_get_changed_files",
    "_normalize_diff_path",
    "_normalize_provider",
    "_resolve_commit_skill",
    "build_commit_details",
    "main",
    "_native_marker_path",
]


def _jlog(event: str, **kwargs: Any) -> None:
    """Append a structured JSON log line to ~/.sase_commit_stop_hook.jsonl."""
    record: dict[str, Any] = {
        "timestamp": datetime.now(get_timezone()).replace(microsecond=0).isoformat(),
        "event": event,
        **kwargs,
    }
    try:
        with open(LOG_FILE, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(record, default=str) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass


def _native_marker_path(session_id: str) -> Path:
    """Return the native commit-hook dedup marker path for *session_id*."""
    return (
        Path(os.environ.get("SASE_TMPDIR", "/tmp"))
        / f"sase_commit_hook_done_{session_id}"
    )


def build_commit_details(
    project_dir: str,
    *,
    commit_method: str | None = None,
    bead_id: str | None = None,
) -> tuple[bool, list[str], str, str]:
    """Return the shared commit details, honoring monkeypatchable hook helpers."""
    return _build_commit_details(
        project_dir,
        commit_method=commit_method,
        bead_id=bead_id,
        get_changed_files=_get_changed_files,
        resolve_commit_skill=_resolve_commit_skill,
        build_name_instruction=_build_name_instruction,
    )


def _resolve_project_dir() -> str:
    for key in (
        "CLAUDE_PROJECT_DIR",
        "QWEN_PROJECT_DIR",
        "GEMINI_PROJECT_DIR",
        "CODEX_PROJECT_DIR",
    ):
        candidate = os.environ.get(key)
        if candidate and os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def _is_codex_runtime() -> bool:
    return bool(os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_CI"))


def _is_qwen_runtime() -> bool:
    return bool(os.environ.get("QWEN_PROJECT_DIR"))


def _is_gemini_runtime() -> bool:
    # Qwen Code (a Gemini fork) also sets GEMINI_PROJECT_DIR, so a Qwen
    # session must be excluded here to avoid mislabeling it as Gemini.
    return bool(os.environ.get("GEMINI_PROJECT_DIR")) and not _is_qwen_runtime()


def _read_hook_stdin() -> dict:
    """Read stop-hook metadata piped on stdin (Claude/Gemini/Codex/Qwen/opencode)."""
    if sys.stdin.isatty():
        return {}
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return {}


def _resolve_session_id(hook_input: dict) -> str:
    sase_ts = os.environ.get("SASE_AGENT_TIMESTAMP")
    if sase_ts:
        return sase_ts

    stdin_sid = hook_input.get("session_id") or hook_input.get("sessionId") or ""
    if stdin_sid:
        return f"stdin-{stdin_sid}"

    codex_tid = os.environ.get("CODEX_THREAD_ID")
    if codex_tid:
        return f"codex-{codex_tid}"

    try:
        tty_path = os.ttyname(0)
    except OSError:
        tty_path = ""
    if tty_path:
        import hashlib

        digest = hashlib.md5(tty_path.encode()).hexdigest()[:12]
        return f"tty-{digest}"

    return f"pid-{os.getpid()}"


def _emit_block(reason: str, details: str | None = None) -> int:
    if _is_codex_runtime():
        print(
            json.dumps(
                {"decision": "block", "reason": details or reason}, ensure_ascii=True
            )
        )
        if details:
            print(details, file=sys.stderr)
        return 0

    if _is_gemini_runtime() or _is_qwen_runtime():
        print(json.dumps({"decision": "deny", "reason": details or reason}))
        return 0

    print(details or reason, file=sys.stderr)
    return 2


def _log_hook_run(project_dir: str) -> None:
    claude_dir = Path(project_dir) / ".claude"
    if not claude_dir.is_dir():
        return

    method = os.environ.get("SASE_COMMIT_METHOD", "create_commit")
    log_file = claude_dir / "hooks.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(
            f"[{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        )
        f.write(f"sase_commit_stop_hook ran (method={method})\\n")


def main() -> int:
    t0 = time.monotonic()

    def _exit(code: int, event: str = "script_exit", **extra: Any) -> int:
        _jlog(
            event, exit_code=code, duration_s=round(time.monotonic() - t0, 3), **extra
        )
        return code

    runtime = (
        "qwen"
        if _is_qwen_runtime()
        else "gemini"
        if _is_gemini_runtime()
        else "codex"
        if _is_codex_runtime()
        else "claude"
    )
    commit_method = os.environ.get("SASE_COMMIT_METHOD", "")

    if os.environ.get("SASE_DISABLE_COMMIT_STOP_HOOK"):
        _jlog("disabled", runtime=runtime)
        return _exit(0, reason="disabled")

    project_dir = _resolve_project_dir()
    os.chdir(project_dir)

    hook_input = _read_hook_stdin()
    session_id = _resolve_session_id(hook_input)
    marker_file = _native_marker_path(session_id)

    _jlog(
        "script_start",
        runtime=runtime,
        project_dir=project_dir,
        commit_method=commit_method,
        pid=os.getpid(),
        session_id=session_id,
    )

    _log_hook_run(project_dir)

    if marker_file.exists():
        _jlog("session_dedup_skip", marker=str(marker_file))
        return _exit(0, reason="session_dedup")

    # Gemini's AfterAgent hook may re-enter with stop_hook_active set. Qwen
    # fires the Claude-style Stop event and may set the same field on the first
    # stop payload, so Qwen dedups only through the marker file above.
    if runtime == "gemini" and hook_input.get("stop_hook_active"):
        _jlog("gemini_dedup_skip")
        return _exit(0, reason="gemini_dedup")

    has_changes, changed_files, commit_instruction, details = build_commit_details(
        project_dir, commit_method=commit_method
    )
    _jlog(
        "changes_check",
        has_changes=has_changes,
        num_files=len(changed_files),
        files=changed_files[:20],
    )

    if not has_changes:
        return _exit(0, reason="no_changes")

    marker_file.touch()
    rc = _emit_block(
        "Stop hook blocked: uncommitted changes remain.",
        details,
    )
    _jlog(
        "block_emitted",
        exit_code=rc,
        num_files=len(changed_files),
        commit_instruction=commit_instruction,
    )
    return _exit(rc, reason="block_emitted")


if __name__ == "__main__":
    raise SystemExit(main())
