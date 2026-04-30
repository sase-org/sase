"""Shorthand syntax preprocessing for xprompt references."""

import re

from ._parsing_args import find_matching_paren_for_args


# Pattern to match shorthand syntax: #name: text
# Note: The space after colon distinguishes from existing #name:arg syntax
SHORTHAND_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"  # Group 1: name
    r": "  # Colon followed by space
)

# Pattern to match paren shorthand: #name(
_PAREN_SHORTHAND_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"\("
)

# Pattern to match double-colon shorthand: #name:: text
DOUBLE_COLON_SHORTHAND_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"  # Group 1: name
    r":: "  # Double colon followed by space
)

# Pattern to find the start of the next xprompt directive at a line boundary.
# Used by double-colon shorthand to know where its text ends.
_NEXT_DIRECTIVE_PATTERN = re.compile(
    r"\n(?=#[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*(?:\(|::? ))"
)


def find_shorthand_text_end(prompt: str, start: int) -> int:
    """Find the end of shorthand text (at \\n\\n or end of string)."""
    blank_line_pos = prompt.find("\n\n", start)
    if blank_line_pos == -1:
        return len(prompt)
    return blank_line_pos


def find_double_colon_text_end(prompt: str, start: int) -> int:
    """Find the end of double-colon text (at next directive or end of string).

    Unlike single-colon shorthand which terminates at blank lines, double-colon
    text includes blank lines and only terminates at the next xprompt directive
    at the start of a line, or at EOF.
    """
    match = _NEXT_DIRECTIVE_PATTERN.search(prompt, start)
    if match is None:
        return len(prompt)
    return match.start()


def _format_as_text_block(text: str) -> str:
    """Format text for use inside a [[...]] text block.

    Adds 2-space indent on continuation lines, preserves empty lines.
    """
    lines = text.split("\n")
    formatted_lines = [lines[0]]
    for line in lines[1:]:
        if line.strip() == "":
            formatted_lines.append("")
        else:
            formatted_lines.append("  " + line)
    return "\n".join(formatted_lines)


def _preprocess_paren_shorthand(prompt: str, xprompt_names: set[str]) -> str:
    """Convert #name(args): text shorthand to #name(args, [[text]]) format."""
    matches = list(re.finditer(_PAREN_SHORTHAND_PATTERN, prompt))

    for match in reversed(matches):
        name = match.group(1)
        if name not in xprompt_names:
            continue

        # Position of the opening '('
        paren_open = match.end() - 1
        paren_close = find_matching_paren_for_args(prompt, paren_open)
        if paren_close is None:
            continue

        # Check for "):: " (double-colon) or "): " (single-colon) after paren
        after_paren = prompt[paren_close + 1 :]
        if after_paren.startswith(":: "):
            text_start = paren_close + 4  # skip "):: "
            text_end = find_double_colon_text_end(prompt, text_start)
        elif after_paren.startswith(": "):
            text_start = paren_close + 3  # skip "): "
            text_end = find_shorthand_text_end(prompt, text_start)
        else:
            continue
        text = prompt[text_start:text_end].rstrip()

        text_block_content = _format_as_text_block(text)
        args_str = prompt[paren_open + 1 : paren_close].strip()

        if args_str:
            replacement = f"#{name}({args_str}, [[{text_block_content}]])"
        else:
            # Empty parens: #name(): text -> #name([[text]])
            replacement = f"#{name}([[{text_block_content}]])"

        prompt = prompt[: match.start()] + replacement + prompt[text_end:]

    return prompt


def preprocess_shorthand_syntax(prompt: str, xprompt_names: set[str]) -> str:
    """Convert shorthand #name: text syntax to #name([[text]]) format."""
    # Pass 1: Handle paren shorthand (#name(args): text and #name(args):: text)
    prompt = _preprocess_paren_shorthand(prompt, xprompt_names)

    # Pass 2: Handle simple double-colon shorthand (#name:: text)
    matches = list(re.finditer(DOUBLE_COLON_SHORTHAND_PATTERN, prompt))

    for match in reversed(matches):
        name = match.group(1)
        if name not in xprompt_names:
            continue

        text_start = match.end()
        text_end = find_double_colon_text_end(prompt, text_start)
        text = prompt[text_start:text_end].rstrip()

        text_block_content = _format_as_text_block(text)
        replacement = f"#{name}([[{text_block_content}]])"

        prompt = prompt[: match.start()] + replacement + prompt[text_end:]

    # Pass 3: Handle simple single-colon shorthand (#name: text)
    matches = list(re.finditer(SHORTHAND_PATTERN, prompt))

    for match in reversed(matches):  # Process last-to-first to preserve positions
        name = match.group(1)
        if name not in xprompt_names:
            continue

        text_start = match.end()
        text_end = find_shorthand_text_end(prompt, text_start)
        text = prompt[text_start:text_end].rstrip()

        text_block_content = _format_as_text_block(text)
        replacement = f"#{name}([[{text_block_content}]])"

        prompt = prompt[: match.start()] + replacement + prompt[text_end:]

    return prompt
