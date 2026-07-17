"""Resolve the chat transcript path for ``#fork`` workflows."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names import (
    find_named_agent,
    get_most_recent_agent_name,
    get_reserved_agent_name_map,
    is_agent_name_template,
    require_latest_agent_name_template,
    resolve_agent_name_template_reference,
)


@dataclass(frozen=True)
class _ForkSource:
    """One concrete parent conversation used by ``#fork``."""

    name: str
    path: str


def _resolve_agent_chat_path(name: str | None = None) -> str:
    """Return the chat path for an explicit or default resume target.

    Explicit names preserve the legacy lookup order: completed agents use
    ``done.json``'s ``response_path`` first, then any live/historical agent may
    provide ``agent_meta.json``'s ``chat_path``. An omitted name resolves to the
    most recently launched named agent, excluding ``SASE_ARTIFACTS_DIR`` so an
    agent cannot accidentally resume itself.
    """
    resolved_name = _normalize_name(name)
    if resolved_name is None:
        resolved_name = _resolve_default_agent_name()

    response_path = _resolve_done_response_path(resolved_name)
    if response_path:
        return response_path

    chat_path = _resolve_meta_chat_path(resolved_name)
    if chat_path:
        return chat_path

    raise RuntimeError(f"No agent with chat history found for: {resolved_name}")


def _resolve_agent_chat_sources(names: Sequence[str]) -> list[_ForkSource]:
    """Resolve and validate every requested parent as one atomic operation."""
    requested_names: list[str | None] = list(names) or [None]
    sources: list[_ForkSource] = []
    errors: list[str] = []

    for index, requested_name in enumerate(requested_names, start=1):
        label = requested_name or "<default>"
        try:
            resolved_name = _normalize_name(requested_name)
            if resolved_name is None:
                resolved_name = _resolve_default_agent_name()
            source = _ForkSource(
                name=resolved_name,
                path=_resolve_agent_chat_path(resolved_name),
            )
            _validate_readable_transcript(source)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"parent {index} ({label}): {exc}")
        else:
            sources.append(source)

    first_source_by_path: dict[str, _ForkSource] = {}
    for source in sources:
        canonical_path = str(Path(source.path).expanduser().resolve(strict=False))
        previous = first_source_by_path.get(canonical_path)
        if previous is not None:
            errors.append(
                f"parents '{previous.name}' and '{source.name}' resolve to the "
                f"same transcript: {source.path}"
            )
        else:
            first_source_by_path[canonical_path] = source

    if errors:
        raise RuntimeError("Invalid fork parents:\n- " + "\n- ".join(errors))
    return sources


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that prints resolved source metadata as JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="*")
    args = parser.parse_args(argv)
    sources = _resolve_agent_chat_sources(args.name)
    source_data = [{"name": source.name, "path": source.path} for source in sources]
    print(
        json.dumps(
            {
                # Keep the historical single-path field as a compatibility seam.
                "path": sources[0].path,
                "sources_json": json.dumps(source_data),
            }
        )
    )
    return 0


def _normalize_name(name: str | None) -> str | None:
    if name is None:
        return None
    stripped = name.strip()
    if not stripped:
        return None
    if is_agent_name_template(stripped):
        return _resolve_template_name_excluding_current_agent(stripped)
    return resolve_agent_name_template_reference(stripped)


def _resolve_template_name_excluding_current_agent(name: str) -> str:
    current_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not current_artifacts_dir:
        return resolve_agent_name_template_reference(name)

    current = Path(current_artifacts_dir).expanduser().resolve(strict=False)
    reserved = {
        agent_name
        for agent_name, owner_path in get_reserved_agent_name_map().items()
        if Path(owner_path).expanduser().resolve(strict=False) != current
    }
    return require_latest_agent_name_template(name, names=reserved)


def _resolve_default_agent_name() -> str:
    name = get_most_recent_agent_name(
        exclude_artifacts_dir=os.environ.get("SASE_ARTIFACTS_DIR")
    )
    if not name:
        raise RuntimeError("No previous named agent found for bare #fork")
    return name


def _validate_readable_transcript(source: _ForkSource) -> None:
    path = Path(source.path).expanduser()
    try:
        with open(path, encoding="utf-8"):
            pass
    except OSError as exc:
        raise OSError(
            f"Transcript for agent '{source.name}' is not readable: {source.path}"
        ) from exc


def _resolve_done_response_path(name: str) -> str | None:
    agent = find_named_agent(name, only_done=True)
    if agent is None:
        return None
    return _read_json_string_field(
        Path(agent.artifacts_dir) / "done.json", "response_path"
    )


def _resolve_meta_chat_path(name: str) -> str | None:
    agent = find_named_agent(name)
    if agent is None:
        return None
    return _read_json_string_field(
        Path(agent.artifacts_dir) / "agent_meta.json", "chat_path"
    )


def _read_json_string_field(path: Path, field: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            data: Any = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None
    value = data.get(field)
    return value if isinstance(value, str) and value else None


if __name__ == "__main__":
    raise SystemExit(main())
