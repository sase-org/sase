import re
from typing import Any

import yaml  # type: ignore[import-untyped]


def _str_literal_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Represent multi-line strings with literal block style."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _LiteralBlockDumper(yaml.SafeDumper):
    """YAML Dumper that uses literal block style for multi-line strings."""

    pass


_LiteralBlockDumper.add_representer(str, _str_literal_representer)


def dump_yaml(data: Any, sort_keys: bool = True) -> str:
    """Dump data to YAML with proper multi-line string handling.

    Uses literal block style (|) for multi-line strings to preserve
    exact newline formatting.
    """
    return yaml.dump(
        data, default_flow_style=False, sort_keys=sort_keys, Dumper=_LiteralBlockDumper
    )


def apply_section_marker_handling(content: str, is_at_line_start: bool) -> str:
    """Apply section marker handling for content starting with ### or ---.

    For content starting with section markers (### or ---):
    - Prepends \\n\\n when not at the start of a line (for proper spacing)
    - Strips "---" marker lines (they're just signals, not content)

    The --- marker serves as a signal that triggers newline handling
    without appearing in the final output.

    Args:
        content: The content to process
        is_at_line_start: Whether the content appears at the start of a line

    Returns:
        The processed content with section marker handling applied
    """
    starts_with_section_marker = content.startswith("###") or content.startswith("---")

    if not starts_with_section_marker:
        return content

    has_hr_marker = content.startswith("---\n") or content.strip() == "---"

    # Strip --- marker if present (it's just a signal, not content)
    if has_hr_marker:
        if content.strip() == "---":
            content = ""
        else:
            # Remove "---\n" and any leading newlines after it
            content = content[4:].lstrip("\n")

    # Prepend newlines to create a paragraph break before the content.
    if not is_at_line_start and content:
        # Mid-line: need two newlines to end the current line AND create a blank line.
        content = "\n\n" + content
    elif is_at_line_start and has_hr_marker and content:
        # At line start with a --- marker: the caller already has one \n before
        # the insertion point, but a single \n is just a soft line break that
        # prettier will reflow into the same paragraph.  Prepend one more \n so
        # the total is \n\n (a blank line), which is a proper paragraph break.
        content = "\n" + content

    return content


def content_ends_with_markdown_heading(content: str) -> bool:
    """Check if content ends with a markdown heading without a trailing newline.

    Returns True if the content ends with a markdown heading line (starts
    with # followed by a space) and does NOT already have a trailing newline.
    This detects cases where template rendering strips trailing newlines,
    which would cause subsequent content to be appended onto the heading line.
    """
    if not content or content.endswith("\n"):
        return False
    last_line = content.rsplit("\n", 1)[-1]
    return bool(re.match(r"#{1,6}\s", last_line))


def ensure_str_content(content: str | list[str | dict[Any, Any]]) -> str:
    """Ensure AIMessage content is a string.

    AIMessage.content can be either a string or a list of content parts.
    This function ensures we always get a string representation.
    """
    if isinstance(content, str):
        return content
    # Handle list content by converting to string
    return str(content)
