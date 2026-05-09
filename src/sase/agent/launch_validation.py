"""Pre-spawn validation for permanent agent-name launches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "AgentNameLaunchCollisionError",
    "AgentNameReuseConfirmationRequiredError",
    "force_reuse_owner_names",
    "launch_prompts_need_force_reuse_confirmation",
    "rewrite_force_reuse_name_directives",
    "validate_launch_name_requests",
    "wipe_names_for_forced_reuse",
]


@dataclass(frozen=True)
class _LaunchNameRequest:
    """Explicit agent name requested by one launch prompt."""

    name: str
    force_reuse: bool
    prompt_index: int


class _LaunchNameValidationError(RuntimeError):
    """Base class for launch-name validation failures."""


class AgentNameLaunchCollisionError(_LaunchNameValidationError):
    """Raised when a launch tries to reuse an already reserved name."""

    def __init__(self, name: str, suggestion: str) -> None:
        self.name = name
        self.suggestion = suggestion
        super().__init__(f"Agent name '{name}' is taken. Try '{suggestion}'.")


class AgentNameReuseConfirmationRequiredError(_LaunchNameValidationError):
    """Raised when a non-TUI surface submits ``%name:!<name>``."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Agent name '{name}' uses forced reuse; confirmation is required."
        )


def _explicit_launch_name_requests(prompts: list[str]) -> list[_LaunchNameRequest]:
    """Return explicit ``%name`` requests from already-expanded launch prompts."""
    requests: list[_LaunchNameRequest] = []
    for i, prompt in enumerate(prompts):
        parsed = _extract_explicit_name(prompt)
        if parsed is None:
            continue
        name, force_reuse = parsed
        requests.append(
            _LaunchNameRequest(name=name, force_reuse=force_reuse, prompt_index=i)
        )
    return requests


def launch_prompts_need_force_reuse_confirmation(prompts: list[str]) -> bool:
    """Return whether any prompt contains a forced-reuse name directive."""
    return any(
        request.force_reuse for request in _explicit_launch_name_requests(prompts)
    )


def validate_launch_name_requests(
    prompts: list[str],
    *,
    allow_force_reuse: bool = False,
) -> None:
    """Validate explicit launch names under the global name allocation lock."""
    requests = _explicit_launch_name_requests(prompts)
    if not requests:
        return

    from sase.agent.names import (
        agent_name_allocation_lock,
        is_name_reserved,
        lowest_name_suggestion,
    )

    seen: set[str] = set()
    with agent_name_allocation_lock():
        for request in requests:
            if request.force_reuse and not allow_force_reuse:
                raise AgentNameReuseConfirmationRequiredError(request.name)
            if request.force_reuse:
                continue
            if request.name in seen or is_name_reserved(request.name):
                raise AgentNameLaunchCollisionError(
                    request.name, lowest_name_suggestion(request.name)
                )
            seen.add(request.name)


def rewrite_force_reuse_name_directives(prompt: str) -> str:
    """Rewrite ``%name:!foo``/``%name(!foo)`` to normal ``%name:foo`` forms."""
    if "%n" not in prompt and "%name" not in prompt:
        return prompt

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)
    replacements: list[tuple[int, int, str]] = []

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_directive = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_directive, raw_directive) != "name":
            continue

        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is None:
                continue
            inner = protected[paren_start + 1 : paren_end]
            positional_args, _ = parse_args(inner)
            if not positional_args or not positional_args[0].startswith("!"):
                continue
            name = positional_args[0][1:]
            replacements.append(
                (match.start(), paren_end + 1, f"%{raw_directive}:{name}")
            )
        elif match.group(3) is not None:
            raw_arg = match.group(3)
            if raw_arg.startswith("`") and raw_arg.endswith("`"):
                value = raw_arg[1:-1]
                if not value.startswith("!"):
                    continue
                replacement = f"%{raw_directive}:`{value[1:]}`"
            else:
                if not raw_arg.startswith("!"):
                    continue
                replacement = f"%{raw_directive}:{raw_arg[1:]}"
            replacements.append((match.start(), match.end(), replacement))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def force_reuse_owner_names(prompts: list[str]) -> list[str]:
    """Return force-reuse owner names in first-seen order."""
    names: list[str] = []
    seen: set[str] = set()
    for request in _explicit_launch_name_requests(prompts):
        if request.force_reuse and request.name not in seen:
            names.append(request.name)
            seen.add(request.name)
    return names


def wipe_names_for_forced_reuse(names: list[str]) -> None:
    """Best-effort removal hook used after TUI confirmation."""
    for name in names:
        _wipe_agent_name_for_reuse(name)


def _wipe_agent_name_for_reuse(name: str) -> None:
    """Best-effort narrow wipe of the current registry owner for *name*.

    Phase 5 owns the complete delete contract.  This helper provides the
    launch-time hook and removes the owner locations that phase 1 registry
    entries already know about.
    """
    from shutil import rmtree

    from sase.agent.names import delete_registered_name, lookup_registered_name

    entry = lookup_registered_name(name)
    if entry is None:
        return

    try:
        from sase.agent.running import kill_named_agent

        kill_named_agent(name, exact_name=True)
    except Exception:
        pass

    artifacts_dir = entry.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        try:
            rmtree(Path(artifacts_dir), ignore_errors=True)
        except Exception:
            pass

    bundle_path = entry.get("bundle_path")
    if isinstance(bundle_path, str) and bundle_path:
        try:
            Path(bundle_path).unlink(missing_ok=True)
        except OSError:
            pass

    delete_registered_name(name)


def _extract_explicit_name(prompt: str) -> tuple[str, bool] | None:
    if "%" not in prompt:
        return None
    if _prompt_has_launch_fanout(prompt):
        return None

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue

        value = ""
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                inner = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(inner)
                value = positional_args[0] if positional_args else ""
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            value = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )

        if not value:
            return None
        force_reuse = value.startswith("!")
        name = value[1:] if force_reuse else value
        if "#" in name or not name:
            return None
        return name, force_reuse
    return None


def _prompt_has_launch_fanout(prompt: str) -> bool:
    try:
        from sase.xprompt.directives import plan_prompt_fanout_variants

        return plan_prompt_fanout_variants(prompt) is not None
    except Exception:
        return False
