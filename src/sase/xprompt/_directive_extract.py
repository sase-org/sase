"""Public prompt directive extraction implementation."""

from __future__ import annotations

import re
from collections.abc import Callable

from ._directive_collect import collect_prompt_directive_matches
from ._exceptions import DirectiveError
from ._directive_types import PromptDirectives
from ._directive_values import (
    expand_multi_directive_args,
    expand_single_directive_args,
    normalize_model_directive,
    parse_group_tag,
    parse_repeat_count,
    resolve_auto_argument,
    resolve_family_membership,
    resolve_auto_mode,
    resolve_name_template,
    resolve_model_alias_overrides,
    resolve_reasoning_effort,
    resolve_wait_agent_args,
    resolve_wait_templates,
    resolve_wait_runners_args,
    resolve_wait_time_args,
)
from ._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks


def extract_prompt_directives(
    prompt: str,
    *,
    strip_disabled_markers: bool = True,
    process_references: Callable[[str], str],
) -> tuple[str, PromptDirectives]:
    """Extract ``%name`` directives from a prompt."""
    if "%" not in prompt:
        return prompt, PromptDirectives()

    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    collected = collect_prompt_directive_matches(prompt)
    if not collected.regions_to_remove:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        if strip_disabled_markers:
            prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

    if "family" in collected.seen and collected.name_family_args is not None:
        raise DirectiveError(
            "Cannot combine %family with %n(parent, suffix); choose parallel "
            "family membership or serial family attachment."
        )

    name_explicit = collected.name_family_args is None and bool(
        collected.seen.get("name")
    )
    name_force_reuse = False
    if name_explicit and collected.seen.get("name", "").startswith("!"):
        name_force_reuse = True
        collected.seen["name"] = collected.seen["name"][1:]

    if (
        collected.name_family_args is None
        and "name" in collected.seen
        and not collected.seen["name"]
    ):
        from sase.agent.names import get_next_auto_name

        collected.seen["name"] = get_next_auto_name()

    resolve_wait_agent_args(collected.seen_multi)
    wait_duration, wait_until = resolve_wait_time_args(collected.wait_time_args)
    wait_runners = resolve_wait_runners_args(collected.wait_runners_args)

    cleaned = _remove_directive_regions(prompt, collected.regions_to_remove)

    model_effort, model_had_alias_prefix = normalize_model_directive(
        collected.seen,
        collected.literal_directives,
    )
    expanded_args = expand_single_directive_args(
        collected.seen,
        literal_directives=collected.literal_directives,
        model_had_alias_prefix=model_had_alias_prefix,
        process_references=process_references,
    )
    expanded_multi = expand_multi_directive_args(
        collected.seen_multi,
        process_references=process_references,
    )

    name_info = resolve_name_template(
        expanded_args.get("name"),
        force_reuse=name_force_reuse,
    )
    resolve_wait_templates(expanded_multi)

    repeat_count = parse_repeat_count(expanded_args)
    parsed_tag = parse_group_tag(expanded_args)
    family_target, family_role = resolve_family_membership(
        expanded_args,
        raw_role=collected.family_role,
    )
    reasoning_effort = resolve_reasoning_effort(
        effort_directive=expanded_args.get("effort"),
        effort_present="effort" in expanded_args,
        model_effort=model_effort,
    )
    auto_mode = resolve_auto_mode(expanded_args)
    auto_enabled, auto_argument = resolve_auto_argument(expanded_args)
    model_alias_overrides = resolve_model_alias_overrides(
        collected.model_alias_overrides,
        process_references=process_references,
    )

    directives = PromptDirectives(
        auto_mode=auto_mode,
        auto_enabled=auto_enabled,
        auto_argument=auto_argument,
        hide="hide" in expanded_args,
        model=expanded_args.get("model") or None,
        model_alias_overrides=model_alias_overrides,
        reasoning_effort=reasoning_effort,
        name=expanded_args.get("name") or None,
        name_explicit=name_explicit,
        name_force_reuse=name_force_reuse,
        family_target=family_target,
        family_role=family_role,
        family_attach_parent=(
            collected.name_family_args[0]
            if collected.name_family_args is not None
            else None
        ),
        family_attach_suffix=(
            collected.name_family_args[1]
            if collected.name_family_args is not None
            else None
        ),
        name_template=name_info.name_template,
        name_template_base=name_info.name_template_base,
        name_indexed_template=name_info.name_indexed_template,
        name_indexed_base=name_info.name_indexed_base,
        repeat_count=repeat_count,
        tag=parsed_tag,
        wait=expanded_multi.get("wait", []),
        wait_duration=wait_duration,
        wait_until=wait_until,
        wait_runners=wait_runners,
    )

    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    if strip_disabled_markers:
        cleaned = strip_disabled_region_markers(cleaned)
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    return cleaned, directives


def _remove_directive_regions(
    prompt: str, regions_to_remove: list[tuple[int, int]]
) -> str:
    cleaned = prompt
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]
    return re.sub(r"^\s*\n", "", cleaned)
