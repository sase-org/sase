"""Prompt directive parsing (%name tag system).

Directives are in-prompt tags with a ``%`` prefix that modify runner behavior.
They are extracted and stripped from the prompt before further preprocessing.
Directive arguments use the same syntax as xprompts (colon, paren, backtick, plus).

Example::

    %model:#gemini_small_model
    Review this code...

The ``%model`` directive overrides the LLM model used for that prompt.
"""

import itertools
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
    {"approve", "edit", "hide", "model", "name", "plan", "repeat", "wait"}
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
    "r": "repeat",
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
    repeat_count: int | None = None
    wait: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None


# Pattern to match %alt( or %( at a directive-valid position.
_ALT_DIRECTIVE_RE = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"(%(?:alt)?)\(",
    re.MULTILINE,
)


def _split_prompt_for_alternatives(prompt: str) -> list[str] | None:
    """Split a prompt containing ``%alt(...)`` or ``%(...)`` into per-alternative prompts.

    Each argument becomes a separate prompt with the directive span replaced
    by that argument's text.  Arguments can be arbitrary text — directives,
    xprompt references, plain instructions, or ``[[text blocks]]``.

    ``%(...)`` is syntactic sugar for ``%alt(...)``.

    When multiple ``%alt``/``%(`` directives appear, a Cartesian product of
    all argument lists is computed — e.g. two directives with 2 and 3
    arguments produce 2 × 3 = 6 prompts.

    Returns ``None`` if there are no ``%alt``/``%(`` directives or all have
    zero arguments.  A single-arg ``%alt(foo)`` / ``%(foo)`` is treated as
    having an implicit empty variant, producing two alternatives for that
    directive.

    Raises:
        DirectiveError: If an opening parenthesis has no matching close.
    """
    matches = list(_ALT_DIRECTIVE_RE.finditer(prompt))
    if not matches:
        return None

    # Collect directive spans and their argument lists.
    directives: list[tuple[int, int, list[str]]] = []
    for match in matches:
        paren_start = match.end() - 1  # position of '('
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is None:
            raise DirectiveError(
                "Unclosed '%alt('/'%(' directive — missing closing ')'"
            )

        inner = prompt[paren_start + 1 : paren_end]
        positional_args, _ = parse_args(inner)

        if len(positional_args) == 0:
            continue

        # Single arg: treat as "with/without" — append an implicit empty variant.
        if len(positional_args) == 1:
            positional_args.append("")

        directives.append((match.start(1), paren_end + 1, positional_args))

    if not directives:
        return None

    # Compute Cartesian product of all argument lists.
    all_arg_lists = [d[2] for d in directives]
    result: list[str] = []
    for combination in itertools.product(*all_arg_lists):
        # Replace spans right-to-left so earlier positions aren't shifted.
        replaced = prompt
        for (span_start, span_end, _), arg in reversed(
            list(zip(directives, combination, strict=True))
        ):
            replaced = replaced[:span_start] + arg + replaced[span_end:]
        result.append(replaced)
    return result


def split_prompt_for_models(prompt: str) -> list[str] | None:
    """Split a prompt with multi-model or ``%alt``/``%(`` directives into per-variant prompts.

    Handles three cases:

    1. ``%model(a,b,...)`` / ``%m(a,b,...)`` — rewritten internally to
       ``%alt(%model:a,%model:b,...)`` then split.
    2. Repeated scalar ``%model`` / ``%m`` directives (e.g.
       ``%model:opus\\n%model:sonnet``) — collected, deduped in document
       order, and collapsed into a single ``%alt(%model:a,%model:b,...)``
       before splitting.  Mixing scalar and paren forms is supported.
    3. Direct ``%alt(...)`` or ``%(...)`` usage — split as-is.

    Multiple model directives that all resolve to the same model yield a
    single variant (no split); duplicate ``%model`` directives inside
    fenced code blocks or ``%xprompts_enabled:false`` regions are ignored.

    Returns ``None`` if there is nothing to split (single unique model,
    single alt argument, or no splitting directive at all).  When only one
    unique model remains but multiple ``%model`` directives exist, the
    duplicates are tolerated downstream by :func:`extract_prompt_directives`
    (last-wins).
    """
    if "%" not in prompt:
        return None

    # Protect fenced code blocks and disabled regions so %model directives
    # inside them are neither collected nor rewritten.
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    # Identify inner regions of %alt(...) / %(...) so %model matches
    # nested inside them are not double-collected (they're handled by
    # _split_prompt_for_alternatives).
    alt_inner_regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(protected):
        paren_start = alt_match.end() - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        alt_inner_regions.append((paren_start + 1, paren_end))

    def _is_inside_alt(pos: int) -> bool:
        return any(start <= pos < end for start, end in alt_inner_regions)

    # Walk all directive matches and pick out %model / %m occurrences.
    directive_spans: list[tuple[int, int, list[str]]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        resolved = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if resolved != "model":
            continue
        if _is_inside_alt(match.start()):
            continue

        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()
        args: list[str] = []

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                paren_content = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(paren_content)
                args = [a for a in positional_args if a]
                match_end = paren_end + 1
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                value = colon_arg[1:-1]
            else:
                value = colon_arg
            if value:
                args = [value]
        elif plus_suffix is not None:
            # %model+ is a plus-syntax sentinel with no real model value —
            # leave it alone for the extractor to handle.
            continue
        # Bare %model (no arg) contributes no model but its span is still
        # eligible for rewrite so the prompt stays clean.

        directive_spans.append((match.start(), match_end, args))

    if not directive_spans:
        # No collectable %model directives — fall through to alt-only handling
        # on the original (unprotected) prompt.
        return _split_prompt_for_alternatives(prompt)

    # Dedupe model args in document order (first occurrence wins).
    seen_models: set[str] = set()
    unique_models: list[str] = []
    for _, _, args in directive_spans:
        for arg in args:
            if arg not in seen_models:
                seen_models.add(arg)
                unique_models.append(arg)

    if len(unique_models) <= 1:
        # Zero or one unique model — no split needed.  Any duplicate scalar
        # %model directives are tolerated by extract_prompt_directives.
        return _split_prompt_for_alternatives(prompt)

    # Two or more unique models — collapse every collected span into a
    # single %alt(%model:a,%model:b,...) directive at the first span's
    # position and remove the others.
    alt_args = ",".join(f"%model:{m}" for m in unique_models)
    replacement = f"%alt({alt_args})"

    # Absorb a trailing newline for non-first spans that occupy a whole
    # line, so the rewrite does not leave behind blank lines.
    adjusted: list[tuple[int, int, bool]] = []
    for i, (span_start, span_end, _) in enumerate(directive_spans):
        is_first = i == 0
        if (
            not is_first
            and span_end < len(protected)
            and protected[span_end] == "\n"
            and (span_start == 0 or protected[span_start - 1] == "\n")
        ):
            span_end += 1
        adjusted.append((span_start, span_end, is_first))

    # Splice right-to-left so earlier positions aren't shifted.
    rewritten = protected
    for span_start, span_end, is_first in reversed(adjusted):
        if is_first:
            rewritten = rewritten[:span_start] + replacement + rewritten[span_end:]
        else:
            rewritten = rewritten[:span_start] + rewritten[span_end:]

    rewritten = unprotect_disabled_regions(rewritten, disabled_regions)
    rewritten = unprotect_fenced_blocks(rewritten, fenced_blocks)

    return _split_prompt_for_alternatives(rewritten)


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


def has_alt_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains a ``%alt(`` or ``%(`` directive.

    This avoids the overhead of full splitting and is suitable for
    early detection in the CLI auto-daemon routing.
    """
    if "%" not in prompt:
        return False
    return bool(re.search(r"(?:^|\s)%(?:alt)?\(", prompt, re.MULTILINE))


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
        if strip_disabled_markers:
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

    # Build PromptDirectives from expanded args
    directives = PromptDirectives(
        approve="approve" in expanded_args,
        edit="edit" in expanded_args,
        hide="hide" in expanded_args,
        model=expanded_args.get("model") or None,
        name=expanded_args.get("name") or None,
        plan="plan" in expanded_args,
        repeat_count=repeat_count,
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
