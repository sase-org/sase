"""Template wait/resume reference rewriting for multi-prompt launches."""

from __future__ import annotations

import re
from collections.abc import Callable

from sase.agent.multi_prompt_reference_resume import _RESUME_REF_RE
from sase.core.agent_tribe import parse_tribe_reference

TemplateNameResolver = Callable[[str], str]


def rewrite_template_references(
    prompt: str,
    resolve_template_name: TemplateNameResolver,
) -> str:
    """Resolve template wait/resume refs using a launch-local name resolver."""
    prompt = _rewrite_template_wait_directives(prompt, resolve_template_name)
    return _rewrite_template_resume_references(prompt, resolve_template_name)


def _rewrite_template_wait_directives(
    prompt: str,
    resolve_template_name: TemplateNameResolver,
) -> str:
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
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue

        colon_arg = match.group(3)
        if colon_arg is not None:
            resolved_args = _resolve_template_arg_list(
                _unquote_backtick_arg(colon_arg).split(","),
                resolve_template_name,
            )
            if resolved_args is None:
                continue
            replacements.append(
                (
                    match.start(),
                    match.end(),
                    f"%{raw_name}:{','.join(resolved_args)}",
                )
            )
            continue

        if match.group(2) is None:
            continue

        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        inner = protected[paren_start + 1 : paren_end]
        positional_args, _ = parse_args(inner)
        resolved_args = _resolve_template_arg_list(
            list(positional_args),
            resolve_template_name,
        )
        if resolved_args is None:
            continue
        replacements.append(
            (
                match.start(),
                paren_end + 1,
                f"%{raw_name}({','.join(resolved_args)})",
            )
        )

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _rewrite_template_resume_references(
    prompt: str,
    resolve_template_name: TemplateNameResolver,
) -> str:
    if "#fork" not in prompt and "#resume" not in prompt:
        return prompt

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
    for match in _RESUME_REF_RE.finditer(protected):
        kind = match.group("kind")
        colon = match.group("colon")
        if colon is not None:
            if colon.startswith("`") and colon.endswith("`"):
                colon_args = [_unquote_backtick_arg(colon)]
            else:
                colon_args, _ = parse_args(colon, preserve_empty_args=True)
            resolved_args = _resolve_template_arg_list(
                colon_args,
                resolve_template_name,
            )
            if resolved_args is not None:
                replacements.append(
                    (
                        match.start(),
                        match.end(),
                        f"#{kind}:{','.join(resolved_args)}",
                    )
                )
            continue

        if match.group("open_paren") is None:
            continue
        paren_start = match.end("open_paren") - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        inner = protected[paren_start + 1 : paren_end]
        positional_args, _ = parse_args(inner, preserve_empty_args=True)
        if not positional_args:
            continue
        resolved_args = _resolve_template_arg_list(
            positional_args,
            resolve_template_name,
        )
        if resolved_args is not None:
            replacements.append(
                (
                    match.start(),
                    paren_end + 1,
                    f"#{kind}({','.join(resolved_args)})",
                )
            )

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _resolve_template_arg_list(
    args: list[str],
    resolve_template_name: TemplateNameResolver,
) -> list[str] | None:
    resolved: list[str] = []
    changed = False
    for arg in args:
        value = _resolve_template_arg(arg, resolve_template_name)
        if value is None:
            resolved.append(arg)
        else:
            resolved.append(value)
            changed = True
    return resolved if changed else None


def _resolve_template_arg(
    arg: str,
    resolve_template_name: TemplateNameResolver,
) -> str | None:
    from sase.agent.names import is_agent_name_template

    if parse_tribe_reference(arg) is not None:
        return None
    if not is_agent_name_template(arg):
        return None
    return resolve_template_name(arg)


def _unquote_backtick_arg(arg: str) -> str:
    if arg.startswith("`") and arg.endswith("`"):
        return arg[1:-1]
    return arg
