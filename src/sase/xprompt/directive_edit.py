"""Pure text helpers for rewriting launch-property xprompt directives."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
)
from ._disabled_regions import protect_disabled_regions, unprotect_disabled_regions
from ._directive_shorthand import find_directive_double_colon_text_end
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_arg_spans,
    parse_args,
)

AutoMode = Literal["plan", "tale", "epic"]


@dataclass(frozen=True)
class PromptWaitDirective:
    """Canonical wait directive payload used by prompt rewrite callers."""

    agents: tuple[str, ...] = ()
    time_token: str | None = None
    runners: int | None = None
    beads: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(
            self.agents or self.time_token or self.runners is not None or self.beads
        )


@dataclass(frozen=True)
class _PromptIdDirective:
    start: int
    end: int
    positional: tuple[str, ...]
    named: dict[str, str]


_TIME_XPROMPT_RE = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#t(?:(\()|:(`[^`]*`|\$\([^)]*\)|[a-zA-Z0-9_.~,+/-]*[a-zA-Z0-9_~+/-]))"
)


def set_prompt_name(
    prompt: str,
    name: str,
    *,
    directive_alias: Literal["id", "i"] = "id",
    preserve_kwargs: bool = True,
    drop_kwargs: frozenset[str] = frozenset(),
) -> str:
    """Return *prompt* with a canonical ``%id`` and optional existing kwargs."""
    protected, restore = _protect_ignored_regions(prompt)
    directive = _find_prompt_id_directive(protected)
    if directive is None:
        return restore(_insert_directive(protected, f"%{directive_alias}:{name}"))
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
        _format_wait_arg(member_id),
        f"clan={_format_wait_arg(clan_name)}",
    ]
    if directives.bead_id:
        replacement_parts.append(f"bead={_format_wait_arg(directives.bead_id)}")
    replacement = f"%id({', '.join(replacement_parts)})"
    rewritten = (
        _set_prompt_directive(prompt, {"clan"}, None)
        if directives.clan_declared
        else prompt
    )
    return _set_prompt_directive(rewritten, {"id"}, replacement)


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
        _format_wait_arg(member_id),
        f"family={_format_wait_arg(family_name)}",
    ]
    if effective_bead:
        replacement_parts.append(f"bead={_format_wait_arg(effective_bead)}")
    replacement = f"%id({', '.join(replacement_parts)})"

    rewritten = prompt
    if directives.clan_declared:
        rewritten = _set_prompt_directive(rewritten, {"clan"}, None)
    return _set_prompt_directive(rewritten, {"id"}, replacement)


def set_prompt_tribe(prompt: str, tribe: str | None) -> str:
    """Add, replace, or remove the ``tribe=`` keyword on ``%id``."""
    if _prompt_has_effective_clan(prompt):
        rewritten = set_prompt_clan_tribe(prompt, tribe)
        return _set_prompt_directive(rewritten, {"g", "group", "tribe"}, None)

    # Editing an existing agent also migrates launch prompts written before
    # tribes replaced groups. These spellings remain unsupported by the
    # runtime parser; recognizing them here is cleanup, not a legacy alias.
    protected, restore = _protect_ignored_regions(prompt)
    protected = _rewrite_protected_prompt(
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
        return restore(_insert_directive(protected, f"%id(tribe={tribe})"))

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
        rewritten = _remove_spans(
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
    protected, restore = _protect_ignored_regions(prompt)
    alt_inner_regions = _alt_inner_regions(protected)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        if _inside_regions(match.start(), alt_inner_regions):
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
    protected, _restore = _protect_ignored_regions(prompt)
    alt_inner_regions = _alt_inner_regions(protected)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        if _inside_regions(match.start(), alt_inner_regions):
            continue
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name == "clan":
            return True
    return False


def prompt_declares_clan(prompt: str) -> bool:
    """Return whether *prompt* contains an effective top-level ``%clan``."""
    return _prompt_has_effective_clan(prompt)


def set_prompt_auto_mode(prompt: str, mode: AutoMode | None) -> str:
    """Return *prompt* with the requested canonical ``%auto`` directive."""
    replacement = None
    if mode == "plan":
        replacement = "%auto"
    elif mode is not None:
        replacement = f"%auto:{mode}"
    return _set_prompt_directive(prompt, {"auto"}, replacement)


def set_prompt_wait(
    prompt: str,
    wait_spec: PromptWaitDirective | None,
) -> str:
    """Return *prompt* with a canonical ``%wait(...)`` directive or none."""
    replacement = _format_wait_directive(wait_spec) if wait_spec else None
    return _set_prompt_directive(
        prompt,
        {"wait"},
        replacement,
        remove_deprecated=True,
        remove_time_xprompts=True,
    )


def _format_wait_directive(wait_spec: PromptWaitDirective | None) -> str | None:
    if not wait_spec:
        return None
    parts = [_format_wait_arg(agent) for agent in wait_spec.agents]
    if wait_spec.time_token:
        parts.append(f"time={wait_spec.time_token}")
    if wait_spec.runners is not None:
        parts.append(f"runners={wait_spec.runners}")
    directives = [f"%wait({', '.join(parts)})"] if parts else []
    directives.extend(
        f"%wait(bead={_format_wait_arg(bead)})" for bead in wait_spec.beads
    )
    return "\n".join(directives)


def _format_wait_arg(value: str) -> str:
    if value and not any(ch.isspace() or ch in ",()=" for ch in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_id_directive(
    name: str | None,
    named: dict[str, str],
    *,
    directive_alias: Literal["id", "i"] = "id",
) -> str:
    if not named:
        return f"%{directive_alias}" if name is None else f"%{directive_alias}:{name}"
    parts = [] if name is None else [_format_wait_arg(name)]
    parts.extend(f"{key}={_format_wait_arg(value)}" for key, value in named.items())
    return f"%{directive_alias}({', '.join(parts)})"


def _find_prompt_id_directive(prompt: str) -> _PromptIdDirective | None:
    alt_inner_regions = _alt_inner_regions(prompt)
    for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE):
        if _inside_regions(match.start(), alt_inner_regions):
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


def _set_prompt_directive(
    prompt: str,
    directive_names: set[str],
    replacement: str | None,
    *,
    remove_deprecated: bool = False,
    remove_time_xprompts: bool = False,
) -> str:
    protected, restore = _protect_ignored_regions(prompt)
    protected = _rewrite_protected_prompt(
        protected,
        directive_names,
        replacement,
        remove_deprecated=remove_deprecated,
        remove_time_xprompts=remove_time_xprompts,
    )
    return restore(protected)


def _protect_ignored_regions(prompt: str) -> tuple[str, Callable[[str], str]]:
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    def restore(text: str) -> str:
        text = unprotect_disabled_regions(text, disabled_regions)
        return unprotect_fenced_blocks(text, fenced_blocks)

    return protected, restore


def _rewrite_protected_prompt(
    prompt: str,
    directive_names: set[str],
    replacement: str | None,
    *,
    remove_deprecated: bool,
    remove_time_xprompts: bool,
) -> str:
    spans = list(
        _directive_spans(
            prompt,
            directive_names,
            remove_deprecated=remove_deprecated,
            remove_clan_shorthand=replacement is None,
        )
    )
    if remove_time_xprompts:
        spans.extend(_time_xprompt_spans(prompt))
    spans = _merge_spans(spans)

    cleaned = _remove_spans(prompt, spans) if spans else prompt
    if replacement is None:
        return cleaned
    return _insert_directive(cleaned, replacement)


def _directive_spans(
    prompt: str,
    directive_names: set[str],
    *,
    remove_deprecated: bool,
    remove_clan_shorthand: bool,
) -> Iterable[tuple[int, int]]:
    alt_inner_regions = _alt_inner_regions(prompt)
    for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE):
        if _inside_regions(match.start(), alt_inner_regions):
            continue
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in directive_names and not (
            remove_deprecated and name in _DEPRECATED_DIRECTIVES
        ):
            continue
        match_end = match.end()
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        if (
            remove_clan_shorthand
            and name == "clan"
            and prompt.startswith(":: ", match_end)
        ):
            shorthand_end = find_directive_double_colon_text_end(
                prompt,
                match_end + 3,
                ignored_ranges=alt_inner_regions,
            )
            line_start = prompt.rfind("\n", 0, match.start()) + 1
            if (
                shorthand_end < len(prompt)
                and prompt[shorthand_end] == "\n"
                and not prompt[line_start : match.start()].strip()
            ):
                shorthand_end += 1
            match_end = shorthand_end
        yield match.start(), match_end


def _time_xprompt_spans(prompt: str) -> Iterable[tuple[int, int]]:
    alt_inner_regions = _alt_inner_regions(prompt)
    for match in _TIME_XPROMPT_RE.finditer(prompt):
        if _inside_regions(match.start(), alt_inner_regions):
            continue
        match_end = match.end()
        if match.group(1) is not None:
            paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        yield match.start(), match_end


def _alt_inner_regions(prompt: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(prompt):
        open_pos = alt_match.end() - 1
        if prompt[open_pos] == "{":
            close_pos = find_matching_brace_for_args(prompt, open_pos)
        else:
            close_pos = find_matching_paren_for_args(prompt, open_pos)
        if close_pos is None:
            continue
        regions.append((open_pos + 1, close_pos))
    return regions


def _inside_regions(pos: int, regions: Iterable[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in regions)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    removal_ranges = _line_or_span_removal_ranges(text, spans)
    parts: list[str] = []
    cursor = 0
    for start, end in removal_ranges:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _line_or_span_removal_ranges(
    text: str,
    spans: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    line_start = 0
    span_index = 0
    while line_start < len(text):
        newline_index = text.find("\n", line_start)
        line_end = len(text) if newline_index == -1 else newline_index + 1
        line_spans: list[tuple[int, int]] = []
        while span_index < len(spans) and spans[span_index][1] <= line_start:
            span_index += 1
        lookahead = span_index
        while lookahead < len(spans) and spans[lookahead][0] < line_end:
            start, end = spans[lookahead]
            line_spans.append((max(start, line_start), min(end, line_end)))
            lookahead += 1
        if not line_spans:
            line_start = line_end
            continue
        if _line_without_spans(text, line_start, line_end, line_spans).strip() == "":
            ranges.append((line_start, line_end))
        else:
            ranges.extend(
                _expand_inline_removal_span(text, line_end, start, end)
                for start, end in line_spans
            )
        line_start = line_end
    if line_start == len(text):
        return _merge_spans(ranges)
    return _merge_spans(ranges)


def _expand_inline_removal_span(
    text: str,
    line_end: int,
    start: int,
    end: int,
) -> tuple[int, int]:
    """Include separator whitespace after removed inline directives."""
    content_end = (
        line_end - 1 if line_end > 0 and text[line_end - 1] == "\n" else line_end
    )
    while end < content_end and text[end] in " \t":
        end += 1
    return start, end


def _line_without_spans(
    text: str,
    line_start: int,
    line_end: int,
    line_spans: list[tuple[int, int]],
) -> str:
    parts: list[str] = []
    cursor = line_start
    for start, end in line_spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:line_end])
    return "".join(parts)


def _insert_directive(prompt: str, directive: str) -> str:
    insert_at = _frontmatter_end(prompt)
    prefix = prompt[:insert_at]
    suffix = prompt[insert_at:]
    return f"{prefix}{directive}\n{suffix}"


def _frontmatter_end(prompt: str) -> int:
    if not prompt.startswith("---\n"):
        return 0
    cursor = 4
    while cursor < len(prompt):
        next_newline = prompt.find("\n", cursor)
        line_end = len(prompt) if next_newline == -1 else next_newline + 1
        line = prompt[cursor:line_end].strip()
        if line == "---":
            return line_end
        cursor = line_end
    return 0
