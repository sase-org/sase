"""YAML front matter parsing for macro files."""

from typing import Any

import yaml  # type: ignore[import-untyped]


def parse_yaml_front_matter_with_error(
    content: str,
) -> tuple[dict[str, Any] | None, str, yaml.YAMLError | None]:
    """Parse YAML front matter delimited by --- lines.

    Args:
        content: The full file content.

    Returns:
        Tuple of (front_matter_dict, body_content, parse_error).
        front_matter_dict is None if no front matter found.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, content, None

    # Find the closing ---
    end_index = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index == -1:
        # No closing ---, treat as no front matter
        return None, content, None

    # Extract and parse YAML
    yaml_content = "\n".join(lines[1:end_index])
    try:
        front_matter = yaml.safe_load(yaml_content)
        if not isinstance(front_matter, dict):
            front_matter = {}
    except yaml.YAMLError as exc:
        # Invalid YAML, treat as no front matter
        return None, content, exc

    # Body is everything after the closing ---
    body = "\n".join(lines[end_index + 1 :])
    # Remove leading newline if present (common after front matter)
    if body.startswith("\n"):
        body = body[1:]

    return front_matter, body, None


def parse_yaml_front_matter(content: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML front matter delimited by --- lines.

    Invalid YAML preserves the historical fallback of treating the full content
    as plain body text.
    """
    front_matter, body, _error = parse_yaml_front_matter_with_error(content)
    return front_matter, body
