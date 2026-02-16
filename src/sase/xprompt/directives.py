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
from dataclasses import dataclass

from ._exceptions import DirectiveError
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
_KNOWN_DIRECTIVES = frozenset({"model"})


@dataclass
class PromptDirectives:
    """Parsed prompt directives that modify runner behavior.

    Attributes:
        model: Model override string, or None to use the default.
    """

    model: str | None = None


def extract_prompt_directives(prompt: str) -> tuple[str, PromptDirectives]:
    """Extract ``%name`` directives from a prompt.

    Finds all ``%name`` patterns in the prompt. Known directives are parsed,
    their xprompt references expanded, and they are stripped from the prompt.
    Unknown ``%name`` patterns are left in the prompt unchanged.

    Args:
        prompt: The raw prompt text.

    Returns:
        Tuple of (cleaned_prompt, directives).

    Raises:
        DirectiveError: If a known directive appears more than once.
    """
    if "%" not in prompt:
        return prompt, PromptDirectives()

    matches = list(re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE))
    if not matches:
        return prompt, PromptDirectives()

    # Collect known directive matches (we'll strip these from the prompt)
    seen: dict[str, str] = {}  # directive name -> raw arg value
    # Regions to remove: list of (start, end) character positions
    regions_to_remove: list[tuple[int, int]] = []

    for match in matches:
        name = match.group(1)
        if name not in _KNOWN_DIRECTIVES:
            continue

        # Check for duplicates
        if name in seen:
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

        seen[name] = raw_arg
        regions_to_remove.append((match.start(), match_end))

    if not regions_to_remove:
        return prompt, PromptDirectives()

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

    # Build PromptDirectives from expanded args
    directives = PromptDirectives(
        model=expanded_args.get("model") or None,
    )

    return cleaned, directives
