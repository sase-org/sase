"""Persistent standalone agent-tribe assignments.

This module keeps temporary tag-named entry points for the staged runtime
cutover.  Both the canonical and compatibility APIs read old state but write
only ``agent_tribes.json`` records containing a scalar ``tribe`` field.
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
    InvalidTribeError,
    canonical_agent_tribes_path,
    legacy_agent_tags_path,
    load_raw_agent_tags,
    load_raw_agent_tribes,
    validate_tribe_name,
)

if TYPE_CHECKING:
    from .tui.models.agent import AgentType

_AGENT_TRIBES_FILE: Path | None = None
_LEGACY_AGENT_TAGS_FILE: Path | None = None
# Compatibility test/caller override.  It now identifies the canonical output
# path even though the variable name predates the storage migration.
_AGENT_TAGS_FILE: Path | None = None

REVIEW_AGENT_TRIBE = "review"
PINNED_AGENT_TRIBE = "pinned"


def _agent_tribes_file() -> Path:
    return _AGENT_TRIBES_FILE or _AGENT_TAGS_FILE or canonical_agent_tribes_path()


def _legacy_agent_tags_file() -> Path:
    if _LEGACY_AGENT_TAGS_FILE is not None:
        return _LEGACY_AGENT_TAGS_FILE
    if _AGENT_TAGS_FILE is not None:
        return _AGENT_TAGS_FILE
    return legacy_agent_tags_path()


def load_agent_tribes() -> dict[tuple[AgentType, str, str | None], str]:
    """Load canonical assignments or importable legacy assignments."""
    from .tui.models.agent import AgentType

    result: dict[tuple[AgentType, str, str | None], str] = {}
    for (agent_type_raw, cl_name, raw_suffix), tribe in load_raw_agent_tribes(
        _agent_tribes_file(), legacy_path=_legacy_agent_tags_file()
    ).items():
        try:
            agent_type = AgentType(agent_type_raw)
        except (ValueError, TypeError):
            continue
        result[(agent_type, cl_name, raw_suffix)] = tribe
    return result


def save_agent_tribes(
    tribes_by_identity: dict[tuple[AgentType, str, str | None], str],
) -> bool:
    """Persist the complete canonical assignment store atomically."""
    try:
        path = _agent_tribes_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            {
                "id": [agent_type.value, cl_name, raw_suffix],
                "tribe": tribe,
            }
            for (agent_type, cl_name, raw_suffix), tribe in tribes_by_identity.items()
            if tribe
        ]
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".agent_tribes.", suffix=".json", dir=path.parent
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as store_file:
                json.dump(entries, store_file, indent=2)
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
def _agent_tribes_file_lock() -> Iterator[None]:
    """Lock the canonical read-modify-write cycle across processes."""
    import fcntl

    path = _agent_tribes_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f"{path.name}.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_agent_tribe(
    identity: tuple[AgentType, str, str | None],
    tribe: str,
) -> bool:
    """Atomically set one assignment, importing legacy state if necessary."""
    validate_tribe_name(tribe)
    try:
        with _agent_tribes_file_lock():
            store = load_agent_tribes()
            set_tribe(store, identity, tribe)
            return save_agent_tribes(store)
    except OSError:
        return False


def update_agent_tribe_assignment(
    identity: tuple[AgentType, str, str | None],
    tribe: str | None,
) -> bool:
    """Atomically set or clear one canonical tribe assignment."""
    if tribe is not None:
        validate_tribe_name(tribe)
    try:
        with _agent_tribes_file_lock():
            store = load_agent_tribes()
            before = store.get(identity)
            if tribe is None:
                unset_tribe(store, identity)
            else:
                set_tribe(store, identity, tribe)
            if store.get(identity) == before:
                return False
            return save_agent_tribes(store)
    except OSError:
        return False


def set_tribe(
    tribes_by_identity: dict[tuple[AgentType, str, str | None], str],
    identity: tuple[AgentType, str, str | None],
    tribe: str,
) -> str:
    """Set *identity* to a validated tribe, replacing its prior value."""
    validate_tribe_name(tribe)
    tribes_by_identity[identity] = tribe
    return tribe


def unset_tribe(
    tribes_by_identity: dict[tuple[AgentType, str, str | None], str],
    identity: tuple[AgentType, str, str | None],
) -> None:
    """Remove *identity* from the assignment map when present."""
    tribes_by_identity.pop(identity, None)


# Temporary compatibility exports used until the runtime cutover lands.
InvalidTagError = InvalidTribeError
REVIEW_AGENT_TAG = REVIEW_AGENT_TRIBE


def validate_tag_name(tag: str) -> str:
    return validate_tribe_name(tag)


def load_agent_tags() -> dict[tuple[AgentType, str, str | None], str]:
    if _AGENT_TAGS_FILE is None or _AGENT_TRIBES_FILE is not None:
        return load_agent_tribes()

    # An explicit old-name override is a compatibility-only legacy reader.
    # Once a mutation writes ``tribe`` records to that path, the canonical
    # reader takes over on subsequent calls.
    raw = load_raw_agent_tribes(
        _AGENT_TAGS_FILE,
        legacy_path=_AGENT_TAGS_FILE,
    )
    if not raw and _AGENT_TAGS_FILE.exists():
        raw = load_raw_agent_tags(_AGENT_TAGS_FILE)
    from .tui.models.agent import AgentType

    result: dict[tuple[AgentType, str, str | None], str] = {}
    for (agent_type_raw, cl_name, raw_suffix), tribe in raw.items():
        try:
            agent_type = AgentType(agent_type_raw)
        except (ValueError, TypeError):
            continue
        result[(agent_type, cl_name, raw_suffix)] = tribe
    return result


def save_agent_tags(
    tags_by_identity: dict[tuple[AgentType, str, str | None], str],
) -> bool:
    return save_agent_tribes(tags_by_identity)


def update_agent_tag(
    identity: tuple[AgentType, str, str | None],
    tag: str,
) -> bool:
    validate_tribe_name(tag)
    try:
        with _agent_tribes_file_lock():
            store = load_agent_tags()
            set_tribe(store, identity, tag)
            return save_agent_tribes(store)
    except OSError:
        return False


def update_agent_tag_assignment(
    identity: tuple[AgentType, str, str | None],
    tag: str | None,
) -> bool:
    if tag is not None:
        validate_tribe_name(tag)
    try:
        with _agent_tribes_file_lock():
            store = load_agent_tags()
            before = store.get(identity)
            if tag is None:
                unset_tribe(store, identity)
            else:
                set_tribe(store, identity, tag)
            if store.get(identity) == before:
                return False
            return save_agent_tribes(store)
    except OSError:
        return False


def set_tag(
    tags_by_identity: dict[tuple[AgentType, str, str | None], str],
    identity: tuple[AgentType, str, str | None],
    tag: str,
) -> str:
    return set_tribe(tags_by_identity, identity, tag)


def unset_tag(
    tags_by_identity: dict[tuple[AgentType, str, str | None], str],
    identity: tuple[AgentType, str, str | None],
) -> None:
    unset_tribe(tags_by_identity, identity)


__all__ = [
    "InvalidTribeError",
    "PINNED_AGENT_TRIBE",
    "REVIEW_AGENT_TRIBE",
    "load_agent_tribes",
    "save_agent_tribes",
    "set_tribe",
    "unset_tribe",
    "update_agent_tribe",
    "update_agent_tribe_assignment",
    "validate_tribe_name",
]
