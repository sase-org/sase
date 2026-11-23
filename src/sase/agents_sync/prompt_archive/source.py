"""Resolve local prompt sources and protect them while publication is pending."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    snapshot_agent_publications_from_path,
)
from sase.core.paths import sase_projects_dir


log = logging.getLogger(__name__)

_MONITOR_STARTER_KEY = "monitor_starter_artifacts_dir"
_MAX_STARTER_HOPS = 3

_ACTIVE_PINS_CACHE_KEY: tuple[tuple[str, int, int], ...] | None = None
_ACTIVE_PINS_CACHE_VALUE: frozenset[str] | None = None


def prompt_source_dirs(artifacts_dir: str | Path) -> tuple[Path, ...]:
    """Return *artifacts_dir* and its bounded monitor-starter chain.

    Returned paths are expanded and normalized with ``resolve(strict=False)``.
    A missing or unreadable ``agent_meta.json`` ends the chain without raising.
    """

    current = Path(artifacts_dir).expanduser()
    from sase.core.wait_dependency_resolution import read_json_dict

    seen: set[Path] = set()
    result: list[Path] = []
    for hop in range(_MAX_STARTER_HOPS + 1):
        normalized = current.expanduser().resolve(strict=False)
        if normalized in seen:
            break
        seen.add(normalized)
        result.append(normalized)
        if hop == _MAX_STARTER_HOPS:
            break
        meta = read_json_dict(current / "agent_meta.json")
        starter = meta.get(_MONITOR_STARTER_KEY) if meta is not None else None
        if not isinstance(starter, str) or not starter.strip():
            break
        current = Path(starter).expanduser()
    return tuple(result)


def first_prompt_source_dir(artifacts_dir: str | Path) -> Path | None:
    """Return the first directory in the starter chain containing a prompt."""

    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    return next(
        (
            directory
            for directory in prompt_source_dirs(artifacts_dir)
            if resolve_raw_prompt_path(directory) is not None
        ),
        None,
    )


def _active_prompt_source_pins() -> frozenset[str] | None:
    """Return prompt-source dirs needed by active outbox rows, failing closed."""

    global _ACTIVE_PINS_CACHE_KEY, _ACTIVE_PINS_CACHE_VALUE

    try:
        paths = tuple(
            sorted(
                sase_projects_dir().glob(f"*/{AGENT_PUBLICATION_OUTBOX_FILENAME}"),
                key=lambda path: str(path),
            )
        )
        signature = tuple(
            (
                str(path.resolve(strict=False)),
                path.stat().st_mtime_ns,
                path.stat().st_size,
            )
            for path in paths
        )
    except OSError:
        log.debug(
            "Could not stat agent-publication outboxes for prompt pins", exc_info=True
        )
        return None

    if signature == _ACTIVE_PINS_CACHE_KEY and _ACTIVE_PINS_CACHE_VALUE is not None:
        return _ACTIVE_PINS_CACHE_VALUE

    pins: set[str] = set()
    try:
        for path in paths:
            items = snapshot_agent_publications_from_path(path, path.parent.name)
            for item in items:
                if item.terminal or item.quarantined or not item.artifacts_dir:
                    continue
                pins.update(
                    str(directory.resolve(strict=False))
                    for directory in prompt_source_dirs(item.artifacts_dir)
                )
    except Exception:
        log.debug(
            "Could not read agent-publication outboxes for prompt pins", exc_info=True
        )
        return None

    value = frozenset(pins)
    _ACTIVE_PINS_CACHE_KEY = signature
    _ACTIVE_PINS_CACHE_VALUE = value
    return value


def artifacts_dir_has_pending_prompt_obligation(artifacts_dir: str | Path) -> bool:
    """Return whether deletion must retain this directory for prompt restore."""

    normalized = str(Path(artifacts_dir).expanduser().resolve(strict=False))
    pins = _active_prompt_source_pins()
    if pins is None:
        log.debug(
            "Deferring artifact deletion because publication prompt pins are unreadable: %s",
            normalized,
        )
        return True
    return normalized in pins


__all__ = [
    "artifacts_dir_has_pending_prompt_obligation",
    "first_prompt_source_dir",
    "prompt_source_dirs",
]
