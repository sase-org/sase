"""Public prompt directive extraction implementation."""

from __future__ import annotations

import re
from collections.abc import Callable

from ._directive_collect import collect_prompt_directive_matches
from ._directive_shorthand import preprocess_directive_double_colon_shorthand
from ._directive_types import PromptDirectives
from ._directive_values import (
    expand_multi_directive_args,
    expand_single_directive_args,
    normalize_model_directive,
    parse_repeat_count,
    parse_tribe_name,
    resolve_clan_tribe,
    resolve_clan_summary,
    resolve_clan_summary_script,
    resolve_clan_membership,
    resolve_auto_argument,
    resolve_auto_mode,
    resolve_name_template,
    resolve_model_alias_overrides,
    resolve_reasoning_effort,
    resolve_wait_agent_args,
    resolve_wait_bead_args,
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
from ._parsing_args import process_text_block


def extract_prompt_directives(
    prompt: str,
    *,
    strip_disabled_markers: bool = True,
    process_references: Callable[[str], str],
) -> tuple[str, PromptDirectives]:
    """Extract ``%id`` directives from a prompt."""
    if "%" not in prompt:
        return prompt, PromptDirectives()

    prompt = preprocess_directive_double_colon_shorthand(prompt)

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

    name_explicit = collected.name_family_args is None and bool(
        collected.seen.get("id")
    )
    name_force_reuse = collected.name_force_reuse
    if name_explicit and collected.seen.get("id", "").startswith("!"):
        name_force_reuse = True
        collected.seen["id"] = collected.seen["id"][1:]

    if (
        collected.name_family_args is None
        and "id" in collected.seen
        and not collected.seen["id"]
    ):
        from sase.agent.names import get_next_auto_name

        collected.seen["id"] = get_next_auto_name()

    resolve_wait_agent_args(collected.seen_multi)
    wait_beads = resolve_wait_bead_args(collected.wait_bead_args)
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

    joined_clan: str | None = None
    if collected.name_clan_arg is not None:
        expanded_join = expand_single_directive_args(
            {"clan": collected.name_clan_arg},
            literal_directives=set(),
            model_had_alias_prefix=False,
            process_references=process_references,
        )
        joined_clan = resolve_clan_membership(expanded_join)
        assert joined_clan is not None
        expanded_args["id"] = f"{joined_clan}.{expanded_args['id']}"

    name_info = resolve_name_template(
        expanded_args.get("id"),
        force_reuse=name_force_reuse,
    )
    resolve_wait_templates(expanded_multi)

    repeat_count = parse_repeat_count(expanded_args)
    tribe = parse_tribe_name(expanded_args)
    declared_clan = resolve_clan_membership(expanded_args)
    clan = joined_clan or declared_clan
    clan_tribe = resolve_clan_tribe(
        collected.clan_tribe_arg,
        present=collected.clan_tribe_present,
        process_references=process_references,
    )
    clan_summary = resolve_clan_summary(
        collected.clan_summary_arg,
        present=collected.clan_summary_present,
    )
    clan_summary_script = resolve_clan_summary_script(
        collected.clan_summary_script_arg,
        present=collected.clan_summary_script_present,
    )
    if clan_summary is not None:
        clan_summary = unprotect_disabled_regions(clan_summary, disabled_regions)
        clan_summary = unprotect_fenced_blocks(clan_summary, fenced_blocks)
        if collected.clan_summary_text_block:
            clan_summary = process_text_block(f"[[{clan_summary}]]")
        else:
            clan_summary = clan_summary.strip()
    if clan_summary_script is not None:
        clan_summary_script = unprotect_disabled_regions(
            clan_summary_script,
            disabled_regions,
        )
        clan_summary_script = unprotect_fenced_blocks(
            clan_summary_script,
            fenced_blocks,
        ).strip()
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
        name=expanded_args.get("id") or None,
        name_explicit=name_explicit,
        name_force_reuse=name_force_reuse,
        clan=clan,
        clan_declared=declared_clan is not None,
        clan_tribe=clan_tribe,
        clan_summary=clan_summary,
        clan_summary_script=clan_summary_script,
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
        tribe=tribe,
        wait=expanded_multi.get("wait", []),
        wait_beads=wait_beads,
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
