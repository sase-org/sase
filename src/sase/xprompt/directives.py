"""Prompt directive parsing (%name tag system).

Directives are in-prompt tags with a ``%`` prefix that modify runner behavior.
They are extracted and stripped from the prompt before further preprocessing.
Directive arguments use the same syntax as xprompts (colon, paren, backtick, plus).

Example::

    %model:agy/flash35l
    Review this code...

The ``%model`` directive overrides the LLM model used for that prompt.

The implementation is split across a few private sibling modules:

- :mod:`._directive_types` — :class:`PromptDirectives` dataclass and the
  shared regex/alias tables.
- :mod:`._directive_time` — duration / absolute-time argument parsing for
  ``%wait``.
- :mod:`._directive_alt` — ``%alt(...)`` / ``%(...)`` splitting and the
  multi-model fan-out used by :func:`split_prompt_for_models`.

This module is the public entry point and owns
:func:`extract_prompt_directives` plus the cheap ``has_*_directive``
predicates.
"""

import re

from ._directive_alt import (
    _ALT_DIRECTIVE_RE,
    apply_fanout_naming,
    has_alt_directive,
    multi_model_unsupported_message,
    plan_prompt_fanout_variants,
    split_prompt_for_alternatives,
    split_prompt_for_models,
)
from ._directive_time import parse_absolute_time, parse_duration
from ._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
    _MULTI_VALUE_DIRECTIVES,
    PromptDirectives,
)
from ._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from ._exceptions import DirectiveError
from .effort import EFFORT_LEVELS_ORDERED, is_valid_effort, split_model_effort
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_args,
)
from .processor import process_xprompt_references

__all__ = [
    "PromptDirectives",
    "apply_fanout_naming",
    "extract_prompt_directives",
    "has_alt_directive",
    "has_deferred_start_directive",
    "has_model_directive",
    "parse_absolute_time",
    "parse_duration",
    "plan_prompt_fanout_variants",
    "split_prompt_for_alternatives",
    "split_prompt_for_models",
    "strip_known_directives",
]


def strip_known_directives(prompt: str) -> str:
    """Remove known ``%name`` directive spans from *prompt* without side effects.

    Side-effect-free counterpart to :func:`extract_prompt_directives`: it
    strips the same known/directive-migration spans (colon, paren, backtick,
    and plus argument forms, plus short aliases) but never allocates auto-names,
    resolves ``%wait`` arguments, or raises :class:`DirectiveError` on
    duplicate or bare directives. Unknown ``%name`` tokens and directives
    inside fenced code blocks are left untouched.

    Intended for cleaning historical prompt text (e.g. ``#fork`` resume
    history) where directives carry no runtime meaning and should simply be
    removed.
    """
    if "%" not in prompt:
        return prompt

    # Protect fenced code blocks so directives inside example code survive.
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    regions_to_remove: list[tuple[int, int]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in _KNOWN_DIRECTIVES and name not in _DEPRECATED_DIRECTIVES:
            continue
        match_end = match.end()
        if match.group(2) is not None:  # paren argument form: consume to ')'
            paren_end = find_matching_paren_for_args(protected, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        regions_to_remove.append((match.start(), match_end))

    cleaned = protected
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]

    return unprotect_fenced_blocks(cleaned, fenced_blocks)


def _has_wait_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%wait`` or ``%w`` directives."""
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:wait|w)(?:[:+(]|\s|$)",
    )


def has_deferred_start_directive(prompt: str) -> bool:
    """Quick check whether a prompt defers launch.

    Used at the workspace-allocation boundary so a prompt that delays its
    start (waiting on a dependency or a wall-clock time) does not claim a
    workspace until it is actually ready to run.
    """
    if _has_wait_directive(prompt) or _has_t_time_xprompt_reference(prompt):
        return True
    if "#fork" not in prompt:
        return False
    from sase.agent.names import has_fork_reference

    return has_fork_reference(prompt)


def has_model_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%model`` or ``%m`` directives.

    This avoids the overhead of full directive extraction and is suitable for
    checking whether a user's custom prompt already specifies a model.
    """
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:model|m)(?:[:+(]|\s|$)",
    )


def _has_protected_directive_match(prompt: str, pattern: str) -> bool:
    """Run a cheap directive predicate after extractor-equivalent protection."""
    return _has_protected_pattern_match(prompt, pattern, required_substring="%")


def _has_t_time_xprompt_reference(prompt: str) -> bool:
    """Quick check whether a prompt contains an explicit ``#t`` time wait."""
    return _has_protected_pattern_match(
        prompt,
        r"(?:^|(?<=\s)|(?<=[(\[{\"']))#t(?=[:(])",
        required_substring="#t",
    )


def _has_protected_pattern_match(
    prompt: str, pattern: str, *, required_substring: str
) -> bool:
    """Run a cheap predicate after fenced-block and disabled-region protection."""
    if required_substring not in prompt:
        return False

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    return bool(re.search(pattern, protected, re.MULTILINE))


def _resolve_reasoning_effort(
    *,
    effort_directive: str | None,
    effort_present: bool,
    model_effort: str | None,
) -> str | None:
    """Resolve the effective reasoning effort from the two directive surfaces.

    ``effort_directive`` is the value of an explicit ``%effort`` directive
    (``effort_present`` distinguishes an absent directive from an empty one);
    ``model_effort`` is the effort peeled off a ``%model:<model>@<effort>``
    suffix (already a known level, or None).

    Validates the ``%effort`` spelling and enforces the conflict rule: if both
    surfaces survive into the same prompt with different levels, raise; equal
    values are allowed.
    """
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


def extract_prompt_directives(
    prompt: str, *, strip_disabled_markers: bool = True
) -> tuple[str, PromptDirectives]:
    """Extract ``%name`` directives from a prompt.

    Finds all ``%name`` patterns in the prompt. Known directives are parsed,
    their xprompt references expanded, and they are stripped from the prompt.
    Unknown ``%name`` patterns are left in the prompt unchanged.

    Args:
        prompt: The raw prompt text.
        strip_disabled_markers: If True (default), strip
            ``%xprompts_enabled:false``/``%xprompts_enabled:true`` markers from
            the returned prompt. Set to False when this function is called as
            part of a multi-phase pipeline that needs to preserve the markers
            for a later phase (e.g. :func:`preprocess_prompt_early`).

    Returns:
        Tuple of (cleaned_prompt, directives).

    Raises:
        DirectiveError: If a known single-value directive appears more than
            once. Top-level ``%model`` is single-value; repeated model
            directives and multi-argument ``%model(...)`` forms raise with a
            migration hint. Directives inside raw ``%alt(...)`` / ``%(...)`` /
            ``%{...}`` bodies are ignored until the fan-out planner splits
            those branches.
    """
    if "%" not in prompt:
        return prompt, PromptDirectives()

    # Protect fenced code blocks so directives inside them are ignored
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # Protect disabled regions so old directives inside #fork
    # expansions are not re-parsed.
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    alt_inner_regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(prompt):
        open_pos = alt_match.end() - 1
        if prompt[open_pos] == "{":
            close_pos = find_matching_brace_for_args(prompt, open_pos)
        else:
            close_pos = find_matching_paren_for_args(prompt, open_pos)
        if close_pos is None:
            continue
        alt_inner_regions.append((open_pos + 1, close_pos))

    def _is_inside_alt(pos: int) -> bool:
        return any(start <= pos < end for start, end in alt_inner_regions)

    matches = [
        match
        for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE)
        if not _is_inside_alt(match.start())
    ]
    if not matches:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        if strip_disabled_markers:
            prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

    # Collect known directive matches (we'll strip these from the prompt)
    seen: dict[str, str] = {}  # directive name -> raw arg value (single-value)
    seen_source: dict[str, str] = {}  # directive name -> raw directive text
    seen_multi: dict[
        str, list[str]
    ] = {}  # directive name -> raw arg values (multi-value)
    wait_time_args: list[str] = []
    # Single-value directives whose argument came from a backtick literal
    # (e.g. ``%model:`literal@id` ``). Tracked so the ``@effort`` split bypasses
    # backtick-literal model values, preserving any ``@`` in the model id.
    literal_directives: set[str] = set()
    # Regions to remove: list of (start, end) character positions
    regions_to_remove: list[tuple[int, int]] = []

    for match in matches:
        name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(name, name)  # resolve alias
        if name in _DEPRECATED_DIRECTIVES:
            raise DirectiveError(
                "The '%time' directive has been removed; use #t:<time> "
                "or %wait(time=<time>) instead."
            )
        if name not in _KNOWN_DIRECTIVES:
            continue

        # Extract argument value
        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()
        is_multi = name in _MULTI_VALUE_DIRECTIVES
        raw_args: list[str] = []

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(prompt, paren_start)
            if paren_end is not None:
                paren_content = prompt[paren_start + 1 : paren_end]
                positional_args, named_args = parse_args(paren_content)
                if name == "wait":
                    unknown_keys = sorted(key for key in named_args if key != "time")
                    if unknown_keys:
                        keys = ", ".join(f"{key}=" for key in unknown_keys)
                        raise DirectiveError(
                            f"Unsupported keyword on %wait: {keys}. "
                            "Only time= is supported."
                        )
                    if "time" in named_args:
                        wait_time_args.append(named_args["time"])
                if is_multi:
                    raw_args = list(positional_args)
                elif (
                    name == "model" and len([arg for arg in positional_args if arg]) > 1
                ):
                    source = prompt[match.start() : paren_end + 1]
                    models = [arg for arg in positional_args if arg]
                    raise DirectiveError(
                        multi_model_unsupported_message(source, models)
                    )
                else:
                    raw_args = [positional_args[0] if positional_args else ""]
                match_end = paren_end + 1
            else:
                raw_args = [""]
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_args = [colon_arg[1:-1]]
                literal_directives.add(name)
            elif is_multi:
                raw_args = [seg for seg in colon_arg.split(",") if seg]
            else:
                raw_args = [colon_arg]
        elif plus_suffix is not None:
            raw_args = ["true"]
        else:
            raw_args = [""]

        if is_multi:
            seen_multi.setdefault(name, []).extend(raw_args)
        else:
            if name in seen:
                if name == "model":
                    models = [arg for arg in [seen[name], raw_args[0]] if arg]
                    if models:
                        source = (
                            f"{seen_source[name]} ... "
                            f"{prompt[match.start() : match_end]}"
                        )
                        raise DirectiveError(
                            multi_model_unsupported_message(source, models)
                        )
                raise DirectiveError(f"Duplicate directive '%{name}' in prompt")
            seen[name] = raw_args[0]
            seen_source[name] = prompt[match.start() : match_end]
        regions_to_remove.append((match.start(), match_end))

    if not regions_to_remove:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        if strip_disabled_markers:
            prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

    # Track whether %name was supplied with an explicit argument before any
    # auto-fill happens. Bare ``%name`` (no arg) and auto-named flows
    # (no %name at all) leave this False.
    name_explicit = bool(seen.get("name"))
    name_force_reuse = False
    if name_explicit and seen.get("name", "").startswith("!"):
        name_force_reuse = True
        seen["name"] = seen["name"][1:]

    # Auto-generate name if %name was used bare (no argument)
    if "name" in seen and not seen["name"]:
        from sase.agent.names import get_next_auto_name

        seen["name"] = get_next_auto_name()

    # %wait branch: resolve bare to previous agent; reject time-shaped
    # positional args with a migration hint pointing users to the time= keyword.
    if "wait" in seen_multi:
        resolved_wait: list[str] = []
        prev_name: str | None = None  # lazily fetched
        for raw_arg in seen_multi["wait"]:
            if not raw_arg:
                if prev_name is None:
                    from sase.agent.names import get_most_recent_agent_name

                    prev_name = get_most_recent_agent_name() or ""
                if not prev_name:
                    raise DirectiveError(
                        "Bare '%wait' directive found but no previously"
                        " named agent exists"
                    )
                resolved_wait.append(prev_name)
                continue
            if parse_duration(raw_arg) is not None:
                raise DirectiveError(
                    f"%wait:{raw_arg} is a time wait; use "
                    f"%wait(time={raw_arg}) or #t:{raw_arg} instead"
                )
            if parse_absolute_time(raw_arg) is not None:
                raise DirectiveError(
                    f"%wait:{raw_arg} is a time wait; use "
                    f"%wait(time={raw_arg}) or #t:{raw_arg} instead"
                )
            resolved_wait.append(raw_arg)
        seen_multi["wait"] = resolved_wait

    # %wait time= keyword: durations fold to wait_duration (max); a single
    # absolute time sets wait_until. Empty and non-time values are invalid.
    wait_duration: float | None = None
    wait_until: str | None = None
    if wait_time_args:
        for raw_arg in wait_time_args:
            if not raw_arg:
                raise DirectiveError(
                    "'%wait(time=...)' requires a duration or absolute time argument"
                )
            dur = parse_duration(raw_arg)
            if dur is not None:
                if wait_until is not None:
                    raise DirectiveError(
                        "Cannot combine duration and absolute time waits"
                    )
                wait_duration = max(wait_duration or 0.0, dur)
                continue
            abs_time = parse_absolute_time(raw_arg)
            if abs_time is not None:
                if wait_until is not None:
                    raise DirectiveError("Multiple absolute time waits are not allowed")
                if wait_duration is not None:
                    raise DirectiveError(
                        "Cannot combine duration and absolute time waits"
                    )
                wait_until = abs_time
                continue
            raise DirectiveError(
                f"Invalid %wait time= value '{raw_arg}'; time= accepts only "
                "durations (e.g. 5m) and absolute times (e.g. 1430). "
                f"Use %wait:{raw_arg} to wait for an agent."
            )

    # Remove directive regions from prompt (last-to-first to preserve positions)
    cleaned = prompt
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]

    # Strip the line if the directive was the only content on it
    # (remove leftover blank lines from directive removal)
    cleaned = re.sub(r"^\s*\n", "", cleaned)

    # Peel a trailing ``@<effort>`` suffix off the raw %model value before xprompt
    # expansion so directives.model stays a clean model string. Backtick-literal
    # models (``%model:`literal@id` ``) bypass the split to preserve their ``@``.
    model_effort: str | None = None
    if "model" in seen and "model" not in literal_directives:
        clean_model, model_effort = split_model_effort(seen["model"])
        seen["model"] = clean_model

    # Expand xprompt references in directive argument values
    expanded_args: dict[str, str] = {}
    for directive_name, raw_arg in seen.items():
        if raw_arg and "#" in raw_arg:
            expanded_args[directive_name] = process_xprompt_references(raw_arg).strip()
        else:
            expanded_args[directive_name] = raw_arg

    # Expand xprompt references in multi-value directive arguments
    expanded_multi: dict[str, list[str]] = {}
    for directive_name, raw_args in seen_multi.items():
        expanded_list: list[str] = []
        for raw_arg in raw_args:
            if raw_arg and "#" in raw_arg:
                expanded_list.append(process_xprompt_references(raw_arg).strip())
            else:
                expanded_list.append(raw_arg)
        expanded_multi[directive_name] = expanded_list

    name_template: str | None = None
    name_template_base: str | None = None
    name_indexed_template = False
    name_indexed_base: str | None = None
    raw_name = expanded_args.get("name")
    if raw_name:
        from sase.agent.names import (
            AgentNameTemplateError,
            agent_name_template_base,
            is_agent_name_template,
            parse_agent_name_template,
        )

        if is_agent_name_template(raw_name):
            if name_force_reuse:
                raise DirectiveError(
                    "Cannot combine forced name reuse with an agent name template"
                )
            try:
                parse_agent_name_template(raw_name)
                name_template_base = agent_name_template_base(raw_name)
            except AgentNameTemplateError as exc:
                raise DirectiveError(str(exc)) from exc
            name_template = raw_name
            name_indexed_template = True
            name_indexed_base = name_template_base

    if "wait" in expanded_multi:
        from sase.agent.names import (
            AgentNameTemplateError,
            is_agent_name_template,
            require_latest_agent_name_template,
        )

        resolved_waits: list[str] = []
        for raw_wait in expanded_multi["wait"]:
            if not is_agent_name_template(raw_wait):
                resolved_waits.append(raw_wait)
                continue
            try:
                resolved_waits.append(require_latest_agent_name_template(raw_wait))
            except AgentNameTemplateError as exc:
                raise DirectiveError(str(exc)) from exc
        expanded_multi["wait"] = resolved_waits

    # Parse repeat_count from the repeat directive
    repeat_count: int | None = None
    if "repeat" in expanded_args:
        raw_repeat = expanded_args["repeat"]
        if not raw_repeat:
            raise DirectiveError(
                "'%repeat' directive requires a positive integer argument"
                " (e.g., %repeat:3)"
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

    # Validate the %group directive value, if present. The user-facing
    # directive is %group (alias %g); it is stored on PromptDirectives.tag
    # because the persisted concept retains the "tag" name.
    raw_tag = expanded_args.get("group")
    parsed_tag: str | None = None
    if raw_tag:
        from sase.ace.agent_tags import InvalidTagError, validate_tag_name

        try:
            parsed_tag = validate_tag_name(raw_tag)
        except InvalidTagError as exc:
            raise DirectiveError(f"Invalid '%group' value: {exc}") from exc
    elif "group" in expanded_args:
        raise DirectiveError(
            "'%group' directive requires a tag name argument (e.g., %group:review)"
        )

    # Resolve the reasoning effort from the %effort directive and/or a
    # %model:<model>@<effort> suffix. The public spelling is ``effort``; the
    # stored field is ``reasoning_effort``.
    reasoning_effort = _resolve_reasoning_effort(
        effort_directive=expanded_args.get("effort"),
        effort_present="effort" in expanded_args,
        model_effort=model_effort,
    )

    auto_mode: str | None = None
    if "auto" in expanded_args:
        raw_auto_mode = expanded_args["auto"] or "plan"
        if raw_auto_mode == "true":
            raw_auto_mode = "plan"
        valid_auto_modes = ("plan", "tale", "epic")
        if raw_auto_mode not in valid_auto_modes:
            raise DirectiveError(
                f"Unknown %auto mode '{raw_auto_mode}'; valid modes are: "
                f"{', '.join(valid_auto_modes)}"
            )
        auto_mode = raw_auto_mode

    # Build PromptDirectives from expanded args. ``%auto`` and its ``%a`` alias
    # set one auto-approval mode: plan by default, or tale/epic via argument.
    directives = PromptDirectives(
        auto_mode=auto_mode,
        edit="edit" in expanded_args,
        hide="hide" in expanded_args,
        model=expanded_args.get("model") or None,
        reasoning_effort=reasoning_effort,
        name=expanded_args.get("name") or None,
        name_explicit=name_explicit,
        name_force_reuse=name_force_reuse,
        name_template=name_template,
        name_template_base=name_template_base,
        name_indexed_template=name_indexed_template,
        name_indexed_base=name_indexed_base,
        repeat_count=repeat_count,
        tag=parsed_tag,
        wait=expanded_multi.get("wait", []),
        wait_duration=wait_duration,
        wait_until=wait_until,
    )

    # Restore disabled regions, then strip markers
    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    if strip_disabled_markers:
        cleaned = strip_disabled_region_markers(cleaned)

    # Restore fenced code blocks before returning
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    return cleaned, directives
