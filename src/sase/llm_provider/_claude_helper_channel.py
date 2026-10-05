"""Claude native-helper channel: template path, guard settings, and probe.

On every Claude invocation cycle SASE passes a packaged static helper
template through the hidden ``--append-subagent-system-prompt-file`` flag
(when the CLI supports it) and an inline ``--settings`` JSON blob carrying a
stdlib-only PreToolUse guard on ``Bash|Skill``. Both are gated by the
``claude_helper_channel`` sunset flag; the template flag is additionally
gated by a cached no-API capability probe.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

SubagentPromptSupport = Literal["supported", "unknown", "unsupported"]

HELPER_TEMPLATE_FIRST_LINE = "# SASE Helper Instructions"
_HELPER_TEMPLATE_RESOURCE = "templates/claude_helper_instructions.md"
_HELPER_GUARD_RESOURCE = "_claude_helper_guard.py"

_CAPABILITY_PROVIDER = "claude_helper_channel"
_PROBE_TIMEOUT_SECONDS = 20.0
_GUARD_HOOK_TIMEOUT_SECONDS = 10


def claude_helper_channel_enabled() -> bool:
    """Return whether the Claude helper channel flag is on.

    Falls back to the registry default (on for a sunset flag) when the flag
    cannot be resolved, so a broken flag snapshot fails toward the guarded
    channel rather than silently dropping it.
    """
    try:
        from sase.feature_flags import FeatureFlag, current_flags
        from sase.feature_flags.models import FeatureFlagError

        return current_flags().enabled(FeatureFlag.claude_helper_channel)
    except FeatureFlagError:
        return True
    except Exception:  # noqa: BLE001 - never let flag resolution break invoke.
        log.debug("Claude helper channel flag lookup failed", exc_info=True)
        return True


def helper_template_path() -> Path:
    """Return the installed helper-template path (no per-run temp file)."""
    return Path(
        str(
            resources.files("sase.llm_provider").joinpath(
                *_HELPER_TEMPLATE_RESOURCE.split("/")
            )
        )
    )


def _helper_guard_path() -> Path:
    """Return the installed stdlib-only guard script path."""
    return Path(
        str(resources.files("sase.llm_provider").joinpath(_HELPER_GUARD_RESOURCE))
    )


def helper_channel_settings_json() -> str:
    """Return the inline ``--settings`` JSON carrying the PreToolUse guard."""
    command = (
        f"{shlex.quote(sys.executable)} -I "
        f"{shlex.quote(os.fspath(_helper_guard_path()))}"
    )
    return json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash|Skill",
                        "hooks": [
                            {
                                "type": "command",
                                "command": command,
                                "timeout": _GUARD_HOOK_TIMEOUT_SECONDS,
                            }
                        ],
                    }
                ]
            }
        }
    )


def _resolve_claude_executable(explicit: str | None = None) -> str | None:
    """Return the resolved ``claude`` executable path, if it exists."""
    candidates = [explicit] if explicit else []
    candidates.append(shutil.which("claude") or "claude")
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def probe_subagent_prompt_uncached(
    executable: str | None = None,
    *,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> tuple[SubagentPromptSupport, str]:
    """Probe ``--append-subagent-system-prompt-file`` support without an API call.

    Runs ``claude -p --append-subagent-system-prompt-file <nonexistent>``
    with empty stdin: ``file not found`` means the flag parses (supported),
    ``unknown option`` means it does not (unsupported), and anything else —
    including timeouts and missing binaries — is unknown.
    """
    command = executable or _resolve_claude_executable()
    if not command:
        return "unknown", "claude executable was not found on PATH"
    probe_target = "/nonexistent/sase-helper-probe.md"
    try:
        result = subprocess.run(
            [command, "-p", "--append-subagent-system-prompt-file", probe_target],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "unknown", f"probe timed out after {timeout:g}s"
    except OSError as exc:
        return "unknown", f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - the probe must never break invoke.
        return "unknown", f"{type(exc).__name__}: {exc}"
    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "unknown option" in combined:
        return "unsupported", _first_line(result.stdout, result.stderr)
    if "not found" in combined:
        return "supported", _first_line(result.stdout, result.stderr)
    return "unknown", _first_line(result.stdout, result.stderr) or (
        f"exited {result.returncode}"
    )


def _first_line(stdout: str | None, stderr: str | None) -> str:
    """Return the first non-empty output line of a probe run."""
    for text in (stdout or "", stderr or ""):
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    return ""


def subagent_prompt_supported(executable: str | None = None) -> bool:
    """Return whether the hidden subagent flag parses, using the cache.

    The result is cached by resolved executable path plus its mtime and size
    (the usage-preflight cache pattern under a dedicated provider key so the
    usage probe entry is never clobbered). Cache failures degrade to a live
    probe, never to a channel failure.
    """
    from sase.llm_provider.usage._capability_cache import (
        executable_fingerprint,
        read_probe_capability,
        write_probe_capability,
    )

    command = executable or _resolve_claude_executable()
    fingerprint = executable_fingerprint(command)
    if fingerprint is not None:
        try:
            cached = read_probe_capability(_CAPABILITY_PROVIDER, fingerprint)
        except Exception:  # noqa: BLE001 - cache failures degrade to a miss.
            cached = None
        if isinstance(cached, dict) and cached.get("outcome") in (
            "supported",
            "unsupported",
            "unknown",
        ):
            return cached["outcome"] == "supported"
    outcome, _ = probe_subagent_prompt_uncached(command)
    if fingerprint is not None:
        try:
            write_probe_capability(
                _CAPABILITY_PROVIDER, fingerprint, {"outcome": outcome}
            )
        except Exception:  # noqa: BLE001 - never let caching break invoke.
            log.debug("Claude helper channel capability cache write failed")
    return outcome == "supported"


__all__ = [
    "HELPER_TEMPLATE_FIRST_LINE",
    "SubagentPromptSupport",
    "claude_helper_channel_enabled",
    "helper_channel_settings_json",
    "helper_template_path",
    "probe_subagent_prompt_uncached",
    "subagent_prompt_supported",
]
