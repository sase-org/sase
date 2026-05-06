"""Prompt directive parsing (%name tag system).

Directives are in-prompt tags with a ``%`` prefix that modify runner behavior.
They are extracted and stripped from the prompt before further preprocessing.
Directive arguments use the same syntax as xprompts (colon, paren, backtick, plus).

Example::

    %model:#gemini_small_model
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
predicates.  It re-exports the private helpers that existing tests
import from ``sase.xprompt.directives``.
"""

import re

from ._directive_alt import (
    apply_fanout_naming,
    has_alt_directive,
    plan_prompt_fanout_variants,
    split_prompt_for_alternatives,
    split_prompt_for_models,
)
from ._directive_time import parse_absolute_time, parse_duration
from ._directive_types import (
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
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args, parse_args
from .processor import process_xprompt_references

__all__ = [
    "PromptDirectives",
    "apply_fanout_naming",
    "extract_prompt_directives",
    "has_alt_directive",
    "has_model_directive",
    "has_wait_directive",
    "parse_absolute_time",
    "parse_duration",
    "plan_prompt_fanout_variants",
    "split_prompt_for_alternatives",
    "split_prompt_for_models",
]


def has_wait_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%wait`` or ``%w`` directives.

    This avoids the overhead of full xprompt expansion and is suitable for
    early detection in the agent launcher.
    """
    if "%" not in prompt:
        return False
    return bool(re.search(r"(?:^|\s)%(?:wait|w)(?:[:+(]|\s|$)", prompt, re.MULTILINE))


def has_model_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%model`` or ``%m`` directives.

    This avoids the overhead of full directive extraction and is suitable for
    checking whether a user's custom prompt already specifies a model.
    """
    if "%" not in prompt:
        return False
    return bool(re.search(r"(?:^|\s)%(?:model|m)(?:[:+(]|\s|$)", prompt, re.MULTILINE))


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
        DirectiveError: If a known non-``%model`` directive appears more
            than once.  Multiple ``%model`` directives are tolerated with
            last-wins semantics; multi-model splitting is normally handled
            upstream by :func:`split_prompt_for_models`.
    """
    if "%" not in prompt:
        return prompt, PromptDirectives()

    # Protect fenced code blocks so directives inside them are ignored
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # Protect disabled regions so old directives inside #resume
    # expansions are not re-parsed.
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    matches = list(re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE))
    if not matches:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        if strip_disabled_markers:
            prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

    # Collect known directive matches (we'll strip these from the prompt)
    seen: dict[str, str] = {}  # directive name -> raw arg value (single-value)
    seen_multi: dict[
        str, list[str]
    ] = {}  # directive name -> raw arg values (multi-value)
    # Regions to remove: list of (start, end) character positions
    regions_to_remove: list[tuple[int, int]] = []

    for match in matches:
        name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(name, name)  # resolve alias
        if name not in _KNOWN_DIRECTIVES:
            continue

        # Check for duplicates (multi-value directives are allowed to repeat).
        # `%model` is a soft exception: repeated `%model` directives are
        # normally collapsed by :func:`split_prompt_for_models` upstream.
        # If a caller bypasses the splitter, we tolerate duplicates here
        # with last-wins semantics so the prompt still extracts cleanly.
        if name in _MULTI_VALUE_DIRECTIVES or name == "model":
            pass  # handled below after arg extraction
        elif name in seen:
            raise DirectiveError(f"Duplicate directive '%{name}' in prompt")

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
                positional_args, _ = parse_args(paren_content)
                if is_multi:
                    raw_args = list(positional_args)
                else:
                    raw_args = [positional_args[0] if positional_args else ""]
                match_end = paren_end + 1
            else:
                raw_args = [""]
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_args = [colon_arg[1:-1]]
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
            seen[name] = raw_args[0]
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

    # Auto-generate name if %name was used bare (no argument)
    if "name" in seen and not seen["name"]:
        from sase.agent.names import get_next_auto_name

        seen["name"] = get_next_auto_name()

    # Resolve bare %wait directives to the most recently named agent,
    # and separate duration/absolute-time arguments from agent-name arguments.
    wait_duration: float | None = None
    wait_until: str | None = None
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
            else:
                dur = parse_duration(raw_arg)
                if dur is not None:
                    # Take the max if multiple durations appear
                    wait_duration = max(wait_duration or 0.0, dur)
                else:
                    abs_time = parse_absolute_time(raw_arg)
                    if abs_time is not None:
                        if wait_until is not None:
                            raise DirectiveError(
                                "Multiple absolute time waits are not allowed"
                            )
                        if wait_duration is not None:
                            raise DirectiveError(
                                "Cannot combine duration and absolute time waits"
                            )
                        wait_until = abs_time
                    else:
                        resolved_wait.append(raw_arg)
        if wait_until is not None and wait_duration is not None:
            raise DirectiveError("Cannot combine duration and absolute time waits")
        seen_multi["wait"] = resolved_wait

    # Remove directive regions from prompt (last-to-first to preserve positions)
    cleaned = prompt
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]

    # Strip the line if the directive was the only content on it
    # (remove leftover blank lines from directive removal)
    cleaned = re.sub(r"^\s*\n", "", cleaned)

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

    # Validate the %tag directive value, if present.
    raw_tag = expanded_args.get("tag")
    parsed_tag: str | None = None
    if raw_tag:
        from sase.ace.agent_tags import InvalidTagError, validate_tag_name

        try:
            parsed_tag = validate_tag_name(raw_tag)
        except InvalidTagError as exc:
            raise DirectiveError(f"Invalid '%tag' value: {exc}") from exc
    elif "tag" in expanded_args:
        raise DirectiveError(
            "'%tag' directive requires a tag name argument (e.g., %tag:review)"
        )

    # Build PromptDirectives from expanded args
    directives = PromptDirectives(
        approve="approve" in expanded_args,
        edit="edit" in expanded_args,
        epic="epic" in expanded_args,
        hide="hide" in expanded_args,
        model=expanded_args.get("model") or None,
        name=expanded_args.get("name") or None,
        name_explicit=name_explicit,
        plan="plan" in expanded_args,
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
