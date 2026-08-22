"""Public prompt directive extraction implementation."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.xprompt.code_value import CodeDirectiveScan, CodeValue

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
    resolve_launch_bead_id,
    resolve_auto_argument,
    resolve_auto_mode,
    resolve_name_template,
    resolve_model_alias_overrides,
    resolve_reasoning_effort,
    resolve_wait_agent_args,
    resolve_wait_bead_args,
    resolve_wait_identifier_args,
    resolve_wait_priority_args,
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
    original_prompt = prompt
    if "%" not in prompt:
        return prompt, PromptDirectives()

    from sase.xprompt.code_value import (
        raise_if_code_directive_scan_failed,
        reject_disabled_code_directives,
        scan_directive_owned_fences,
        strip_owned_code_spans,
        typed_launch_units_enabled,
    )

    owned_scan = scan_directive_owned_fences(prompt)
    reject_disabled_code_directives(prompt, scan=owned_scan)
    if typed_launch_units_enabled():
        raise_if_code_directive_scan_failed(owned_scan)
        prompt = strip_owned_code_spans(prompt, owned_scan)

    prompt = preprocess_directive_double_colon_shorthand(prompt)

    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    collected = collect_prompt_directive_matches(prompt)
    if_code, proc_code, proc_options = _owned_code_values(
        original_prompt, owned_scan, collected
    )
    if not collected.regions_to_remove and if_code is None and proc_code is None:
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
    wait_units = resolve_wait_identifier_args(
        "unit", [process_references(arg) for arg in collected.wait_unit_args]
    )
    wait_procs = resolve_wait_identifier_args(
        "proc", [process_references(arg) for arg in collected.wait_proc_args]
    )
    wait_beads = resolve_wait_bead_args(collected.wait_bead_args)
    wait_duration, wait_until = resolve_wait_time_args(collected.wait_time_args)
    wait_runners = resolve_wait_runners_args(collected.wait_runners_args)
    wait_priority = resolve_wait_priority_args(collected.wait_priority_args)

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
        model_alias=(
            (expanded_args.get("model") or None) if model_had_alias_prefix else None
        ),
        model_alias_overrides=model_alias_overrides,
        reasoning_effort=reasoning_effort,
        name=expanded_args.get("id") or None,
        bead_id=resolve_launch_bead_id(expanded_args),
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
        wait_units=wait_units,
        wait_procs=wait_procs,
        wait_beads=wait_beads,
        wait_duration=wait_duration,
        wait_until=wait_until,
        wait_runners=wait_runners,
        wait_priority=wait_priority,
        final=expanded_multi.get("final", []),
        if_code=if_code,
        proc_code=proc_code,
        proc_options=proc_options,
    )

    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    if strip_disabled_markers:
        cleaned = strip_disabled_region_markers(cleaned)
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    return cleaned, directives


def _owned_code_values(
    prompt: str,
    owned_scan: CodeDirectiveScan,
    collected: object,
) -> tuple[CodeValue | None, CodeValue | None, dict[str, str]]:
    from sase.xprompt._exceptions import DirectiveError

    if_spans = [item for item in owned_scan.directives if item.name == "if"]
    proc_spans = [item for item in owned_scan.directives if item.name == "proc"]
    if len(if_spans) > 1:
        raise DirectiveError("Only one %if is allowed per launch unit.")
    collected_proc = getattr(collected, "proc_code", None)
    if len(proc_spans) > 1 or (proc_spans and collected_proc is not None):
        raise DirectiveError("Only one %proc is allowed per launch unit.")
    if_code = if_spans[0].code if if_spans else None
    proc_code = proc_spans[0].code if proc_spans else collected_proc
    proc_options = dict(getattr(collected, "proc_options", {}))
    if proc_spans:
        proc_options.update(_owned_proc_options(prompt, proc_spans[0].span))
    return if_code, proc_code, proc_options


def _owned_proc_options(prompt: str, span: tuple[int, int]) -> dict[str, str]:
    from sase.xprompt._exceptions import DirectiveError

    from ._parsing import find_matching_paren_for_args, parse_args

    start, end = span
    header_end = prompt.find("::", start, end)
    if header_end < 0:
        return {}
    header = prompt[start:header_end].strip()
    if not header.startswith("%proc("):
        return {}
    paren_start = prompt.find("(", start, header_end)
    paren_end = find_matching_paren_for_args(prompt, paren_start)
    if paren_start < 0 or paren_end is None or paren_end > header_end:
        return {}
    try:
        positional_args, named_args = parse_args(
            prompt[paren_start + 1 : paren_end],
            reject_duplicate_named_args=True,
        )
    except ValueError as exc:
        raise DirectiveError(str(exc)) from exc
    supported_keys = {"timeout", "idle_timeout", "cwd", "workspace", "label"}
    body_keys = {"bash", "python"}
    unknown = sorted(key for key in named_args if key not in supported_keys | body_keys)
    if unknown:
        keys = ", ".join(f"{key}=" for key in unknown)
        raise DirectiveError(
            f"Unsupported keyword on %proc: {keys}. Only bash=, python=, "
            "timeout=, idle_timeout=, cwd=, workspace=, and label= are supported."
        )
    if any(arg for arg in positional_args) or body_keys & named_args.keys():
        raise DirectiveError(
            "%proc cannot combine a parenthesized body with a fenced body."
        )
    return {key: value for key, value in named_args.items() if key in supported_keys}


def _remove_directive_regions(
    prompt: str, regions_to_remove: list[tuple[int, int]]
) -> str:
    cleaned = prompt
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]
    return re.sub(r"^\s*\n", "", cleaned)
