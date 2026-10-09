"""Cheap prompt directive scanning and side-effect-free stripping."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from ._disabled_regions import protect_disabled_regions, unprotect_disabled_regions
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._exceptions import DirectiveError
from ._parsing import find_matching_paren_for_args, parse_args
from ._directive_values import classify_auto_spelling, resolve_dispatch_target

_TYPED_LAUNCH_DIRECTIVES = frozenset({"if", "proc"})


@dataclass(frozen=True, slots=True)
class _AutoDirectiveScan:
    """Side-effect-free read of the prompt's ``%auto``/``%a`` spelling.

    ``error`` carries the exact launch-path message when the spelling is
    invalid (or duplicated). ``None`` means the spelling is absent,
    valid, or Manual — display surfaces show nothing for those while
    launch validation stays authoritative.
    """

    error: str | None


@dataclass(frozen=True, slots=True)
class DispatchDirectiveScan:
    """Side-effect-free routing result for a prompt-level dispatch directive."""

    target: str
    prompt: str
    source: str


def strip_known_directives(prompt: str) -> str:
    """Remove known ``%id`` directive spans from *prompt* without side effects.

    Side-effect-free counterpart to ``extract_prompt_directives``: it strips
    the same known/directive-migration spans (colon, paren, backtick, and plus
    argument forms, plus short aliases) but never allocates auto-names, resolves
    ``%wait`` arguments, or raises on duplicate or bare directives. Unknown
    Unknown ``%directive`` tokens and directives inside fenced code blocks are left
    untouched.
    """
    if "%" not in prompt:
        return prompt

    from sase.macro.code_value import (
        scan_directive_owned_fences,
        strip_owned_code_spans,
    )

    prompt = strip_owned_code_spans(prompt, scan_directive_owned_fences(prompt))

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    regions_to_remove: list[tuple[int, int]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in _KNOWN_DIRECTIVES and name not in _DEPRECATED_DIRECTIVES:
            continue
        match_end = match.end()
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(protected, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        regions_to_remove.append((match.start(), match_end))

    cleaned = protected
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]

    return unprotect_fenced_blocks(cleaned, fenced_blocks)


def scan_dispatch_directive(prompt: str) -> DispatchDirectiveScan | None:
    """Return active dispatch routing, stripping only ``%dispatch``.

    This is intentionally cheaper and narrower than full directive extraction:
    it does not allocate auto names, resolve macro references, or strip other
    launch directives that the remote target must receive.
    """
    if "%dispatch" not in prompt:
        return None

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    target: str | None = None
    source = ""
    regions_to_remove: list[tuple[int, int]] = []
    saw_wait = False
    saw_queue = False
    saw_clan = False
    saw_hold = False

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in _KNOWN_DIRECTIVES and name not in _DEPRECATED_DIRECTIVES:
            continue
        if name == "hold":
            saw_hold = True
        if name == "wait":
            saw_wait = True
        if name == "queue":
            saw_queue = True
        if name == "clan":
            saw_clan = True
        if name != "dispatch":
            continue

        if target is not None:
            raise DirectiveError("Only one %dispatch directive is allowed per launch.")
        raw_target, match_end = _dispatch_raw_target(protected, match)
        source = protected[match.start() : match_end]
        target = resolve_dispatch_target({"dispatch": raw_target})
        regions_to_remove.append((match.start(), match_end))

    if target is None:
        return None
    if saw_wait or saw_queue or saw_clan or saw_hold:
        raise DirectiveError(
            "%dispatch cannot be combined with %wait, %queue, %clan, or %hold in V1 "
            "remote launch."
        )

    cleaned = protected
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = re.sub(r"^\s*\n", "", cleaned)
    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    return DispatchDirectiveScan(target=target, prompt=cleaned, source=source)


def set_dispatch_directive(prompt: str, target: str | None) -> str:
    """Return *prompt* with one leading ``%dispatch:<target>`` directive.

    Existing active dispatch directives are removed through
    :func:`scan_dispatch_directive`, so duplicate/conflicting dispatch syntax
    still raises the same parser error the launcher would raise.
    """
    cleaned = prompt
    scan = scan_dispatch_directive(prompt)
    if scan is not None:
        cleaned = scan.prompt
    if target is None:
        return cleaned.lstrip("\n")
    resolved = resolve_dispatch_target({"dispatch": target})
    if resolved is None:  # pragma: no cover - resolve_dispatch_target rejects this.
        return cleaned.lstrip("\n")
    body = cleaned.lstrip("\n")
    return (
        f"%dispatch:{resolved}" if not body.strip() else f"%dispatch:{resolved}\n{body}"
    )


def scan_auto_directive(prompt: str) -> _AutoDirectiveScan | None:
    """Return the prompt's ``%auto``/``%a`` state, or None when absent.

    This is intentionally cheaper and narrower than full directive
    extraction: it classifies each occurrence through the same core
    grammar the launch path uses, so an invalid spelling yields the exact
    message ``extract_prompt_directives`` would raise. Fenced and
    disabled regions are ignored through the existing literal-zone
    pipeline. A valid or Manual spelling yields a scan with ``error``
    set to None; a duplicate yields the launch path's duplicate message
    (suppressed inside ``%{...}`` fan-out, mirroring ``scan_tab_directive``,
    where each branch validates alone).
    """
    if "%a" not in prompt:
        return None

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    occurrences = 0
    first_error: str | None = None
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "auto":
            continue
        if match.group(2) is not None:
            # Parenthesized forms raise during collection, before any
            # duplicate check, exactly as the launch collector does.
            return _AutoDirectiveScan(error=_auto_match_error(protected, match))
        occurrences += 1
        if occurrences > 1 and "%{" not in protected:
            return _AutoDirectiveScan(error="Duplicate directive '%auto' in prompt")
        if first_error is None:
            first_error = _auto_match_error(protected, match)
    if occurrences == 0:
        return None
    return _AutoDirectiveScan(error=first_error)


def _auto_match_error(prompt: str, match: re.Match[str]) -> str | None:
    """Classify one ``%auto``/``%a`` match, returning its error or None.

    The form/value/spelling mapping mirrors the launch collector so the
    core message matches the launch path exactly: paren spellings keep
    their literal source slice, while colon spellings are normalized to
    ``%auto:<value>`` exactly as ``_resolve_auto_fields`` rebuilds them.
    """
    if match.group(2) is not None:
        paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
        if paren_end is not None:
            spelling = prompt[match.start() : paren_end + 1]
        else:
            spelling = prompt[match.start() : match.end()]
        form, value = "paren", ""
    elif match.group(3) is not None:
        raw = match.group(3)
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        form, value, spelling = "colon", raw, f"%auto:{raw}"
    elif match.group(4) is not None:
        form, value, spelling = "colon", "true", "%auto:true"
    else:
        form, value, spelling = "bare", "", "%auto"
    try:
        classify_auto_spelling(form=form, value=value, spelling=spelling)
    except DirectiveError as exc:
        return str(exc)
    return None


def _dispatch_raw_target(prompt: str, match: re.Match[str]) -> tuple[str, int]:
    has_open_paren = match.group(2) is not None
    colon_arg = match.group(3)
    plus_suffix = match.group(4)
    if has_open_paren:
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is None:
            raise DirectiveError(
                "Malformed %dispatch(...) directive: missing closing ')'."
            )
        positional_args, named_args = parse_args(
            prompt[paren_start + 1 : paren_end],
            reject_duplicate_named_args=True,
        )
        if named_args:
            keys = ", ".join(f"{key}=" for key in sorted(named_args))
            raise DirectiveError(
                f"Unsupported keyword on %dispatch: {keys}. "
                "%dispatch only accepts one machine alias."
            )
        non_empty = [arg for arg in positional_args if arg]
        if len(non_empty) > 1:
            raise DirectiveError(
                "%dispatch accepts exactly one machine alias argument."
            )
        return (positional_args[0] if positional_args else ""), paren_end + 1
    if colon_arg is not None:
        if colon_arg.startswith("`") and colon_arg.endswith("`"):
            return colon_arg[1:-1], match.end()
        return colon_arg, match.end()
    if plus_suffix is not None:
        raise DirectiveError("%dispatch does not support '+'; use %dispatch:<machine>.")
    return "", match.end()


def has_deferred_start_directive(prompt: str) -> bool:
    """Quick check whether a prompt defers launch."""
    if (
        _has_wait_directive(prompt)
        or _has_queue_admission_directive(prompt)
        or _has_t_time_macro_reference(prompt)
    ):
        return True
    if "#fork" not in prompt:
        return False
    from sase.agent.names import has_fork_reference

    return has_fork_reference(prompt)


def has_runner_threshold_directive(prompt: str) -> bool:
    """Quick check for an explicit runner-slot threshold directive."""
    return _has_legacy_wait_runners_directive(
        prompt,
    ) or _has_queue_runners_directive(prompt)


def _has_legacy_wait_runners_directive(prompt: str) -> bool:
    return _has_protected_pattern_match(
        prompt,
        r"(?:^|\s)%(?:wait|w)\([^)]*\brunners\s*=",
        required_substring="%",
    )


def has_model_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%model`` or ``%m`` directives."""
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:model|m)(?:[:+(]|\s|$)",
    )


def has_typed_launch_directive(prompt: str) -> bool:
    """Return whether *prompt* has an active ``%if`` or ``%proc`` directive.

    Uses the shared directive/fence contract: fenced code, inline literals, and
    ``%macros_enabled:false`` regions are inert. Parenthesized and ``::``
    fenced forms in live text count as active.
    """
    if "%if" not in prompt and "%proc" not in prompt:
        return False

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name == "if" and match.group(2) is not None:
            continue
        if name in _TYPED_LAUNCH_DIRECTIVES:
            return True
    return False


def _has_wait_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%wait`` or ``%w`` directives."""
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:wait|w)(?:[:+(]|\s|$)",
    )


def _has_queue_admission_directive(prompt: str) -> bool:
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:queue|q)(?::`?[^`\s]+`?|\()",
    )


def _has_queue_runners_directive(prompt: str) -> bool:
    return _has_protected_pattern_match(
        prompt,
        r"(?:^|\s)%(?:queue|q)(?::`?[0-9]+`?|\(\s*(?:[0-9]+|capacity\s*=)|\([^)]*,\s*capacity\s*=)",
        required_substring="%",
    )


def _has_protected_directive_match(prompt: str, pattern: str) -> bool:
    """Run a cheap directive predicate after extractor-equivalent protection."""
    return _has_protected_pattern_match(prompt, pattern, required_substring="%")


def _has_t_time_macro_reference(prompt: str) -> bool:
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
