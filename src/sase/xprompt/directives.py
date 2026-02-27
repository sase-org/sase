"""Prompt directive parsing (%name tag system).

Directives are in-prompt tags with a ``%`` prefix that modify runner behavior.
They are extracted and stripped from the prompt before further preprocessing.
Directive arguments use the same syntax as xprompts (colon, paren, backtick, plus).

Example::

    %model:#gemini_small_model
    Review this code...

The ``%model`` directive overrides the LLM model used for that prompt.
"""

import re
from dataclasses import dataclass, field

from ._exceptions import DirectiveError
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args, parse_args
from .processor import process_xprompt_references

# Pattern to match directive references: %name, %name(, %name:arg, %name:`arg`, %name+
# Mirrors _XPROMPT_PATTERN from processor.py but with % prefix.
# The colon-arg character class is expanded to include # (for xprompt refs in args).
_DIRECTIVE_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"%([a-zA-Z_][a-zA-Z0-9_]*)"  # Group 1: directive name
    r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_#/.-]*[a-zA-Z0-9_#/-])|(\+))?"  # Group 2: paren OR Group 3: colon arg OR Group 4: plus
)

# Known directive names
_KNOWN_DIRECTIVES = frozenset({"approve", "model", "name", "plan", "wait"})

# Directives that allow multiple occurrences (values are collected into a list)
_MULTI_VALUE_DIRECTIVES = frozenset({"wait"})

# Short aliases for directives (alias -> canonical name)
_DIRECTIVE_ALIASES: dict[str, str] = {
    "a": "approve",
    "m": "model",
    "n": "name",
    "p": "plan",
    "w": "wait",
}


@dataclass
class PromptDirectives:
    """Parsed prompt directives that modify runner behavior.

    Attributes:
        model: Model override string, or None to use the default.
        name: Agent name assigned via %name directive, or None.
        runner: Runner provider directive as (provider_name, ref, named_args),
            or None if no runner directive was found.
        wait: List of agent names to wait for via %wait directives.
    """

    approve: bool = False
    model: str | None = None
    name: str | None = None
    plan: bool = False
    runner: tuple[str, str, dict[str, str]] | None = None
    wait: list[str] = field(default_factory=list)


def extract_prompt_directives(
    prompt: str,
    *,
    runner_provider_names: frozenset[str] | None = None,
) -> tuple[str, PromptDirectives]:
    """Extract ``%name`` directives from a prompt.

    Finds all ``%name`` patterns in the prompt. Known directives are parsed,
    their xprompt references expanded, and they are stripped from the prompt.
    Unknown ``%name`` patterns are left in the prompt unchanged.

    When *runner_provider_names* is provided, directives whose name matches
    a runner provider are parsed as runner directives (at most one allowed).

    Args:
        prompt: The raw prompt text.
        runner_provider_names: Optional set of known runner provider names.
            Keeps this module as a pure parser with no import dependency on
            ``runner_provider.py``.

    Returns:
        Tuple of (cleaned_prompt, directives).

    Raises:
        DirectiveError: If a known directive appears more than once, or if
            multiple runner directives are found.
    """
    if "%" not in prompt:
        return prompt, PromptDirectives()

    # Protect fenced code blocks so directives inside them are ignored
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    matches = list(re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE))
    if not matches:
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

    # All names we recognize (built-in + runner providers)
    all_known = _KNOWN_DIRECTIVES | (runner_provider_names or frozenset())

    # Collect known directive matches (we'll strip these from the prompt)
    seen: dict[str, str] = {}  # directive name -> raw arg value (single-value)
    seen_multi: dict[
        str, list[str]
    ] = {}  # directive name -> raw arg values (multi-value)
    # Runner directive data: (provider_name, ref, named_args)
    runner_directive_data: tuple[str, str, dict[str, str]] | None = None
    # Regions to remove: list of (start, end) character positions
    regions_to_remove: list[tuple[int, int]] = []

    for match in matches:
        name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(name, name)  # resolve alias
        if name not in all_known:
            continue

        # --- Runner provider directive ---
        if runner_provider_names and name in runner_provider_names:
            if runner_directive_data is not None:
                raise DirectiveError(
                    f"Multiple runner directives found: '%{runner_directive_data[0]}'"
                    f" and '%{name}'"
                )

            # Extract ref (first positional arg) and named args
            has_open_paren = match.group(2) is not None
            colon_arg = match.group(3)
            match_end = match.end()
            runner_ref = ""
            runner_named_args: dict[str, str] = {}

            if has_open_paren:
                paren_start = match.end() - 1
                paren_end = find_matching_paren_for_args(prompt, paren_start)
                if paren_end is not None:
                    paren_content = prompt[paren_start + 1 : paren_end]
                    positional_args, runner_named_args = parse_args(paren_content)
                    runner_ref = positional_args[0] if positional_args else ""
                    match_end = paren_end + 1
            elif colon_arg is not None:
                if colon_arg.startswith("`") and colon_arg.endswith("`"):
                    runner_ref = colon_arg[1:-1]
                else:
                    runner_ref = colon_arg

            runner_directive_data = (name, runner_ref, runner_named_args)
            regions_to_remove.append((match.start(), match_end))
            continue

        # --- Built-in directive ---
        # Check for duplicates (multi-value directives are allowed to repeat)
        if name in _MULTI_VALUE_DIRECTIVES:
            pass  # handled below after arg extraction
        elif name in seen:
            raise DirectiveError(f"Duplicate directive '%{name}' in prompt")

        # Extract argument value
        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(prompt, paren_start)
            if paren_end is not None:
                paren_content = prompt[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(paren_content)
                raw_arg = positional_args[0] if positional_args else ""
                match_end = paren_end + 1
            else:
                raw_arg = ""
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_arg = colon_arg[1:-1]
            else:
                raw_arg = colon_arg
        elif plus_suffix is not None:
            raw_arg = "true"
        else:
            raw_arg = ""

        if name in _MULTI_VALUE_DIRECTIVES:
            seen_multi.setdefault(name, []).append(raw_arg)
        else:
            seen[name] = raw_arg
        regions_to_remove.append((match.start(), match_end))

    if not regions_to_remove:
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()

    # Remove directive regions from prompt (last-to-first to preserve positions)
    cleaned = prompt
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]

    # Strip the line if the directive was the only content on it
    # (remove leftover blank lines from directive removal)
    cleaned = re.sub(r"^\s*\n", "", cleaned)

    # Expand xprompt references in directive argument values
    expanded_args: dict[str, str] = {}
    for directive_name, raw_arg in seen.items():
        if raw_arg and "#" in raw_arg:
            expanded_args[directive_name] = process_xprompt_references(raw_arg).strip()
        else:
            expanded_args[directive_name] = raw_arg

    # Expand xprompt references in multi-value directive arguments
    expanded_multi: dict[str, list[str]] = {}
    for directive_name, raw_args in seen_multi.items():
        expanded_list: list[str] = []
        for raw_arg in raw_args:
            if raw_arg and "#" in raw_arg:
                expanded_list.append(process_xprompt_references(raw_arg).strip())
            else:
                expanded_list.append(raw_arg)
        expanded_multi[directive_name] = expanded_list

    # Expand xprompt references in runner ref if it contains #
    if runner_directive_data is not None:
        rp_name, rp_ref, rp_named = runner_directive_data
        if rp_ref and "#" in rp_ref:
            rp_ref = process_xprompt_references(rp_ref).strip()
        runner_directive_data = (rp_name, rp_ref, rp_named)

    # Build PromptDirectives from expanded args
    directives = PromptDirectives(
        approve="approve" in expanded_args,
        model=expanded_args.get("model") or None,
        name=expanded_args.get("name") or None,
        plan="plan" in expanded_args,
        runner=runner_directive_data,
        wait=expanded_multi.get("wait", []),
    )

    # Restore fenced code blocks before returning
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    return cleaned, directives
