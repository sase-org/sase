"""Identity, clan, family, and tribe prompt directive edits."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ._directive_edit_core import (
    find_alt_inner_regions,
    format_directive_arg,
    insert_directive,
    is_inside_regions,
    protect_ignored_regions,
    remove_spans,
    rewrite_protected_prompt,
    set_prompt_directive,
)
from ._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from ._parsing import find_matching_paren_for_args, parse_arg_spans, parse_args


@dataclass(frozen=True)
class _PromptIdDirective:
    start: int
    end: int
    positional: tuple[str, ...]
    named: dict[str, str]


def set_prompt_name(
    prompt: str,
    name: str,
    *,
    directive_alias: Literal["id", "i"] = "id",
    preserve_kwargs: bool = True,
    drop_kwargs: frozenset[str] = frozenset(),
) -> str:
    """Return *prompt* with a canonical ``%id`` and optional existing kwargs."""
    protected, restore = protect_ignored_regions(prompt)
    directive = _find_prompt_id_directive(protected)
    if directive is None:
        return restore(insert_directive(protected, f"%{directive_alias}:{name}"))
    named = directive.named if preserve_kwargs else {}
    if drop_kwargs:
        named = {key: value for key, value in named.items() if key not in drop_kwargs}
    replacement = _format_id_directive(
        name,
        named,
        directive_alias=directive_alias,
    )
    rewritten = protected[: directive.start] + replacement + protected[directive.end :]
    return restore(rewritten)


def demote_prompt_clan_declaration(prompt: str) -> str:
    """Rewrite a declaring clan member into the join form for relaunch."""
    from sase.xprompt.directives import extract_prompt_directives

    _, directives = extract_prompt_directives(prompt)
    if not directives.clan_declared:
        return prompt
    if directives.clan is None or directives.name is None:
        raise ValueError(
            "Cannot relaunch a clan declaration without an explicit member name."
        )

    return rewrite_prompt_clan_member_name(
        prompt,
        directives.name,
        force_reuse=directives.name_force_reuse,
    )


def rewrite_prompt_clan_member_name(
    prompt: str,
    agent_name: str,
    *,
    current_agent_name: str | None = None,
    force_reuse: bool = False,
) -> str:
    """Rewrite a clan member to a concrete join-form agent name.

    ``current_agent_name`` resolves an ``@`` clan template from the stored
    prompt before the replacement name is validated. Relaunch callers know
    that concrete name even when the prompt still contains the original
    template.
    """
    from sase.agent.names import (
        is_agent_name_template,
        match_agent_name_template,
        render_agent_name_template,
    )
    from sase.xprompt.directives import extract_prompt_directives

    _, directives = extract_prompt_directives(prompt)
    if directives.clan is None or directives.name is None:
        raise ValueError("Cannot rewrite a prompt without clan membership.")

    clan_name = directives.clan
    if is_agent_name_template(clan_name) and current_agent_name is not None:
        token = match_agent_name_template(directives.name, current_agent_name)
        if token is None:
            raise ValueError(
                f"Cannot resolve clan template '{clan_name}' from agent "
                f"'{current_agent_name}'."
            )
        clan_name = render_agent_name_template(clan_name, token)
    elif is_agent_name_template(clan_name) and not is_agent_name_template(agent_name):
        if current_agent_name is None:
            raise ValueError(
                f"Cannot resolve clan template '{clan_name}' without the "
                "current concrete agent name."
            )

    prefix = f"{clan_name}."
    if not agent_name.startswith(prefix) or not agent_name.removeprefix(prefix):
        raise ValueError(
            f"Cannot relaunch agent '{agent_name}' as a member of clan "
            f"'{clan_name}': expected the '{prefix}<suffix>' hood."
        )
    member_id = agent_name.removeprefix(prefix)
    if force_reuse:
        member_id = f"!{member_id}"
    replacement_parts = [
        format_directive_arg(member_id),
        f"clan={format_directive_arg(clan_name)}",
    ]
    if directives.bead_id:
        replacement_parts.append(f"bead={format_directive_arg(directives.bead_id)}")
    replacement = f"%id({', '.join(replacement_parts)})"
    rewritten = (
        set_prompt_directive(prompt, {"clan"}, None)
        if directives.clan_declared
        else prompt
    )
    return set_prompt_directive(rewritten, {"id"}, replacement)


def rewrite_prompt_family_member_name(
    prompt: str,
    family_name: str,
    role_suffix: str,
    *,
    force_reuse: bool = False,
    bead_id: str | None = None,
) -> str:
    """Rewrite a prompt as an exact serial-family attachment.

    Existing ``bead=`` metadata wins over *bead_id*. Clan/tribe membership
    syntax is intentionally dropped: the family resolver restores inherited
    clan and tribe context from the authoritative parent.
    """
    from sase.plan_chain import agent_family_suffix_token, canonical_plan_chain_suffix
    from sase.xprompt.directives import extract_prompt_directives

    canonical_suffix = canonical_plan_chain_suffix(role_suffix)
    suffix = agent_family_suffix_token(canonical_suffix or role_suffix)
    if not family_name or not suffix:
        raise ValueError("Cannot rewrite a family member without a family and suffix.")

    _, directives = extract_prompt_directives(prompt)
    effective_bead = directives.bead_id or bead_id
    member_id = f"!{suffix}" if force_reuse else suffix
    replacement_parts = [
        format_directive_arg(member_id),
        f"family={format_directive_arg(family_name)}",
    ]
    if effective_bead:
        replacement_parts.append(f"bead={format_directive_arg(effective_bead)}")
    replacement = f"%id({', '.join(replacement_parts)})"

    rewritten = prompt
    if directives.clan_declared:
        rewritten = set_prompt_directive(rewritten, {"clan"}, None)
    return set_prompt_directive(rewritten, {"id"}, replacement)


def set_prompt_tribe(prompt: str, tribe: str | None) -> str:
    """Add, replace, or remove the ``tribe=`` keyword on ``%id``."""
    if _prompt_has_effective_clan(prompt):
        rewritten = set_prompt_clan_tribe(prompt, tribe)
        return set_prompt_directive(rewritten, {"g", "group", "tribe"}, None)

    # Editing an existing agent also migrates launch prompts written before
    # tribes replaced groups. These spellings remain unsupported by the
    # runtime parser; recognizing them here is cleanup, not a legacy alias.
    protected, restore = protect_ignored_regions(prompt)
    protected = rewrite_protected_prompt(
        protected,
        {"g", "group", "tribe"},
        None,
        remove_deprecated=False,
        remove_time_xprompts=False,
    )
    directive = _find_prompt_id_directive(protected)
    if directive is None:
        if tribe is None:
            return restore(protected)
        return restore(insert_directive(protected, f"%id(tribe={tribe})"))

    named = dict(directive.named)
    if tribe is not None:
        conflicting = sorted(key for key in named if key in {"clan", "family"})
        if conflicting:
            keyword = conflicting[0]
            raise ValueError(
                f"Cannot set tribe= on an %id directive that already uses "
                f"{keyword}=; clan=, family=, and tribe= are mutually exclusive."
            )
        named["tribe"] = tribe
    else:
        if "tribe" not in named:
            return restore(protected)
        named.pop("tribe")

    name = directive.positional[0] if directive.positional else None
    if name is None and not named:
        rewritten = remove_spans(
            protected,
            [(directive.start, directive.end)],
        )
    else:
        replacement = _format_id_directive(name, named)
        rewritten = (
            protected[: directive.start] + replacement + protected[directive.end :]
        )
    return restore(rewritten)


def set_prompt_clan_tribe(prompt: str, tribe: str | None) -> str:
    """Add, replace, or remove ``tribe=`` on the prompt's clan directive."""
    protected, restore = protect_ignored_regions(prompt)
    alt_inner_regions = find_alt_inner_regions(protected)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        if is_inside_regions(match.start(), alt_inner_regions):
            continue
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "clan":
            continue

        end = match.end()
        parenthesized = match.group(2) is not None
        if parenthesized:
            paren_end = find_matching_paren_for_args(protected, match.end() - 1)
            if paren_end is None:
                raise ValueError(
                    "Cannot update clan tribe: malformed %clan(...) directive."
                )
            raw_args = protected[match.end() : paren_end]
            positional, named = parse_args(
                raw_args,
                reject_duplicate_named_args=True,
            )
            if len(positional) != 1 or not positional[0]:
                raise ValueError(
                    "Cannot update clan tribe: %clan requires exactly one clan name."
                )
            supported_keys = {"summary", "summary_script", "tribe"}
            unknown_keys = sorted(key for key in named if key not in supported_keys)
            if unknown_keys:
                keys = ", ".join(f"{key}=" for key in unknown_keys)
                raise ValueError(
                    f"Cannot update clan tribe: unsupported keyword on %clan: "
                    f"{keys}. Only summary=, summary_script=, and tribe= are "
                    "supported."
                )
            if "summary" in named and "summary_script" in named:
                raise ValueError(
                    "Cannot update clan tribe: %clan summary= and summary_script= "
                    "are mutually exclusive."
                )
            clan_name = positional[0]
            end = paren_end + 1
        else:
            colon_arg = match.group(3)
            if colon_arg is None:
                raise ValueError(
                    "Cannot update clan tribe: %clan requires a clan name."
                )
            clan_name = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )
            if not clan_name:
                raise ValueError(
                    "Cannot update clan tribe: %clan requires a clan name."
                )

        if parenthesized:
            edited_args = _edit_clan_tribe_arg(raw_args, tribe)
            replacement = f"%clan({edited_args})"
        elif tribe:
            replacement = f"%clan({clan_name}, tribe={tribe})"
        else:
            replacement = f"%clan:{clan_name}"
        rewritten = protected[: match.start()] + replacement + protected[end:]
        return restore(rewritten)

    raise ValueError(
        "Cannot update a clan tribe from this prompt; tribe membership belongs "
        "to the inherited clan and must be supplied by a clan member's "
        "%clan(<clan>, tribe=<tribe>) declaration."
    )


def _edit_clan_tribe_arg(raw_args: str, tribe: str | None) -> str:
    """Edit only the raw ``tribe=`` argument inside ``%clan(...)``."""
    spans = parse_arg_spans(raw_args)
    positional = next(span for span in spans if span.name is None)
    tribe_index = next(
        (index for index, span in enumerate(spans) if span.name == "tribe"),
        None,
    )

    if tribe:
        if tribe_index is not None:
            tribe_span = spans[tribe_index]
            assert tribe_span.value_start is not None
            assert tribe_span.value_end is not None
            return (
                raw_args[: tribe_span.value_start]
                + tribe
                + raw_args[tribe_span.value_end :]
            )

        if positional.separator is not None:
            insert_at = positional.separator + 1
            return raw_args[:insert_at] + f" tribe={tribe}," + raw_args[insert_at:]
        return (
            raw_args[: positional.end] + f", tribe={tribe}" + raw_args[positional.end :]
        )

    if tribe_index is None:
        return raw_args

    tribe_span = spans[tribe_index]
    if tribe_span.separator is not None:
        remove_start = tribe_span.segment_start
        remove_end = tribe_span.separator + 1
    else:
        previous_separator = (
            spans[tribe_index - 1].separator if tribe_index > 0 else None
        )
        remove_start = (
            previous_separator
            if previous_separator is not None
            else tribe_span.segment_start
        )
        remove_end = tribe_span.segment_end
    return raw_args[:remove_start] + raw_args[remove_end:]


def _prompt_has_effective_clan(prompt: str) -> bool:
    protected, _restore = protect_ignored_regions(prompt)
    alt_inner_regions = find_alt_inner_regions(protected)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        if is_inside_regions(match.start(), alt_inner_regions):
            continue
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name == "clan":
            return True
    return False


def prompt_declares_clan(prompt: str) -> bool:
    """Return whether *prompt* contains an effective top-level ``%clan``."""
    return _prompt_has_effective_clan(prompt)


def _format_id_directive(
    name: str | None,
    named: dict[str, str],
    *,
    directive_alias: Literal["id", "i"] = "id",
) -> str:
    if not named:
        return f"%{directive_alias}" if name is None else f"%{directive_alias}:{name}"
    parts = [] if name is None else [format_directive_arg(name)]
    parts.extend(f"{key}={format_directive_arg(value)}" for key, value in named.items())
    return f"%{directive_alias}({', '.join(parts)})"


def _find_prompt_id_directive(prompt: str) -> _PromptIdDirective | None:
    alt_inner_regions = find_alt_inner_regions(prompt)
    for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE):
        if is_inside_regions(match.start(), alt_inner_regions):
            continue
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "id":
            continue

        end = match.end()
        positional: list[str] = []
        named: dict[str, str] = {}
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
            if paren_end is None:
                raise ValueError("Cannot update malformed %id(...) directive.")
            positional, named = parse_args(
                prompt[match.end() : paren_end],
                reject_duplicate_named_args=True,
            )
            end = paren_end + 1
        elif match.group(3) is not None:
            raw_value = match.group(3)
            positional = [
                raw_value[1:-1]
                if raw_value.startswith("`") and raw_value.endswith("`")
                else raw_value
            ]
        return _PromptIdDirective(
            start=match.start(),
            end=end,
            positional=tuple(positional),
            named=named,
        )
    return None
