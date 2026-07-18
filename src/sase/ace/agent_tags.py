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
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.agent_tribe import (
    InvalidTagError,
    load_raw_agent_tags,
    validate_tag_name,
)
from sase.core.paths import sase_home

if TYPE_CHECKING:
    from .tui.models.agent import AgentType

_AGENT_TAGS_FILE: Path | None = None

REVIEW_AGENT_TAG = "review"


def _agent_tags_file() -> Path:
    return _AGENT_TAGS_FILE or sase_home() / "agent_tags.json"


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

    result: dict[tuple[AgentType, str, str | None], str] = {}
    for (agent_type_raw, cl_name, raw_suffix), tag in load_raw_agent_tags(
        _agent_tags_file()
    ).items():
        try:
            agent_type = AgentType(agent_type_raw)
        except (ValueError, TypeError):
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
        path = _agent_tags_file()
        path.parent.mkdir(parents=True, exist_ok=True)
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
            prefix=".agent_tags.", suffix=".json", dir=path.parent
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp_path, path)
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

    path = _agent_tags_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f"{path.name}.lock"
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


def update_agent_tag_assignment(
    identity: tuple[AgentType, str, str | None],
    tag: str | None,
) -> bool:
    """Atomically set or clear one identity's persistent tag assignment.

    Returns True when the on-disk store changed and False when the identity was
    already in the requested state or the save failed.
    """
    try:
        with _agent_tags_file_lock():
            store = load_agent_tags()
            before = store.get(identity)
            if tag is None:
                unset_tag(store, identity)
            else:
                set_tag(store, identity, tag)
            if store.get(identity) == before:
                return False
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
