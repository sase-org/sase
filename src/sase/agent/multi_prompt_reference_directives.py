"""Directive parsing and rewriting helpers for multi-prompt launches."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class StaticFamilyDirective:
    """Top-level parallel-family declaration visible before xprompt expansion."""

    target: str
    role: str


def extract_static_family_directive(prompt: str) -> StaticFamilyDirective | None:
    """Return a validated top-level ``%family`` declaration, when present."""
    if "%" not in prompt:
        return None

    from sase.xprompt._directive_collect import collect_prompt_directive_matches
    from sase.xprompt._directive_values import resolve_family_membership
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._exceptions import DirectiveError
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)
    collected = collect_prompt_directive_matches(protected)
    if "family" not in collected.seen:
        return None
    if collected.name_family_args is not None:
        raise DirectiveError(
            "Cannot combine %family with %n(parent, suffix); choose parallel "
            "family membership or serial family attachment."
        )
    target, role = resolve_family_membership(
        collected.seen,
        raw_role=collected.family_role,
    )
    assert target is not None and role is not None
    return StaticFamilyDirective(target=target, role=role)


def extract_static_name_directive(prompt: str) -> str | None:
    """Return an explicit top-level ``%name`` value that is safe to reuse."""
    if "%" not in prompt:
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
                positional_args, named_args = parse_args(inner)
                from sase.agent.family_attach import parse_name_directive_args

                parsed = parse_name_directive_args(
                    positional_args,
                    named_args,
                    source=f"%{raw_name}",
                )
                if parsed.family_parent is not None:
                    return None
                value = parsed.plain_name or ""
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            value = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )

        if value.startswith("!"):
            value = value[1:]
        if not value or "#" in value:
            return None
        return value
    return None


def has_bare_wait_directive(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``%wait``."""
    if "%" not in prompt:
        return False

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        return True
    return False


def rewrite_bare_wait_directives(prompt: str, agent_name: str) -> str:
    """Rewrite top-level bare ``%wait``/``%w`` directives to *agent_name*."""
    if "%" not in prompt:
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
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
            end = paren_end + 1 if paren_end is not None else match.end()
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        else:
            end = match.end()
        replacements.append((match.start(), end, f"%{raw_name}:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)
