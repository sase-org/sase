from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.time import get_timezone
from sase.vcs_provider import get_vcs_provider
from sase.vcs_provider._registry import detect_vcs

LOG_FILE = os.path.expanduser("~/.sase_commit_stop_hook.jsonl")


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


def jlog(event: str, **kwargs: Any) -> None:
    """Public wrapper around the structured JSONL log helper."""
    _jlog(event, **kwargs)


def native_marker_path(session_id: str) -> Path:
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
    """Return (has_changes, changed_files, commit_instruction, details).

    ``commit_instruction`` is the trailing instruction sentence(s) and
    ``details`` is the full block (file list + instruction) that the native
    hook would emit. When the worktree is clean, both strings are empty.
    """
    has_changes, changed_files = _get_changed_files(project_dir)
    if not has_changes:
        return (False, [], "", "")

    skill = _resolve_commit_skill(project_dir)
    method = (
        commit_method
        if commit_method is not None
        else os.environ.get("SASE_COMMIT_METHOD", "")
    )
    resolved_bead = bead_id if bead_id is not None else os.environ.get("SASE_BEAD_ID")
    commit_instruction = _build_commit_instruction_message(skill, method, resolved_bead)
    name_instruction = _build_name_instruction()
    if name_instruction:
        commit_instruction += " " + name_instruction

    details = (
        "Uncommitted changes detected:\n"
        + "\n".join(changed_files)
        + f"\n\n{commit_instruction}"
    )
    return (True, changed_files, commit_instruction, details)


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


def _normalize_provider(provider: str | None) -> str:
    raw = (provider or "").strip().lower()
    if raw in {"", "auto"}:
        return "git"
    if raw in {"github", "bare_git", "git"}:
        return "git"
    if raw in {"google", "hg"}:
        return "hg"

    token = re.sub(r"[^a-z0-9_]", "_", raw)
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "git"


def _build_name_instruction() -> str | None:
    # Only PRs are named, since we need a branch name to associate with them.
    if os.environ.get("SASE_COMMIT_METHOD") != "create_pull_request":
        return None

    sase_name = os.environ.get("SASE_PR_NAME")
    sase_pr_name_is_set = True
    if not sase_name or sase_name == "None":
        sase_name = "<name>"
        sase_pr_name_is_set = False
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE", "")
    project = Path(project_file).stem if project_file else ""
    full_sase_name = sase_name
    if project and sase_pr_name_is_set:
        full_sase_name = f"{project}_{sase_name}"
    parts = [
        f'You MUST include `"name": "{full_sase_name}"` in your commit JSON payload.'
    ]
    if not sase_pr_name_is_set:
        parts.append(
            f"You should decide on what name to use for `{sase_name}` but it should be"
            " short, descriptive, and consist of lowercase letters and underscores."
        )
        if project:
            parts.append(
                f'Also, one more requirement: `{sase_name}` MUST start with "{project}_".'
            )
    return " ".join(parts)


def _build_commit_instruction_message(
    skill: str, commit_method: str, bead_id: str | None = None
) -> str:
    method = commit_method or "create_commit"
    resolved_bead_id = (bead_id or "").strip()
    parts = [
        "A post-completion hook has detected uncommitted changes.",
        "First decide whether the listed uncommitted changes were made by you in this session.",
        "If you did NOT make these changes, ignore this warning for the session; it will not appear again.",
    ]
    if resolved_bead_id:
        parts.append(
            f"If you DID make these changes, run `sase bead close {resolved_bead_id}` "
            f"and verify bead `{resolved_bead_id}` is closed before invoking the commit skill."
        )
        parts.append(
            f"Then commit the changes using your {skill} skill before continuing."
        )
    else:
        parts.append(
            f"If you DID make these changes, commit them using your {skill} skill before continuing."
        )
    parts.append(f"The commit method type is `{method}`.")
    if method != "create_pull_request":
        parts.append(
            "When constructing the commit message, describe only the changes in this commit."
        )
        parts.append(
            "Do NOT describe the entire pull request or unrelated planned work."
        )
    parts.append(
        f"You MUST use `--type {method}` or omit --type entirely to let the"
        " environment decide. Do NOT pass a --type value that conflicts with"
        " the stated method."
    )
    return " ".join(parts)


def _resolve_commit_skill(project_dir: str) -> str:
    explicit = os.environ.get("SASE_COMMIT_SKILL")
    if explicit:
        return explicit

    provider = os.environ.get("SASE_VCS_PROVIDER")
    if not provider or provider == "auto":
        provider = detect_vcs(project_dir)
    provider_token = _normalize_provider(provider)
    return f"/sase_{provider_token}_commit"


def _normalize_diff_path(path: str) -> str | None:
    p = path.strip()
    if not p or p == "/dev/null":
        return None
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p or None


def _changed_files_from_diff(diff_text: str) -> list[str]:
    files: set[str] = set()

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                candidate = _normalize_diff_path(parts[3])
                if candidate:
                    files.add(candidate)
            continue

        if line.startswith("rename to "):
            candidate = _normalize_diff_path(line.removeprefix("rename to "))
            if candidate:
                files.add(candidate)
            continue

        if line.startswith("+++ "):
            candidate = _normalize_diff_path(line.removeprefix("+++ "))
            if candidate:
                files.add(candidate)
            continue

        if line.startswith("Index: "):
            candidate = _normalize_diff_path(line.removeprefix("Index: "))
            if candidate:
                files.add(candidate)

    return sorted(files)


def _get_changed_files(project_dir: str) -> tuple[bool, list[str]]:
    try:
        provider = get_vcs_provider(project_dir)
    except Exception:
        return (False, [])

    diff_text: str | None = None
    try:
        ok, diff_text = provider.diff_with_untracked(project_dir, timeout=20)
        if not ok:
            diff_text = None
    except NotImplementedError:
        ok, diff_text = provider.diff(project_dir)
        if not ok:
            diff_text = None
    except Exception:
        diff_text = None

    changed_files = _changed_files_from_diff(diff_text or "")
    if changed_files:
        return (True, changed_files)

    try:
        ok, value = provider.has_local_changes(project_dir)
        if ok and (value or "").strip().lower() == "true":
            return (True, ["(unable to list changed files for this VCS provider)"])
    except NotImplementedError:
        pass
    except Exception:
        pass

    return (False, [])


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
    marker_file = native_marker_path(session_id)

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

    # Deduplication: Gemini and Qwen use stop_hook_active from stdin
    if runtime in ("gemini", "qwen") and hook_input.get("stop_hook_active"):
        _jlog(f"{runtime}_dedup_skip")
        return _exit(0, reason=f"{runtime}_dedup")

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
