"""Directive value resolution after raw prompt directive collection."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ._directive_time import parse_absolute_time, parse_duration
from ._exceptions import DirectiveError
from .effort import EFFORT_LEVELS_ORDERED, is_valid_effort, split_model_effort

ProcessReferences = Callable[[str], str]


@dataclass(frozen=True)
class _NameTemplateInfo:
    """Resolved fields derived from an optional agent-name template."""

    name_template: str | None = None
    name_template_base: str | None = None
    name_indexed_template: bool = False
    name_indexed_base: str | None = None


def resolve_wait_agent_args(seen_multi: dict[str, list[str]]) -> None:
    """Resolve positional ``%wait`` arguments in-place."""
    if "wait" not in seen_multi:
        return

    resolved_wait: list[str] = []
    prev_name: str | None = None
    for raw_arg in seen_multi["wait"]:
        if not raw_arg:
            if prev_name is None:
                from sase.agent.names import get_most_recent_agent_name

                prev_name = get_most_recent_agent_name() or ""
            if not prev_name:
                raise DirectiveError(
                    "Bare '%wait' directive found but no previously named agent exists"
                )
            resolved_wait.append(prev_name)
            continue
        _parse_wait_tribe_reference(raw_arg)
        resolved_wait.append(raw_arg)
    seen_multi["wait"] = resolved_wait


def _parse_wait_tribe_reference(value: str) -> str | None:
    """Parse a wait tribe target and translate validation into directive errors."""
    from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference

    try:
        return parse_tribe_reference(value)
    except InvalidTribeError as exc:
        raise DirectiveError(
            f"Invalid '%wait' tribe reference {value!r}: {exc}"
        ) from exc


def resolve_wait_bead_args(wait_bead_args: list[str]) -> list[str]:
    """Validate and deduplicate ``%wait(bead=...)`` values."""
    resolved: list[str] = []
    seen: set[str] = set()
    for raw_arg in wait_bead_args:
        if not raw_arg or re.fullmatch(r"\S+", raw_arg) is None:
            raise DirectiveError(
                "'%wait(bead=...)' requires a non-empty, whitespace-free bead ID"
            )
        if raw_arg not in seen:
            seen.add(raw_arg)
            resolved.append(raw_arg)
    return resolved


def resolve_wait_time_args(
    wait_time_args: list[str],
) -> tuple[float | None, str | None]:
    """Resolve ``%wait(time=...)`` values into duration/until fields."""
    wait_duration: float | None = None
    wait_until: str | None = None
    for raw_arg in wait_time_args:
        if not raw_arg:
            raise DirectiveError(
                "'%wait(time=...)' requires a duration or absolute time argument"
            )
        dur = parse_duration(raw_arg)
        if dur is not None:
            if wait_until is not None:
                raise DirectiveError("Cannot combine duration and absolute time waits")
            wait_duration = max(wait_duration or 0.0, dur)
            continue
        abs_time = parse_absolute_time(raw_arg)
        if abs_time is not None:
            if wait_until is not None:
                raise DirectiveError("Multiple absolute time waits are not allowed")
            if wait_duration is not None:
                raise DirectiveError("Cannot combine duration and absolute time waits")
            wait_until = abs_time
            continue
        raise DirectiveError(
            f"Invalid %wait time= value '{raw_arg}'; time= accepts only "
            "durations (e.g. 5m) and absolute times (e.g. 1430). "
            f"Use %wait:{raw_arg} to wait for an agent."
        )
    return wait_duration, wait_until


def resolve_wait_runners_args(wait_runners_args: list[str]) -> int | None:
    """Resolve and validate the optional ``%wait(runners=...)`` threshold."""
    if not wait_runners_args:
        return None
    if len(wait_runners_args) > 1:
        raise DirectiveError("Multiple %wait(runners=...) values are not allowed")

    raw_arg = wait_runners_args[0]
    if re.fullmatch(r"[0-9]+", raw_arg) is None:
        raise DirectiveError(
            "'%wait(runners=...)' requires a non-negative integer argument"
        )
    return int(raw_arg)


def normalize_model_directive(
    seen: dict[str, str],
    literal_directives: set[str],
) -> tuple[str | None, bool]:
    """Split ``%model:<model>@<effort>`` and normalize alias prefixes in-place."""
    model_effort: str | None = None
    model_had_alias_prefix = False
    if "model" in seen and "model" not in literal_directives:
        from sase.llm_provider.config import strip_model_alias_prefix

        clean_model, model_effort = split_model_effort(seen["model"])
        model_had_alias_prefix = clean_model.startswith("@")
        if model_had_alias_prefix:
            clean_model = strip_model_alias_prefix(clean_model)
        seen["model"] = clean_model
    return model_effort, model_had_alias_prefix


def expand_single_directive_args(
    seen: dict[str, str],
    *,
    literal_directives: set[str],
    model_had_alias_prefix: bool,
    process_references: ProcessReferences,
) -> dict[str, str]:
    """Expand xprompt references in single-value directive arguments."""
    expanded_args: dict[str, str] = {}
    for directive_name, raw_arg in seen.items():
        if raw_arg and "#" in raw_arg:
            expanded_args[directive_name] = process_references(raw_arg).strip()
        else:
            expanded_args[directive_name] = raw_arg

    if "model" in expanded_args and "model" not in literal_directives:
        expanded_args["model"] = _validate_model_alias_prefix(
            expanded_args["model"],
            had_alias_prefix=model_had_alias_prefix,
        )
    return expanded_args


def expand_multi_directive_args(
    seen_multi: dict[str, list[str]],
    *,
    process_references: ProcessReferences,
) -> dict[str, list[str]]:
    """Expand xprompt references in multi-value directive arguments."""
    expanded_multi: dict[str, list[str]] = {}
    for directive_name, raw_args in seen_multi.items():
        expanded_list: list[str] = []
        for raw_arg in raw_args:
            if raw_arg and "#" in raw_arg:
                expanded_list.append(process_references(raw_arg).strip())
            else:
                expanded_list.append(raw_arg)
        expanded_multi[directive_name] = expanded_list
    return expanded_multi


def resolve_model_alias_overrides(
    raw_overrides: dict[str, str],
    *,
    process_references: ProcessReferences,
) -> dict[str, str]:
    """Expand and validate launch-family model alias overrides."""
    if not raw_overrides:
        return {}

    from sase.llm_provider.config import model_alias_names

    aliases = model_alias_names()
    valid_aliases = ", ".join(f"@{name}" for name in sorted(aliases))
    resolved: dict[str, str] = {}
    for raw_key, raw_value in raw_overrides.items():
        key = raw_key.strip()
        if key.startswith("@"):
            raise DirectiveError(
                f"Model alias override keys are bare — use '{key[1:]}=', not '{key}='."
            )
        if key not in aliases:
            raise DirectiveError(
                f"Unknown model alias '{key}' on %model — valid aliases: "
                f"{valid_aliases}."
            )

        value = raw_value
        if value and "#" in value:
            value = process_references(value).strip()
        if not value:
            raise DirectiveError(
                f"Model alias override '{key}=' requires a model value."
            )

        clean_value, effort = split_model_effort(value)
        if effort is not None:
            raise DirectiveError(
                f"Model alias override '{key}={value}' cannot set reasoning "
                "effort; per-alias effort overrides are not supported."
            )
        had_alias_prefix = clean_value.startswith("@")
        alias_value = clean_value[1:] if had_alias_prefix else clean_value
        _validate_model_alias_prefix(
            alias_value,
            had_alias_prefix=had_alias_prefix,
        )
        if had_alias_prefix and alias_value == key:
            raise DirectiveError(
                f"Model alias override '{key}=@{key}' cannot reference itself."
            )
        resolved[key] = clean_value
    return resolved


def resolve_name_template(
    raw_name: str | None, *, force_reuse: bool
) -> _NameTemplateInfo:
    """Resolve optional agent-name template metadata."""
    if not raw_name:
        return _NameTemplateInfo()

    if "@" not in raw_name:
        return _NameTemplateInfo()

    from sase.agent.names import (
        AgentNameTemplateError,
        agent_name_template_base,
        parse_agent_name_template,
    )

    if force_reuse:
        raise DirectiveError(
            "Cannot combine forced name reuse with an agent name template"
        )
    try:
        parse_agent_name_template(raw_name)
        template_base = agent_name_template_base(raw_name)
    except AgentNameTemplateError as exc:
        raise DirectiveError(str(exc)) from exc
    return _NameTemplateInfo(
        name_template=raw_name,
        name_template_base=template_base,
        name_indexed_template=True,
        name_indexed_base=template_base,
    )


def resolve_wait_templates(expanded_multi: dict[str, list[str]]) -> None:
    """Resolve ``%wait`` agent-name templates in-place."""
    if "wait" not in expanded_multi:
        return

    from sase.agent.names import (
        AgentNameTemplateError,
        is_agent_name_template,
        require_latest_agent_name_template,
    )

    resolved_waits: list[str] = []
    for raw_wait in expanded_multi["wait"]:
        if _parse_wait_tribe_reference(raw_wait) is not None:
            resolved_waits.append(raw_wait)
            continue
        if not is_agent_name_template(raw_wait):
            resolved_waits.append(raw_wait)
            continue
        try:
            resolved_waits.append(require_latest_agent_name_template(raw_wait))
        except AgentNameTemplateError as exc:
            raise DirectiveError(str(exc)) from exc
    expanded_multi["wait"] = resolved_waits


def parse_repeat_count(expanded_args: dict[str, str]) -> int | None:
    """Parse and validate the ``%repeat`` directive."""
    if "repeat" not in expanded_args:
        return None

    raw_repeat = expanded_args["repeat"]
    if not raw_repeat:
        raise DirectiveError(
            "'%repeat' directive requires a positive integer argument (e.g., %repeat:3)"
        )
    try:
        repeat_count = int(raw_repeat)
    except ValueError as exc:
        raise DirectiveError(
            f"Invalid repeat count '{raw_repeat}' — must be a positive integer"
        ) from exc
    if repeat_count <= 0:
        raise DirectiveError(
            f"Invalid repeat count '{repeat_count}' — must be a positive integer"
        )
    return repeat_count


def parse_tribe_name(expanded_args: dict[str, str]) -> str | None:
    """Parse and validate the ``tribe=`` keyword on ``%id``."""
    raw_tribe = expanded_args.get("tribe")
    if raw_tribe:
        from sase.core.agent_tribe import InvalidTribeError, validate_tribe_name

        try:
            return validate_tribe_name(raw_tribe)
        except InvalidTribeError as exc:
            raise DirectiveError(f"Invalid '%id' tribe= value: {exc}") from exc
    if "tribe" in expanded_args:
        raise DirectiveError("'%id(..., tribe=...)' requires a non-empty tribe name.")
    return None


def resolve_clan_membership(expanded_args: dict[str, str]) -> str | None:
    """Validate and return the optional ``%clan:<name>`` declaration."""
    if "clan" not in expanded_args:
        return None

    clan = expanded_args["clan"].strip()
    if not clan:
        raise DirectiveError(
            "'%clan' directive requires a clan name argument (e.g., %clan:research.@)"
        )
    return clan


def resolve_clan_tribe(
    raw_tribe: str | None,
    *,
    present: bool,
    process_references: ProcessReferences,
) -> str | None:
    """Expand and validate the optional ``tribe=`` keyword on ``%clan``."""
    if not present:
        return None
    tribe = raw_tribe or ""
    if tribe and "#" in tribe:
        tribe = process_references(tribe).strip()
    if not tribe:
        raise DirectiveError("'%clan(..., tribe=...)' requires a non-empty tribe name.")

    from sase.core.agent_tribe import InvalidTribeError, validate_tribe_name

    try:
        return validate_tribe_name(tribe)
    except InvalidTribeError as exc:
        raise DirectiveError(f"Invalid '%clan' tribe= value: {exc}") from exc


def resolve_clan_summary(
    raw_summary: str | None,
    *,
    present: bool,
) -> str | None:
    """Validate the optional literal ``summary=`` keyword on ``%clan``."""
    return _resolve_nonempty_clan_value(
        raw_summary,
        present=present,
        keyword="summary",
    )


def resolve_clan_summary_script(
    raw_script: str | None,
    *,
    present: bool,
) -> str | None:
    """Validate the optional ``summary_script=`` keyword on ``%clan``."""
    return _resolve_nonempty_clan_value(
        raw_script,
        present=present,
        keyword="summary_script",
    )


def _resolve_nonempty_clan_value(
    raw_value: str | None,
    *,
    present: bool,
    keyword: str,
) -> str | None:
    if not present:
        return None
    value = (raw_value or "").strip()
    if not value:
        raise DirectiveError(f"'%clan(..., {keyword}=...)' requires a non-empty value.")
    return value


def resolve_reasoning_effort(
    *,
    effort_directive: str | None,
    effort_present: bool,
    model_effort: str | None,
) -> str | None:
    """Resolve the effective reasoning effort from both directive surfaces."""
    directive_effort: str | None = None
    if effort_present:
        if not effort_directive:
            raise DirectiveError(
                "'%effort' directive requires a level argument (e.g., %effort:xhigh)"
            )
        if not is_valid_effort(effort_directive):
            raise DirectiveError(
                f"Unknown effort level '{effort_directive}'; valid levels are: "
                f"{', '.join(EFFORT_LEVELS_ORDERED)}"
            )
        directive_effort = effort_directive

    if (
        directive_effort is not None
        and model_effort is not None
        and directive_effort != model_effort
    ):
        raise DirectiveError(
            f"Conflicting effort levels: %model:...@{model_effort} and "
            f"%effort:{directive_effort} must match"
        )

    return directive_effort or model_effort


def resolve_auto_mode(expanded_args: dict[str, str]) -> str | None:
    """Return a compatibility mode while retaining validation for adapters."""
    if "auto" not in expanded_args:
        return None

    raw_auto_mode = expanded_args["auto"] or "plan"
    if raw_auto_mode == "true":
        raw_auto_mode = "plan"
    return raw_auto_mode


def resolve_auto_argument(expanded_args: dict[str, str]) -> tuple[bool, str | None]:
    """Return presence plus the opaque optional ``%auto`` argument."""
    if "auto" not in expanded_args:
        return False, None
    raw = expanded_args["auto"]
    if raw in {"", "true"}:
        return True, None
    return True, raw


def _validate_model_alias_prefix(model: str, *, had_alias_prefix: bool) -> str:
    """Enforce the user-facing ``@`` spelling rule for model aliases."""
    if not model:
        return model

    from sase.llm_provider.config import model_alias_names

    aliases = model_alias_names()
    if had_alias_prefix:
        if model not in aliases:
            raise DirectiveError(
                f"'@{model}' is not a known model alias; @ may only prefix a "
                "configured or built-in model alias (e.g. @default, @coder)."
            )
    elif model in aliases:
        raise DirectiveError(
            f"Model aliases must be prefixed with @ — did you mean @{model}?"
        )
    return model
