"""Core-safe tribe reference and persisted tag helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sase.core.paths import sase_home

RawAgentTagIdentity = tuple[str, str, str | None]

TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class InvalidTagError(ValueError):
    """Raised when a tag or tribe name fails validation."""


def validate_tag_name(tag: str) -> str:
    """Return *tag* if it matches the persisted tribe/tag grammar."""
    if not isinstance(tag, str) or not tag:
        raise InvalidTagError("tag name must be a non-empty string")
    if tag.startswith("@"):
        raise InvalidTagError(
            f"tag name {tag!r} must not start with '@' "
            "(the '@' is added on display only — drop it from the input)"
        )
    if not TAG_NAME_RE.fullmatch(tag):
        raise InvalidTagError(
            f"tag name {tag!r} must match ^[A-Za-z0-9_.-]+$ "
            "(letters, digits, underscore, dot, dash)"
        )
    return tag


def parse_tribe_reference(value: str) -> str | None:
    """Return the validated bare tribe from ``@<tribe>``, else ``None``."""
    if not value.startswith("@"):
        return None
    return validate_tag_name(value[1:])


def load_raw_agent_tags(
    path: str | Path | None = None,
) -> dict[RawAgentTagIdentity, str]:
    """Load identity-neutral tag assignments without importing TUI types."""
    tags_path = Path(path) if path is not None else sase_home() / "agent_tags.json"
    try:
        with open(tags_path, encoding="utf-8") as tags_file:
            data = json.load(tags_file)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}

    result: dict[RawAgentTagIdentity, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        identity_raw = entry.get("id")
        if not isinstance(identity_raw, list) or len(identity_raw) != 3:
            continue
        agent_type, cl_name, raw_suffix = identity_raw
        if not isinstance(agent_type, str) or not isinstance(cl_name, str):
            continue
        if raw_suffix is not None and not isinstance(raw_suffix, str):
            continue

        tag: str | None = None
        scalar_raw = entry.get("tag")
        if isinstance(scalar_raw, str) and TAG_NAME_RE.fullmatch(scalar_raw):
            tag = scalar_raw
        else:
            list_raw = entry.get("tags")
            if isinstance(list_raw, list):
                tag = next(
                    (
                        candidate
                        for candidate in list_raw
                        if isinstance(candidate, str)
                        and TAG_NAME_RE.fullmatch(candidate)
                    ),
                    None,
                )
        if tag is not None:
            result[(agent_type, cl_name, raw_suffix)] = tag
    return result


__all__ = [
    "InvalidTagError",
    "RawAgentTagIdentity",
    "load_raw_agent_tags",
    "parse_tribe_reference",
    "validate_tag_name",
]
