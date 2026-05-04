"""Resolve the chat transcript path for ``#resume`` workflows."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.agent.names import find_named_agent, get_most_recent_agent_name


def resolve_agent_chat_path(name: str | None = None) -> str:
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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that prints ``{"path": "<chat-path>"}``."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", default=None)
    args = parser.parse_args(argv)
    print(json.dumps({"path": resolve_agent_chat_path(args.name)}))
    return 0


def _normalize_name(name: str | None) -> str | None:
    if name is None:
        return None
    stripped = name.strip()
    return stripped or None


def _resolve_default_agent_name() -> str:
    name = get_most_recent_agent_name(
        exclude_artifacts_dir=os.environ.get("SASE_ARTIFACTS_DIR")
    )
    if not name:
        raise RuntimeError("No previous named agent found for bare #resume")
    return name


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
