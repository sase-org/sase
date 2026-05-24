"""Runtime provenance tags for real VCS commits."""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Mapping
from pathlib import Path

RUNTIME_COMMIT_TAG_KEYS = frozenset({"AGENT", "MACHINE"})

_TAG_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def _resolve_runtime_commit_tags() -> dict[str, str]:
    """Return runtime-owned commit tags for the current process."""
    tags: dict[str, str] = {}

    agent_name = _resolve_agent_name()
    if agent_name:
        tags["AGENT"] = agent_name

    machine_name = _resolve_machine_name()
    if machine_name:
        tags["MACHINE"] = machine_name

    return tags


def _resolve_agent_name() -> str | None:
    """Resolve the current SASE agent name, if one is available."""
    env_name = _sanitize_tag_value(os.environ.get("SASE_AGENT_NAME"))
    if env_name:
        return env_name

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    return _sanitize_tag_value(meta.get("name"))


def _resolve_machine_name() -> str | None:
    """Resolve the current host name for commit provenance."""
    try:
        machine_name = _sanitize_tag_value(socket.gethostname())
    except OSError:
        machine_name = None
    if machine_name:
        return machine_name
    return _sanitize_tag_value(os.environ.get("HOSTNAME"))


def apply_runtime_commit_tags(payload: dict) -> None:
    """Append or update runtime provenance tags in ``payload['message']``."""
    message = str(payload.get("message") or "")
    payload["message"] = update_trailing_commit_tags(
        message,
        _resolve_runtime_commit_tags(),
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )


def apply_auto_commit_type_tag(message: str, auto_commit_type: str) -> str:
    """Append or update the auto-commit ``TYPE`` tag in *message*."""
    return update_trailing_commit_tags(
        message,
        {"TYPE": auto_commit_type},
        remove_keys={"TYPE"},
    )


def update_trailing_commit_tags(
    message: str,
    updates: Mapping[str, object],
    *,
    remove_keys: frozenset[str] | set[str] = frozenset(),
) -> str:
    """Update the trailing ``KEY=VALUE`` tag block in *message*.

    Existing non-owned tags are preserved in their original order. Keys in
    ``remove_keys`` or ``updates`` are removed from the existing block first,
    then sanitized non-empty update values are appended.
    """
    body, existing_tags = _split_trailing_tag_block(message)
    sanitized_updates = {
        key: value
        for key, raw_value in updates.items()
        if (value := _sanitize_tag_value(raw_value))
    }
    owned_keys = set(remove_keys) | set(updates)

    merged_tags: list[tuple[str, str]] = [
        (key, value) for key, value in existing_tags if key not in owned_keys
    ]
    merged_tags.extend(sanitized_updates.items())

    if not merged_tags:
        return body

    tag_block = "\n".join(f"{key}={value}" for key, value in merged_tags)
    if body:
        return f"{body}\n\n{tag_block}"
    return tag_block


def filter_runtime_owned_tags(tags: Mapping[str, str]) -> dict[str, str]:
    """Remove runtime-owned tag keys from inherited/configured PR tag maps."""
    return {
        key: value for key, value in tags.items() if key not in RUNTIME_COMMIT_TAG_KEYS
    }


def _split_trailing_tag_block(message: str) -> tuple[str, list[tuple[str, str]]]:
    lines = message.split("\n")

    last_non_blank = len(lines) - 1
    while last_non_blank >= 0 and lines[last_non_blank].strip() == "":
        last_non_blank -= 1

    if last_non_blank < 0:
        return "", []

    tags_start_idx = last_non_blank + 1
    for idx in range(last_non_blank, -1, -1):
        stripped = lines[idx].strip()
        if _TAG_LINE_RE.match(stripped):
            tags_start_idx = idx
        elif stripped == "":
            continue
        else:
            break

    if tags_start_idx > last_non_blank:
        return message.rstrip(), []

    tags: list[tuple[str, str]] = []
    for line in lines[tags_start_idx : last_non_blank + 1]:
        stripped = line.strip()
        match = _TAG_LINE_RE.match(stripped)
        if match:
            tags.append((match.group(1), match.group(2)))

    body = "\n".join(lines[:tags_start_idx]).rstrip()
    return body, tags


def _sanitize_tag_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None
