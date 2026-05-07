"""Persistent storage of the user-managed tag on an agent identity.

Tags are stored under ``~/.sase/agent_tags.json`` as a JSON list of
``{"id": [agent_type, cl_name, raw_suffix], "tag": "<tag>"}`` records.
Each agent has at most one tag — the tag drives Agents-tab grouping and
(in Phase 3) the dynamic side-panel split.

Tag names match ``^[A-Za-z0-9_.-]+$`` and are stored *without* the ``@``
prefix; the prefix is purely a display affordance added by the TUI.

Legacy multi-tag entries (``"tags": [...]``) are silently migrated on
read by collapsing to the first element.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tui.models.agent import AgentType

_AGENT_TAGS_FILE = Path.home() / ".sase" / "agent_tags.json"

REVIEW_AGENT_TAG = "review"

TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class InvalidTagError(ValueError):
    """Raised when a tag name fails validation."""


def validate_tag_name(tag: str) -> str:
    """Return *tag* if valid, otherwise raise :class:`InvalidTagError`.

    Rejects empty strings, ``@``-prefixed values (with a hint to drop the
    prefix), and any character outside ``^[A-Za-z0-9_.-]+$``.
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
            f"tag name {tag!r} must match ^[A-Za-z0-9_.-]+$ "
            "(letters, digits, underscore, dot, dash)"
        )
    return tag


def load_agent_tags() -> dict[tuple[AgentType, str, str | None], str]:
    """Load tag assignments from disk.

    Returns:
        A dict mapping ``(AgentType, cl_name, raw_suffix)`` to a single
        tag name.  Untagged agents are simply absent from the dict.
        Empty dict on missing/malformed file.

    Migration: legacy entries with a list-shaped ``"tags"`` field are
    accepted and reduced to their first valid element.
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

    result: dict[tuple[AgentType, str, str | None], str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        identity_raw = entry.get("id")
        if not isinstance(identity_raw, list) or len(identity_raw) != 3:
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

        tag: str | None = None
        scalar_raw = entry.get("tag")
        if isinstance(scalar_raw, str) and TAG_NAME_RE.match(scalar_raw):
            tag = scalar_raw
        else:
            list_raw = entry.get("tags")
            if isinstance(list_raw, list):
                for candidate in list_raw:
                    if isinstance(candidate, str) and TAG_NAME_RE.match(candidate):
                        tag = candidate
                        break

        if tag is None:
            continue
        result[(agent_type, cl_name, raw_suffix)] = tag
    return result


def save_agent_tags(
    tags_by_identity: dict[tuple[AgentType, str, str | None], str],
) -> bool:
    """Persist tag assignments to disk atomically.

    Untagged identities (absent or empty) are dropped from the output so
    the on-disk file never carries vestigial entries.

    Returns:
        True on success, False on I/O failure.
    """
    try:
        _AGENT_TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        for (agent_type, cl_name, raw_suffix), tag in tags_by_identity.items():
            if not tag:
                continue
            entries.append(
                {
                    "id": [agent_type.value, cl_name, raw_suffix],
                    "tag": tag,
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


@contextmanager
def _agent_tags_file_lock() -> Iterator[None]:
    """Hold an exclusive lock for the agent tag store read-modify-write cycle."""
    import fcntl

    _AGENT_TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _AGENT_TAGS_FILE.parent / f"{_AGENT_TAGS_FILE.name}.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_agent_tag(
    identity: tuple[AgentType, str, str | None],
    tag: str,
) -> bool:
    """Atomically set one identity's tag in the persistent tag store.

    The whole load-modify-save cycle runs under an exclusive sibling lock,
    preventing concurrent runner launches from clobbering each other's tag
    assignments.
    """
    validate_tag_name(tag)
    try:
        with _agent_tags_file_lock():
            store = load_agent_tags()
            set_tag(store, identity, tag)
            return save_agent_tags(store)
    except OSError:
        return False


def set_tag(
    tags_by_identity: dict[tuple[AgentType, str, str | None], str],
    identity: tuple[AgentType, str, str | None],
    tag: str,
) -> str:
    """Set *identity*'s tag to *tag*, replacing any previous value.

    Mutates *tags_by_identity* in place and returns the new tag.
    The tag is validated via :func:`validate_tag_name`.
    """
    validate_tag_name(tag)
    tags_by_identity[identity] = tag
    return tag


def unset_tag(
    tags_by_identity: dict[tuple[AgentType, str, str | None], str],
    identity: tuple[AgentType, str, str | None],
) -> None:
    """Remove *identity*'s tag if present.

    Mutates *tags_by_identity* in place; no-op when the identity has no
    tag.
    """
    if identity in tags_by_identity:
        del tags_by_identity[identity]
