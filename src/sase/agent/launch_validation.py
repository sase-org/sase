"""Pre-spawn validation for permanent agent-name launches."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from sase.plan_chain import AGENT_FAMILY_SEPARATOR

__all__ = [
    "AgentNameLaunchCollisionError",
    "AgentNameForeignMachineError",
    "AgentNameSyntaxError",
    "INTERNAL_AGENT_NAME_BYPASS_ENV",
    "AgentNameReuseConfirmationRequiredError",
    "force_reuse_owner_names",
    "internal_agent_name_bypass_enabled",
    "preflight_launch_name_requests",
    "rewrite_force_reuse_name_directives",
    "validate_user_agent_name",
    "validate_launch_name_requests",
    "wipe_names_for_forced_reuse",
]

INTERNAL_AGENT_NAME_BYPASS_ENV = "SASE_INTERNAL_AGENT_NAME_BYPASS"


@dataclass(frozen=True)
class _LaunchNameRequest:
    """Explicit agent name requested by one launch prompt."""

    name: str
    force_reuse: bool
    name_template: bool
    prompt_index: int
    family_attach_parent: str | None = None


class _LaunchNameValidationError(RuntimeError):
    """Base class for launch-name validation failures."""


class AgentNameLaunchCollisionError(_LaunchNameValidationError):
    """Raised when a launch tries to reuse an already reserved name."""

    def __init__(self, name: str, suggestion: str) -> None:
        self.name = name
        self.suggestion = suggestion
        super().__init__(f"Agent name '{name}' is taken. Try '{suggestion}'.")


class _AgentNameClanCollisionError(_LaunchNameValidationError):
    """Raised when an agent tries to claim a clan container's name."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Agent name '{name}' is reserved for clan '{name}'. "
            f"Choose a name inside the clan hood, such as '{name}.member'."
        )


class _AgentNameFamilyCollisionError(_LaunchNameValidationError):
    """Raised when an agent tries to claim a family container's name."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Agent name '{name}' is reserved for agent family '{name}'. "
            "Attach a member with %i(suffix, family=parent) instead."
        )


class AgentNameReuseConfirmationRequiredError(_LaunchNameValidationError):
    """Raised when a non-TUI surface submits ``%id:!<name>``."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Agent name '{name}' uses forced reuse; confirmation is required."
        )


class _AgentNameTemplateError(_LaunchNameValidationError):
    """Raised when template syntax is invalid for launch preflight."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"Invalid agent name template '{name}': {reason}")


class AgentNameSyntaxError(_LaunchNameValidationError):
    """Raised when a new user-specified agent name is syntactically invalid."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Agent name '{name}' cannot contain '{AGENT_FAMILY_SEPARATOR}'; "
            "double dash is reserved for agent-family phases."
        )


class AgentNameForeignMachineError(_LaunchNameValidationError):
    """Raised when a launch names another configured machine's agent."""

    def __init__(self, name: str, foreign_machine: str, local_machine: str) -> None:
        self.name = name
        self.foreign_machine = foreign_machine
        self.local_machine = local_machine
        super().__init__(
            f"Agent name '{name}' belongs to known machine '{foreign_machine}' "
            f"and cannot be launched on local machine '{local_machine}'. "
            "Use a bare name or the local machine-qualified spelling."
        )


class _AgentNameDirectiveSyntaxError(_LaunchNameValidationError):
    """Raised when a ``%id``/``%i`` directive has invalid arguments."""


def validate_user_agent_name(name: str) -> None:
    """Validate a new user-specified agent name.

    Historical artifact names are read separately; this is only for explicit
    user entry points such as ``%id``, mobile launch names, and TUI naming.
    """
    if AGENT_FAMILY_SEPARATOR in name:
        raise AgentNameSyntaxError(name)
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        foreign_agent_owner_root,
    )

    identity = AgentIdentitySnapshot.current()
    foreign_machine = foreign_agent_owner_root(name, identity)
    if foreign_machine is not None and identity.owner is not None:
        raise AgentNameForeignMachineError(
            name,
            foreign_machine,
            identity.owner.machine_name,
        )


def internal_agent_name_bypass_enabled(
    env: Mapping[str, str] | None,
) -> bool:
    """Return whether a trusted launcher enabled internal name syntax."""
    if env is None:
        return False
    return env.get(INTERNAL_AGENT_NAME_BYPASS_ENV) == "1"


def _explicit_launch_name_requests(prompts: list[str]) -> list[_LaunchNameRequest]:
    """Return explicit ``%id`` requests from already-split launch segments.

    Each input must be one per-segment, already-expanded prompt. Only the first
    ``%id``/``%i`` directive in each element is considered.
    """
    requests: list[_LaunchNameRequest] = []
    for i, prompt in enumerate(prompts):
        parsed = _extract_explicit_name(prompt)
        if parsed is None:
            continue
        name, force_reuse, name_template, family_attach_parent = parsed
        requests.append(
            _LaunchNameRequest(
                name=name,
                force_reuse=force_reuse,
                name_template=name_template,
                prompt_index=i,
                family_attach_parent=family_attach_parent,
            )
        )
    return requests


def validate_launch_name_requests(
    prompts: list[str],
    *,
    allow_force_reuse: bool = False,
    allow_reserved_family_separator_names: bool = False,
    allow_hyphenated_names: bool | None = None,
) -> None:
    """Validate explicit launch names under the global name allocation lock."""
    if allow_hyphenated_names is not None:
        allow_reserved_family_separator_names = allow_hyphenated_names

    requests = _preflight_launch_name_requests(
        prompts,
        allow_force_reuse=allow_force_reuse,
        allow_reserved_family_separator_names=(allow_reserved_family_separator_names),
    )
    if not requests:
        return

    from sase.agent.names import (
        agent_name_allocation_lock,
        get_reserved_agent_names,
        get_reserved_clan_names,
        get_reserved_family_names,
        lowest_name_suggestion,
    )

    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )

    identity = AgentIdentitySnapshot.current()
    seen: set[str] = set()
    # Load the reserved-name set once per launch instead of per explicit name.
    # ``is_name_reserved`` reloads the registry (and re-runs O(entries) stale-owner
    # checks) on every call, so a multi-prompt launch with N explicit names paid
    # that cost N times. Computing the set once under the allocation lock keeps the
    # same collision contract while making validation independent of segment count.
    reserved_names: set[str] | None = None
    clan_names: set[str] | None = None
    family_names: set[str] | None = None
    reserved_keys: set[str] | None = None
    clan_keys: set[str] | None = None
    family_keys: set[str] | None = None
    with agent_name_allocation_lock():
        for request in requests:
            if request.name_template:
                continue
            if request.force_reuse:
                if reserved_names is None:
                    reserved_names = get_reserved_agent_names()
                    clan_names = get_reserved_clan_names()
                    family_names = get_reserved_family_names()
                    reserved_keys = {
                        current_owner_agent_name_key(name, identity)
                        for name in reserved_names
                    }
                    clan_keys = {
                        current_owner_agent_name_key(name, identity)
                        for name in clan_names
                    }
                    family_keys = {
                        current_owner_agent_name_key(name, identity)
                        for name in family_names
                    }
                request_key = current_owner_agent_name_key(request.name, identity)
                if clan_keys is not None and request_key in clan_keys:
                    raise _AgentNameClanCollisionError(request.name)
                if family_keys is not None and request_key in family_keys:
                    raise _AgentNameFamilyCollisionError(request.name)
                continue
            if reserved_names is None:
                reserved_names = get_reserved_agent_names()
                clan_names = get_reserved_clan_names()
                family_names = get_reserved_family_names()
                reserved_keys = {
                    current_owner_agent_name_key(name, identity)
                    for name in reserved_names
                }
                clan_keys = {
                    current_owner_agent_name_key(name, identity) for name in clan_names
                }
                family_keys = {
                    current_owner_agent_name_key(name, identity)
                    for name in family_names
                }
            request_key = current_owner_agent_name_key(request.name, identity)
            assert reserved_keys is not None
            if request_key in seen or request_key in reserved_keys:
                if clan_keys is not None and request_key in clan_keys:
                    raise _AgentNameClanCollisionError(request.name)
                if family_keys is not None and request_key in family_keys:
                    raise _AgentNameFamilyCollisionError(request.name)
                raise AgentNameLaunchCollisionError(
                    request.name, lowest_name_suggestion(request.name)
                )
            seen.add(request_key)


def preflight_launch_name_requests(
    prompts: list[str],
    *,
    allow_force_reuse: bool = False,
    allow_reserved_family_separator_names: bool = False,
    allow_hyphenated_names: bool | None = None,
) -> None:
    """Validate launch-name syntax without reading or mutating name state."""
    if allow_hyphenated_names is not None:
        allow_reserved_family_separator_names = allow_hyphenated_names
    _preflight_launch_name_requests(
        prompts,
        allow_force_reuse=allow_force_reuse,
        allow_reserved_family_separator_names=(allow_reserved_family_separator_names),
    )


def _preflight_launch_name_requests(
    prompts: list[str],
    *,
    allow_force_reuse: bool,
    allow_reserved_family_separator_names: bool,
) -> list[_LaunchNameRequest]:
    """Return syntax-checked requests without consulting reservation state."""
    requests = _explicit_launch_name_requests(prompts)

    if not allow_reserved_family_separator_names:
        for request in requests:
            if request.family_attach_parent is not None:
                validate_user_agent_name(request.family_attach_parent)
            elif not request.name_template:
                validate_user_agent_name(request.name)

    from sase.agent.names import (
        InvalidAgentNameTemplateError,
        parse_agent_name_template,
        render_agent_name_template,
    )

    for request in requests:
        if request.name_template:
            if request.force_reuse:
                raise _AgentNameTemplateError(
                    request.name,
                    "forced reuse cannot be combined with templates",
                )
            try:
                parse_agent_name_template(request.name)
                if not allow_reserved_family_separator_names:
                    validate_user_agent_name(
                        render_agent_name_template(request.name, "0")
                    )
            except InvalidAgentNameTemplateError as exc:
                raise _AgentNameTemplateError(request.name, exc.reason) from exc
            continue
        if request.force_reuse and not allow_force_reuse:
            raise AgentNameReuseConfirmationRequiredError(request.name)

    return requests


def rewrite_force_reuse_name_directives(prompt: str) -> str:
    """Rewrite ``%id:!foo``/``%id(!foo)`` to normal ``%id:foo`` forms."""
    if "%i" not in prompt:
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
        if _DIRECTIVE_ALIASES.get(raw_directive, raw_directive) != "id":
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
            bang_index = protected.find("!", paren_start + 1, paren_end)
            if bang_index >= 0:
                replacements.append((bang_index, bang_index + 1, ""))
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
    """Return force-reuse owner names from already-split launch segments.

    Each input must be one per-segment prompt. Only the first ``%id``/``%i``
    directive in each element is considered.
    """
    names: list[str] = []
    seen: set[str] = set()
    for request in _explicit_launch_name_requests(prompts):
        if request.name_template:
            continue
        if request.force_reuse and request.name not in seen:
            names.append(request.name)
            seen.add(request.name)
    return names


def wipe_names_for_forced_reuse(names: list[str]) -> None:
    """Remove explicit force-reuse owners or fail before launch mutation."""
    for name in names:
        from sase.agent.names import wipe_agent_name_for_reuse

        result = wipe_agent_name_for_reuse(name)
        if result.errors:
            detail = "; ".join(result.errors)
            raise RuntimeError(f"Failed to wipe agent name '{name}': {detail}")
        if result.skipped_container_kind:
            raise RuntimeError(
                f"Cannot force-reuse {result.skipped_container_kind} "
                f"container '{name}'."
            )


def _extract_explicit_name(
    prompt: str,
) -> tuple[str, bool, bool, str | None] | None:
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
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "id":
            continue

        value = ""
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                inner = protected[paren_start + 1 : paren_end]
                positional_args, named_args = parse_args(inner)
                from sase.agent.family_attach import parse_name_directive_args

                try:
                    parsed = parse_name_directive_args(
                        positional_args,
                        named_args,
                        source=f"%{raw_name}",
                    )
                except ValueError as exc:
                    raise _AgentNameDirectiveSyntaxError(str(exc)) from exc
                if (
                    parsed.family_parent is not None
                    and parsed.family_suffix is not None
                ):
                    if not parsed.force_reuse:
                        return None
                    from sase.agent.family_attach import normalize_family_suffix_arg

                    exact_name = (
                        f"{parsed.family_parent}"
                        f"{normalize_family_suffix_arg(parsed.family_suffix)}"
                    )
                    return exact_name, True, False, parsed.family_parent
                value = parsed.plain_name or ""
                if parsed.clan is not None:
                    value = f"{parsed.clan}.{value}"
                force_reuse = parsed.force_reuse or value.startswith("!")
            else:
                force_reuse = False
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            value = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )
            force_reuse = value.startswith("!")
        else:
            force_reuse = False

        if not value:
            return None
        if value.startswith("!"):
            value = value[1:]
        name = value
        if "#" in name or not name:
            return None
        return name, force_reuse, "@" in name, None
    return None


def _prompt_has_launch_fanout(prompt: str) -> bool:
    try:
        from sase.xprompt.directives import plan_prompt_fanout_variants

        return plan_prompt_fanout_variants(prompt) is not None
    except Exception:
        return False
