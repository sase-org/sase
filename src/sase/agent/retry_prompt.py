"""Shared prompt helpers for retrying agents."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Literal


def rewrite_retry_prompt_name(
    raw_prompt: str,
    retry_name: str,
    *,
    directive_alias: Literal["id", "i"] = "id",
) -> str:
    """Replace or prepend the top-level prompt ``%id`` directive for retry."""
    from sase.agent.family_attach import extract_family_attach_directive
    from sase.xprompt.directive_edit import set_prompt_name

    # A retry name is already the concrete derived name (for example,
    # ``foo--reviewer.r0``). Keeping family= would reinterpret that full name
    # as a bare family suffix, producing an invalid directive. Drop only that
    # obsolete membership attachment; orthogonal launch metadata such as
    # bead= must survive the retry.
    family_retry = extract_family_attach_directive(raw_prompt) is not None
    return set_prompt_name(
        raw_prompt,
        retry_name,
        directive_alias=directive_alias,
        drop_kwargs=frozenset({"family"}) if family_retry else frozenset(),
    )


def prompt_has_id_directive(prompt: str) -> bool:
    """Whether *prompt* explicitly declares a top-level ``%id``/``%i`` with a name."""
    for match, _protected, _restore in _iter_top_level_id_directives(prompt):
        return match.group(2) is not None or match.group(3) is not None
    return False


def force_name_reuse_in_prompt(
    raw_prompt: str,
    *,
    replacement_name: str | None = None,
) -> str:
    """Mark the first explicit top-level ``%id`` directive for forced reuse."""
    from sase.agent.names import is_agent_name_template
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    scan: tuple[str, Callable[[str], str]] | None = None
    for match, protected, restore in _iter_top_level_id_directives(raw_prompt):
        scan = (protected, restore)
        raw_name = match.group(1)
        insertion_index: int | None = None
        directive_value: str | None = None
        replacement_span: tuple[int, int] | None = None
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is None:
                break
            inner = protected[paren_start + 1 : paren_end]
            positional_args, _ = parse_args(inner)
            if not positional_args or positional_args[0].startswith("!"):
                break
            directive_value = positional_args[0]
            replacement_span = (match.start(), paren_end + 1)
            stripped_inner = inner.lstrip()
            if not stripped_inner:
                break
            insertion_index = paren_start + 1 + (len(inner) - len(stripped_inner))
            if stripped_inner[0] in ('"', "'"):
                insertion_index += 1
            elif stripped_inner.startswith("[["):
                insertion_index += 2
        elif match.group(3) is not None:
            raw_arg = match.group(3)
            insertion_index = match.start(3)
            if raw_arg.startswith("`") and raw_arg.endswith("`"):
                value = raw_arg[1:-1]
                if value.startswith("!"):
                    break
                directive_value = value
                replacement_span = (match.start(), match.end())
                insertion_index += 1
            elif raw_arg.startswith("!"):
                break
            else:
                directive_value = raw_arg
                replacement_span = (match.start(), match.end())
        else:
            break

        if directive_value and is_agent_name_template(directive_value):
            if replacement_name is None:
                break
            assert replacement_span is not None
            start, end = replacement_span
            rewritten = (
                f"{protected[:start]}%{raw_name}:!{replacement_name}{protected[end:]}"
            )
            return restore(rewritten)

        rewritten = (
            f"{protected[:insertion_index]}!{protected[insertion_index:]}"
            if insertion_index is not None
            else protected
        )
        return restore(rewritten)

    if scan is None:
        return raw_prompt
    protected, restore = scan
    return restore(protected)


def _iter_top_level_id_directives(
    prompt: str,
) -> Iterator[tuple[re.Match[str], str, Callable[[str], str]]]:
    """Yield each top-level ``%id``/``%i`` on a fence- and disabled-protected scan.

    Both :func:`prompt_has_id_directive` and :func:`force_name_reuse_in_prompt`
    must walk the same protected text so the kill-and-edit gate cannot fire on
    a directive the rewriter would ignore.
    """
    if "%i" not in prompt:
        return

    from sase.xprompt._directive_types import (
        _DIRECTIVE_ALIASES,
        _DIRECTIVE_PATTERN,
    )
    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    def restore(text: str) -> str:
        return unprotect_fenced_blocks(
            unprotect_disabled_regions(text, disabled),
            fenced,
        )

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "id":
            continue
        yield match, protected, restore
