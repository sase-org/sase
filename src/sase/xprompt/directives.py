"""Prompt directive parsing (%name tag system).

Directives are in-prompt tags with a ``%`` prefix that modify runner behavior.
They are extracted and stripped from the prompt before further preprocessing.
Directive arguments use the same syntax as xprompts (colon, paren, backtick, plus).

Example::

    %model:#gemini_small_model
    Review this code...

The ``%model`` directive overrides the LLM model used for that prompt.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from ._exceptions import DirectiveError
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args, parse_args
from .processor import process_xprompt_references

_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_HHMM_RE = re.compile(r"^\d{4}$")
_YYMMDD_HHMM_RE = re.compile(r"^(\d{6})/(\d{4})$")


def _parse_absolute_time(s: str) -> str | None:
    """Parse an absolute time string into an ISO 8601 target datetime.

    Supported formats:

    - **HHMM** — wait until that time today (wraps to tomorrow if past).
    - **yymmdd/HHMM** — wait until a specific date and time.

    Returns an ISO 8601 string (``YYYY-MM-DDTHH:MM:SS``) or ``None``
    if *s* does not match either format.

    Raises:
        DirectiveError: If the time is invalid or a dated target is in the past.
    """
    m = _YYMMDD_HHMM_RE.match(s)
    if m:
        date_part, time_part = m.group(1), m.group(2)
        hh, mm = int(time_part[:2]), int(time_part[2:])
        if hh > 23 or mm > 59:
            raise DirectiveError(
                f"Invalid time '{time_part}' in '%wait:{s}'"
                f" — hours must be 00-23 and minutes 00-59"
            )
        yy = int(date_part[:2])
        mo = int(date_part[2:4])
        dd = int(date_part[4:6])
        if mo < 1 or mo > 12:
            raise DirectiveError(
                f"Invalid month '{mo:02d}' in '%wait:{s}' — month must be 01-12"
            )
        if dd < 1 or dd > 31:
            raise DirectiveError(
                f"Invalid day '{dd:02d}' in '%wait:{s}' — day must be 01-31"
            )
        try:
            target = datetime(2000 + yy, mo, dd, hh, mm)
        except ValueError as exc:
            raise DirectiveError(f"Invalid date/time in '%wait:{s}' — {exc}") from exc
        if target <= datetime.now():
            raise DirectiveError(f"Target time '%wait:{s}' is in the past")
        return target.isoformat()

    if _HHMM_RE.match(s):
        hh, mm = int(s[:2]), int(s[2:])
        if hh > 23 or mm > 59:
            raise DirectiveError(
                f"Invalid time '{s}' in '%wait:{s}'"
                f" — hours must be 00-23 and minutes 00-59"
            )
        now = datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.isoformat()

    return None


def _parse_duration(s: str) -> float | None:
    """Parse a duration string like ``5m``, ``1h30m``, ``1h30m15s`` into seconds.

    Returns total seconds as a float, or ``None`` if *s* does not match the
    ``XhYmZs`` pattern.  Units must appear in h > m > s order; each unit may
    appear at most once.
    """
    if not s or not s[0].isdigit():
        return None
    m = _DURATION_RE.match(s)
    if not m:
        return None
    hours_s, minutes_s, seconds_s = m.groups()
    if hours_s is None and minutes_s is None and seconds_s is None:
        return None
    hours = int(hours_s) if hours_s else 0
    minutes = int(minutes_s) if minutes_s else 0
    seconds = int(seconds_s) if seconds_s else 0
    return float(hours * 3600 + minutes * 60 + seconds)


# Pattern to match directive references: %name, %name(, %name:arg, %name:`arg`, %name+
# Mirrors _XPROMPT_PATTERN from processor.py but with % prefix.
# The colon-arg character class is expanded to include # (for xprompt refs in args).
_DIRECTIVE_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"%([a-zA-Z_][a-zA-Z0-9_]*)"  # Group 1: directive name
    r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_#/.()-]*[a-zA-Z0-9_#/()-])|(\+))?"  # Group 2: paren OR Group 3: colon arg OR Group 4: plus
)

# Known directive names
_KNOWN_DIRECTIVES = frozenset(
    {"approve", "edit", "hide", "model", "name", "plan", "wait"}
)

# Directives that allow multiple occurrences (values are collected into a list)
_MULTI_VALUE_DIRECTIVES = frozenset({"wait"})

# Short aliases for directives (alias -> canonical name)
_DIRECTIVE_ALIASES: dict[str, str] = {
    "a": "approve",
    "e": "edit",
    "h": "hide",
    "m": "model",
    "n": "name",
    "p": "plan",
    "w": "wait",
}


@dataclass
class PromptDirectives:
    """Parsed prompt directives that modify runner behavior.

    Attributes:
        model: Model override string, or None to use the default.
        name: Agent name assigned via %name directive, or None.
        wait: List of agent names to wait for via %wait directives.
    """

    approve: bool = False
    edit: bool = False
    hide: bool = False
    model: str | None = None
    name: str | None = None
    plan: bool = False
    wait: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None


# Pattern to match %model(...) or %m(...) with parenthesized arguments.
_MULTI_MODEL_RE = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"(%(?:model|m))\(([^)]*)\)",
    re.MULTILINE,
)


def split_prompt_for_models(prompt: str) -> list[str] | None:
    """Split a prompt with a multi-model directive into per-model prompts.

    If the prompt contains ``%model(a,b,...)`` or ``%m(a,b,...)`` with
    multiple comma-separated model names, returns a list of prompts where
    each has the multi-model directive replaced with a single ``%model:X``
    directive.

    Returns ``None`` if there is no multi-model directive (single model
    or no model directive at all).
    """
    match = _MULTI_MODEL_RE.search(prompt)
    if match is None:
        return None

    inner = match.group(2)
    positional_args, _ = parse_args(inner)
    if len(positional_args) <= 1:
        return None

    result: list[str] = []
    for model in positional_args:
        replaced = prompt[: match.start(1)] + f"%model:{model}" + prompt[match.end() :]
        result.append(replaced)
    return result


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


def extract_prompt_directives(prompt: str) -> tuple[str, PromptDirectives]:
    """Extract ``%name`` directives from a prompt.

    Finds all ``%name`` patterns in the prompt. Known directives are parsed,
    their xprompt references expanded, and they are stripped from the prompt.
    Unknown ``%name`` patterns are left in the prompt unchanged.

    Args:
        prompt: The raw prompt text.

    Returns:
        Tuple of (cleaned_prompt, directives).

    Raises:
        DirectiveError: If a known directive appears more than once.
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

        # Check for duplicates (multi-value directives are allowed to repeat)
        if name in _MULTI_VALUE_DIRECTIVES:
            pass  # handled below after arg extraction
        elif name in seen:
            raise DirectiveError(f"Duplicate directive '%{name}' in prompt")

        # Extract argument value
        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(prompt, paren_start)
            if paren_end is not None:
                paren_content = prompt[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(paren_content)
                raw_arg = positional_args[0] if positional_args else ""
                match_end = paren_end + 1
            else:
                raw_arg = ""
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_arg = colon_arg[1:-1]
            else:
                raw_arg = colon_arg
        elif plus_suffix is not None:
            raw_arg = "true"
        else:
            raw_arg = ""

        if name in _MULTI_VALUE_DIRECTIVES:
            seen_multi.setdefault(name, []).append(raw_arg)
        else:
            seen[name] = raw_arg
        regions_to_remove.append((match.start(), match_end))

    if not regions_to_remove:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

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
                dur = _parse_duration(raw_arg)
                if dur is not None:
                    # Take the max if multiple durations appear
                    wait_duration = max(wait_duration or 0.0, dur)
                else:
                    abs_time = _parse_absolute_time(raw_arg)
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

    # Build PromptDirectives from expanded args
    directives = PromptDirectives(
        approve="approve" in expanded_args,
        edit="edit" in expanded_args,
        hide="hide" in expanded_args,
        model=expanded_args.get("model") or None,
        name=expanded_args.get("name") or None,
        plan="plan" in expanded_args,
        wait=expanded_multi.get("wait", []),
        wait_duration=wait_duration,
        wait_until=wait_until,
    )

    # Restore disabled regions, then strip markers
    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    cleaned = strip_disabled_region_markers(cleaned)

    # Restore fenced code blocks before returning
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    return cleaned, directives
