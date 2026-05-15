"""Claude tool-call hook registration during SASE agent launch.

Registers the ``sase_claude_tool_hook`` collector as a Claude ``PreToolUse``
and ``PostToolUse`` hook for the duration of a SASE-managed Claude run by
merging entries into the workspace's ``.claude/settings.local.json``.

Design constraints (epic ``sase-3j``):

- Preserve existing user/project hook entries: SASE-managed entries carry a
  sentinel field so cleanup removes only our entries.
- Only mutate settings inside a SASE-managed workspace dir (resolved from
  ``SASE_GIT_WORKSPACE_DIR`` / ``SASE_CD_WORKSPACE_DIR`` /
  ``SASE_ACTIVE_PROJECT_DIR``). Home-mode launches yield ``False`` from the
  context manager and emit a diagnostic so the stream fallback stays visible.
- A killed/failed agent must not corrupt the file: writes are atomic via a
  temp file + ``os.replace``.
- Malformed pre-existing JSON is left untouched.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

from ._tool_calls import append_tool_call_collector_diagnostic

SASE_HOOK_SENTINEL = "_sase_managed"
SASE_HOOK_SENTINEL_VALUE = "tool-call-collector"
SASE_HOOK_COMMAND = "sase_claude_tool_hook"
SASE_HOOK_TIMEOUT_SECONDS = 10
SASE_HOOK_EVENTS: tuple[str, ...] = ("PreToolUse", "PostToolUse")

_WORKSPACE_ENV_VARS: tuple[str, ...] = (
    "SASE_GIT_WORKSPACE_DIR",
    "SASE_CD_WORKSPACE_DIR",
    "SASE_ACTIVE_PROJECT_DIR",
)


def resolve_workspace_dir() -> str | None:
    """Return the SASE-managed workspace dir, or ``None`` for home-mode launches.

    Home-mode runs don't set any of the workspace env vars, so we return
    ``None`` and the caller skips hook installation rather than mutating
    user-global settings under ``$HOME/.claude``.
    """
    for name in _WORKSPACE_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _settings_path(workspace_dir: str | os.PathLike[str]) -> Path:
    return Path(workspace_dir) / ".claude" / "settings.local.json"


def _build_sase_matcher_entry() -> dict[str, Any]:
    """Construct the matcher-entry Claude expects under ``hooks.<Event>[]``."""
    return {
        "matcher": "*",
        "hooks": [
            {
                "type": "command",
                "command": SASE_HOOK_COMMAND,
                "timeout": SASE_HOOK_TIMEOUT_SECONDS,
                SASE_HOOK_SENTINEL: SASE_HOOK_SENTINEL_VALUE,
            }
        ],
    }


def _is_managed_command(entry: Any) -> bool:
    return (
        isinstance(entry, Mapping)
        and entry.get(SASE_HOOK_SENTINEL) == SASE_HOOK_SENTINEL_VALUE
    )


def _is_pure_sase_matcher(entry: Any) -> bool:
    """True if the matcher entry only contains SASE-managed hook commands."""
    if not isinstance(entry, Mapping):
        return False
    inner = entry.get("hooks")
    if not isinstance(inner, list) or not inner:
        return False
    return all(_is_managed_command(cmd) for cmd in inner)


def _add_sase_hooks(settings: dict[str, Any]) -> None:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return
    for event in SASE_HOOK_EVENTS:
        bucket = hooks.setdefault(event, [])
        if not isinstance(bucket, list):
            continue
        bucket.append(_build_sase_matcher_entry())


def _remove_sase_hooks(settings: dict[str, Any]) -> None:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event in SASE_HOOK_EVENTS:
        bucket = hooks.get(event)
        if not isinstance(bucket, list):
            continue
        new_bucket: list[Any] = []
        for entry in bucket:
            if _is_pure_sase_matcher(entry):
                continue
            if isinstance(entry, Mapping):
                inner = entry.get("hooks")
                if isinstance(inner, list) and any(
                    _is_managed_command(cmd) for cmd in inner
                ):
                    pruned = [cmd for cmd in inner if not _is_managed_command(cmd)]
                    pruned_entry = dict(entry)
                    pruned_entry["hooks"] = pruned
                    new_bucket.append(pruned_entry)
                    continue
            new_bucket.append(entry)
        if new_bucket:
            hooks[event] = new_bucket
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)


def _load_existing(path: Path) -> tuple[dict[str, Any] | None, bool]:
    """Load ``settings.local.json``.

    Returns ``(parsed_object, malformed)``:
        - parsed_object is the dict if the file existed and parsed as an object.
        - ``malformed=True`` when the file exists but is not parseable as a JSON
          object — the caller must NOT overwrite user state in that case.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, True
    if not isinstance(data, dict):
        return None, True
    return data, False


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".sase_claude_settings.",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _diagnose(reason: str, **extra: Any) -> None:
    append_tool_call_collector_diagnostic(
        os.environ.get("SASE_ARTIFACTS_DIR"),
        reason=reason,
        extra=extra or None,
    )


@contextlib.contextmanager
def claude_hooks_session(
    workspace_dir: str | os.PathLike[str] | None,
    *,
    enabled: bool = True,
) -> Generator[bool, None, None]:
    """Install SASE tool-call hooks for the duration of the ``with`` block.

    Yields ``True`` when SASE hook entries were merged into
    ``.claude/settings.local.json``; ``False`` for home-mode/no-workspace
    launches and for cases where existing user state would have been
    clobbered (malformed JSON, unwritable file).

    On exit (including exceptions / process termination during cleanup), the
    SASE-managed entries are removed and the file is restored. If the file
    did not exist before the session and only SASE entries were present, the
    file (and possibly the ``.claude`` directory) is removed.
    """
    if not enabled or not workspace_dir:
        _diagnose(
            "claude_hooks_skipped",
            mode="home_mode_or_no_workspace",
            workspace_dir=str(workspace_dir) if workspace_dir else "",
        )
        yield False
        return

    path = _settings_path(workspace_dir)
    pre_existed = path.exists()
    existing, malformed = _load_existing(path)

    if malformed:
        _diagnose(
            "claude_hooks_skipped",
            mode="settings_file_malformed",
            settings_path=str(path),
        )
        yield False
        return

    base = existing if existing is not None else {}
    merged = copy.deepcopy(base)
    _add_sase_hooks(merged)

    try:
        _atomic_write(path, json.dumps(merged, indent=2) + "\n")
    except OSError as exc:
        _diagnose(
            "claude_hooks_skipped",
            mode="settings_file_unwritable",
            settings_path=str(path),
            error=str(exc),
        )
        yield False
        return

    try:
        yield True
    finally:
        _restore_settings(path, pre_existed=pre_existed)


def _restore_settings(path: Path, *, pre_existed: bool) -> None:
    current, malformed = _load_existing(path)
    if malformed:
        _diagnose(
            "claude_hooks_restore_skipped",
            mode="settings_file_malformed_on_restore",
            settings_path=str(path),
        )
        return
    if current is None:
        return
    _remove_sase_hooks(current)
    if not current and not pre_existed:
        with contextlib.suppress(OSError):
            path.unlink()
        parent = path.parent
        with contextlib.suppress(OSError):
            parent.rmdir()
        return
    try:
        _atomic_write(path, json.dumps(current, indent=2) + "\n")
    except OSError as exc:
        _diagnose(
            "claude_hooks_restore_failed",
            settings_path=str(path),
            error=str(exc),
        )
