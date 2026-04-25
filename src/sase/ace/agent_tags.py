"""Persistent storage of user-managed tags on agent identities.

Tags are stored under ``~/.sase/agent_tags.json`` as a JSON list of
``{"id": [agent_type, cl_name, raw_suffix], "tags": [tag1, tag2, ...]}``
records.  The first tag in the list is the agent's *primary* tag — Phase 3+
will use it to decide which tag-group an agent renders under.

Tag names match ``^[A-Za-z0-9_-]+$`` and are stored *without* the ``@``
prefix; the prefix is purely a display affordance added by the TUI.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tui.models.agent import AgentType

_AGENT_TAGS_FILE = Path.home() / ".sase" / "agent_tags.json"

TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class InvalidTagError(ValueError):
    """Raised when a tag name fails validation."""


def validate_tag_name(tag: str) -> str:
    """Return *tag* if valid, otherwise raise :class:`InvalidTagError`.

    Rejects empty strings, ``@``-prefixed values (with a hint to drop the
    prefix), and any character outside ``^[A-Za-z0-9_-]+$``.
    """
    if not isinstance(tag, str) or not tag:
        raise InvalidTagError("tag name must be a non-empty string")
    if tag.startswith("@"):
        raise InvalidTagError(
            f"tag name {tag!r} must not start with '@' "
            "(the '@' is added on display only — drop it from the input)"
        )
    if not TAG_NAME_RE.match(tag):
        raise InvalidTagError(
            f"tag name {tag!r} must match ^[A-Za-z0-9_-]+$ "
            "(letters, digits, underscore, dash)"
        )
    return tag


def load_agent_tags() -> dict[tuple[AgentType, str, str | None], tuple[str, ...]]:
    """Load tag assignments from disk.

    Returns:
        A dict mapping ``(AgentType, cl_name, raw_suffix)`` to an ordered
        tuple of tag names.  Empty dict on missing/malformed file.
    """
    from .tui.models.agent import AgentType

    if not _AGENT_TAGS_FILE.exists():
        return {}

    try:
        with open(_AGENT_TAGS_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}

    result: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        identity_raw = entry.get("id")
        tags_raw = entry.get("tags")
        if not isinstance(identity_raw, list) or len(identity_raw) != 3:
            continue
        if not isinstance(tags_raw, list):
            continue
        try:
            agent_type = AgentType(identity_raw[0])
        except (ValueError, TypeError):
            continue
        cl_name = identity_raw[1]
        raw_suffix = identity_raw[2]
        if not isinstance(cl_name, str):
            continue
        if raw_suffix is not None and not isinstance(raw_suffix, str):
            continue
        clean_tags: list[str] = []
        seen: set[str] = set()
        for tag in tags_raw:
            if not isinstance(tag, str):
                continue
            if not TAG_NAME_RE.match(tag):
                continue
            if tag in seen:
                continue
            seen.add(tag)
            clean_tags.append(tag)
        if not clean_tags:
            continue
        result[(agent_type, cl_name, raw_suffix)] = tuple(clean_tags)
    return result


def save_agent_tags(
    tags_by_identity: dict[tuple[AgentType, str, str | None], tuple[str, ...]],
) -> bool:
    """Persist tag assignments to disk atomically.

    Empty tag lists are dropped from the output so the on-disk file never
    carries vestigial empty entries.

    Returns:
        True on success, False on I/O failure.
    """
    try:
        _AGENT_TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        for (agent_type, cl_name, raw_suffix), tags in tags_by_identity.items():
            if not tags:
                continue
            entries.append(
                {
                    "id": [agent_type.value, cl_name, raw_suffix],
                    "tags": list(tags),
                }
            )
        # Atomic replace: write to a sibling tempfile, then rename.
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".agent_tags.", suffix=".json", dir=_AGENT_TAGS_FILE.parent
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp_path, _AGENT_TAGS_FILE)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def add_tags(
    tags_by_identity: dict[tuple[AgentType, str, str | None], tuple[str, ...]],
    identity: tuple[AgentType, str, str | None],
    new_tags: list[str],
) -> tuple[str, ...]:
    """Append *new_tags* to *identity*'s tags, preserving order.

    Existing tags keep their relative position (so the primary tag is
    stable).  New tags are appended in the order given, skipping any that
    are already present.  Mutates *tags_by_identity* in place and returns
    the resulting tag tuple.

    Each tag is validated via :func:`validate_tag_name`.
    """
    for tag in new_tags:
        validate_tag_name(tag)
    current = list(tags_by_identity.get(identity, ()))
    current_set = set(current)
    for tag in new_tags:
        if tag in current_set:
            continue
        current.append(tag)
        current_set.add(tag)
    result = tuple(current)
    if result:
        tags_by_identity[identity] = result
    return result


def remove_tags(
    tags_by_identity: dict[tuple[AgentType, str, str | None], tuple[str, ...]],
    identity: tuple[AgentType, str, str | None],
    drop_tags: list[str],
) -> tuple[str, ...]:
    """Remove each tag in *drop_tags* from *identity*'s tag list.

    Mutates *tags_by_identity* in place; deletes the identity entry
    entirely when no tags remain.  Returns the resulting tag tuple
    (empty when the agent has no tags after removal).

    Tag names are validated for input shape so that callers can't smuggle
    illegal characters through this path either.
    """
    for tag in drop_tags:
        validate_tag_name(tag)
    current = list(tags_by_identity.get(identity, ()))
    drop_set = set(drop_tags)
    remaining = tuple(t for t in current if t not in drop_set)
    if remaining:
        tags_by_identity[identity] = remaining
    elif identity in tags_by_identity:
        del tags_by_identity[identity]
    return remaining
