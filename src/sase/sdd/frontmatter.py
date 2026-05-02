"""Structured YAML frontmatter helpers for SDD markdown files."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml  # type: ignore[import-untyped]


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str, bool]:
    """Return ``(frontmatter, body, had_frontmatter)`` for markdown content."""
    if not content.startswith("---\n"):
        return {}, content, False

    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content, False

    raw = content[4:end]
    try:
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError:
        return {}, content, False
    if not isinstance(parsed, dict):
        parsed = {}
    return dict(parsed), content[end + 5 :], True


def _serialize_frontmatter(frontmatter: Mapping[str, Any], body: str) -> str:
    """Serialize frontmatter and body using stable block-style YAML."""
    yaml_text = yaml.safe_dump(
        dict(frontmatter),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{yaml_text}---\n{body}"


def set_frontmatter_fields(content: str, fields: Mapping[str, Any]) -> str:
    """Set or replace frontmatter fields while preserving existing body text."""
    frontmatter, body, _ = parse_frontmatter(content)
    frontmatter.update(fields)
    return _serialize_frontmatter(frontmatter, body)
