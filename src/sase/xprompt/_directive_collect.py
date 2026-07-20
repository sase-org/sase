"""Raw directive match collection for prompt directive extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._directive_alt import _ALT_DIRECTIVE_RE, multi_model_unsupported_message
from ._directive_types import (
    _DEPRECATED_DIRECTIVE_MESSAGES,
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
    _MULTI_VALUE_DIRECTIVES,
)
from ._exceptions import DirectiveError
from ._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_args,
)


@dataclass
class _CollectedDirectives:
    """Raw directive values and source spans collected from a protected prompt."""

    seen: dict[str, str] = field(default_factory=dict)
    seen_source: dict[str, str] = field(default_factory=dict)
    seen_multi: dict[str, list[str]] = field(default_factory=dict)
    wait_bead_args: list[str] = field(default_factory=list)
    wait_time_args: list[str] = field(default_factory=list)
    wait_runners_args: list[str] = field(default_factory=list)
    model_alias_overrides: dict[str, str] = field(default_factory=dict)
    clan_tribe_arg: str | None = None
    clan_tribe_present: bool = False
    clan_summary_arg: str | None = None
    clan_summary_present: bool = False
    clan_summary_text_block: bool = False
    clan_summary_script_arg: str | None = None
    clan_summary_script_present: bool = False
    name_clan_arg: str | None = None
    name_force_reuse: bool = False
    name_family_args: tuple[str, str] | None = None
    literal_directives: set[str] = field(default_factory=set)
    regions_to_remove: list[tuple[int, int]] = field(default_factory=list)


def collect_prompt_directive_matches(prompt: str) -> _CollectedDirectives:
    """Collect known directive matches from a fenced/disabled protected prompt."""
    collected = _CollectedDirectives()
    for match in _directive_matches_outside_alt(prompt):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name in _DEPRECATED_DIRECTIVES:
            raise DirectiveError(_DEPRECATED_DIRECTIVE_MESSAGES[name])
        if name not in _KNOWN_DIRECTIVES:
            continue

        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()
        is_multi = name in _MULTI_VALUE_DIRECTIVES
        raw_args: list[str] = []

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(prompt, paren_start)
            if paren_end is not None:
                paren_content = prompt[paren_start + 1 : paren_end]
                try:
                    positional_args, named_args = parse_args(
                        paren_content,
                        reject_duplicate_named_args=name
                        in {"clan", "id", "model", "wait"},
                    )
                except ValueError as exc:
                    raise DirectiveError(str(exc)) from exc
                if name == "clan":
                    raw_args = _collect_clan_paren_args(
                        collected,
                        positional_args,
                        named_args,
                        paren_content=paren_content,
                    )
                if name == "id":
                    (
                        raw_args,
                        handled,
                    ) = _collect_name_paren_args(
                        collected,
                        prompt,
                        match,
                        paren_end,
                        positional_args,
                        named_args,
                    )
                    if handled:
                        continue
                    positional_args = raw_args
                if name == "wait":
                    supported_keys = {"bead", "runners", "time"}
                    unknown_keys = sorted(
                        key for key in named_args if key not in supported_keys
                    )
                    if unknown_keys:
                        keys = ", ".join(f"{key}=" for key in unknown_keys)
                        raise DirectiveError(
                            f"Unsupported keyword on %wait: {keys}. "
                            "Only bead=, runners=, and time= are supported."
                        )
                    if "bead" in named_args:
                        collected.wait_bead_args.append(named_args["bead"])
                    if "time" in named_args:
                        collected.wait_time_args.append(named_args["time"])
                    if "runners" in named_args:
                        collected.wait_runners_args.append(named_args["runners"])
                if name == "model":
                    collected.model_alias_overrides = dict(named_args)
                if name == "clan":
                    pass
                elif is_multi:
                    raw_args = list(positional_args)
                elif (
                    name == "model" and len([arg for arg in positional_args if arg]) > 1
                ):
                    source = prompt[match.start() : paren_end + 1]
                    models = [arg for arg in positional_args if arg]
                    raise DirectiveError(
                        multi_model_unsupported_message(source, models)
                    )
                else:
                    raw_args = [positional_args[0] if positional_args else ""]
                match_end = paren_end + 1
            else:
                if name == "clan":
                    raise DirectiveError(
                        "Malformed %clan(...) directive: missing closing ')'."
                    )
                raw_args = [""]
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_args = [colon_arg[1:-1]]
                collected.literal_directives.add(name)
            elif is_multi:
                raw_args = [seg for seg in colon_arg.split(",") if seg]
            else:
                raw_args = [colon_arg]
            if name == "model" and "=" in raw_args[0]:
                raise DirectiveError(
                    "Model alias overrides require the parenthesized form — "
                    "use %model(alias=model), not %model:alias=model."
                )
        elif plus_suffix is not None:
            if name == "clan":
                raise DirectiveError(
                    "%clan does not support '+'; use %clan:<name> or "
                    "%clan(<name>, tribe=<tribe>)."
                )
            raw_args = ["true"]
        else:
            raw_args = [""]

        if is_multi:
            collected.seen_multi.setdefault(name, []).extend(raw_args)
        else:
            _store_single_directive(collected, prompt, match, match_end, name, raw_args)
        collected.regions_to_remove.append((match.start(), match_end))

    _validate_clan_directive_contract(collected)
    return collected


def _collect_clan_paren_args(
    collected: _CollectedDirectives,
    positional_args: list[str],
    named_args: dict[str, str],
    *,
    paren_content: str,
) -> list[str]:
    """Validate and retain the canonical ``%clan(...)`` argument shape."""
    supported_keys = {"summary", "summary_script", "tribe"}
    unknown_keys = sorted(key for key in named_args if key not in supported_keys)
    if unknown_keys:
        keys = ", ".join(f"{key}=" for key in unknown_keys)
        raise DirectiveError(
            f"Unsupported keyword on %clan: {keys}. Only summary=, "
            "summary_script=, and tribe= are supported."
        )
    if len(positional_args) > 1:
        raise DirectiveError("%clan accepts exactly one positional clan name argument.")
    if "summary" in named_args and "summary_script" in named_args:
        raise DirectiveError(
            "'%clan' summary= and summary_script= are mutually exclusive."
        )
    if "tribe" in named_args:
        collected.clan_tribe_present = True
        collected.clan_tribe_arg = named_args["tribe"]
    if "summary" in named_args:
        collected.clan_summary_present = True
        collected.clan_summary_arg = named_args["summary"]
        collected.clan_summary_text_block = _named_arg_is_text_block(
            paren_content,
            "summary",
        )
    if "summary_script" in named_args:
        collected.clan_summary_script_present = True
        collected.clan_summary_script_arg = named_args["summary_script"]
    return [positional_args[0] if positional_args else ""]


def _named_arg_is_text_block(paren_content: str, name: str) -> bool:
    return (
        re.search(
            rf"(?:^|,)\s*{re.escape(name)}\s*=\s*\[\[",
            paren_content,
        )
        is not None
    )


def _validate_clan_directive_contract(collected: _CollectedDirectives) -> None:
    """Reject directive combinations that would create two clan axes."""
    if collected.name_clan_arg is not None and "clan" in collected.seen:
        raise DirectiveError(
            "Cannot combine %clan with %id(..., clan=...); a declaring prompt "
            "uses %clan(<clan>, tribe=<tribe>) with a full %id:<clan>.<id>, "
            "while a joining prompt uses only %id(<id>, clan=<clan>)."
        )
    if "clan" in collected.seen and "tribe" in collected.seen:
        raise DirectiveError(
            "Cannot combine %clan with %id(..., tribe=...); use "
            "%clan(<clan>, tribe=<tribe>) to set the clan's tribe."
        )
    if "clan" in collected.seen and collected.name_family_args is not None:
        raise DirectiveError(
            "Cannot combine %clan with %id(..., family=...); choose clan "
            "membership or serial family attachment."
        )


def _directive_matches_outside_alt(prompt: str) -> list[re.Match[str]]:
    alt_inner_regions = _alt_inner_regions(prompt)

    def is_inside_alt(pos: int) -> bool:
        return any(start <= pos < end for start, end in alt_inner_regions)

    return [
        match
        for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE)
        if not is_inside_alt(match.start())
    ]


def _alt_inner_regions(prompt: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(prompt):
        open_pos = alt_match.end() - 1
        if prompt[open_pos] == "{":
            close_pos = find_matching_brace_for_args(prompt, open_pos)
        else:
            close_pos = find_matching_paren_for_args(prompt, open_pos)
        if close_pos is not None:
            regions.append((open_pos + 1, close_pos))
    return regions


def _collect_name_paren_args(
    collected: _CollectedDirectives,
    prompt: str,
    match: re.Match[str],
    paren_end: int,
    positional_args: list[str],
    named_args: dict[str, str],
) -> tuple[list[str], bool]:
    from sase.agent.family_attach import parse_name_directive_args

    try:
        parsed_name = parse_name_directive_args(
            positional_args,
            named_args,
            source=f"%{match.group(1)}",
        )
    except ValueError as exc:
        raise DirectiveError(str(exc)) from exc
    if parsed_name.clan is not None:
        collected.name_clan_arg = parsed_name.clan
    if parsed_name.tribe is not None:
        collected.seen["tribe"] = parsed_name.tribe
    if parsed_name.force_reuse:
        collected.name_force_reuse = True
    if parsed_name.family_parent is not None and parsed_name.family_suffix is not None:
        collected.name_family_args = (
            parsed_name.family_parent,
            parsed_name.family_suffix,
        )
        match_end = paren_end + 1
        if "id" in collected.seen:
            raise DirectiveError(_duplicate_id_message())
        collected.seen["id"] = ""
        collected.seen_source["id"] = prompt[match.start() : match_end]
        collected.regions_to_remove.append((match.start(), match_end))
        return [""], True
    return (
        [parsed_name.plain_name] if parsed_name.plain_name is not None else [],
        False,
    )


def _store_single_directive(
    collected: _CollectedDirectives,
    prompt: str,
    match: re.Match[str],
    match_end: int,
    name: str,
    raw_args: list[str],
) -> None:
    if name in collected.seen:
        if name == "model":
            models = [arg for arg in [collected.seen[name], raw_args[0]] if arg]
            if models:
                source = (
                    f"{collected.seen_source[name]} ... "
                    f"{prompt[match.start() : match_end]}"
                )
                raise DirectiveError(multi_model_unsupported_message(source, models))
        if name == "id":
            raise DirectiveError(_duplicate_id_message())
        raise DirectiveError(f"Duplicate directive '%{name}' in prompt")
    collected.seen[name] = raw_args[0]
    collected.seen_source[name] = prompt[match.start() : match_end]


def _duplicate_id_message() -> str:
    return (
        "Duplicate directive '%id' in prompt; use "
        "%id(<id>, tribe=<tribe>) to assign a tribe to an explicitly named "
        "agent."
    )
