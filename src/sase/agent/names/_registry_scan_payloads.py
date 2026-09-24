"""Payload decoding helpers for registry source scans."""

from __future__ import annotations

from sase.plan_chain import (
    agent_session_base,
    agent_session_parallel_value,
    agent_session_value,
)

import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home


def clan_from_payload(payload: dict[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None
    clan = payload.get("agent_clan")
    if not isinstance(clan, str) or not clan:
        agent_session = agent_session_value(payload)
        if (
            agent_session_parallel_value(payload) is not True
            or not isinstance(agent_session, str)
            or not agent_session
        ):
            return None
        clan = agent_session
    generation = payload.get("agent_clan_generation")
    if not isinstance(generation, str) or not generation:
        parent = payload.get("parent_timestamp")
        generation = parent if isinstance(parent, str) and parent else "legacy"
    return clan, generation


def agent_session_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict) or agent_session_parallel_value(payload) is True:
        return None
    agent_session = agent_session_value(payload)
    return agent_session if isinstance(agent_session, str) and agent_session else None


_NAME_KEYS = ("name", "workflow_name")
_BUNDLE_NAME_KEYS = ("agent_name", "workflow_name", "name")
_OWN_NAME_KEYS = ("name",)
_BUNDLE_OWN_NAME_KEYS = ("agent_name", "name")


def owner_identity_names(
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None = None,
    *,
    bundle: bool = False,
) -> set[str]:
    """Return the agent names an artifact or bundle owns.

    *primary* is the ``agent_meta.json`` (or dismissed-bundle) payload and
    *secondary* the ``done.json`` payload. Two stored names do not identify the
    artifact itself and are dropped, so a forced-reuse wipe of one session
    member never reaches its siblings or root through a shared name:

    * the agent-session container, which every member stores as
      ``workflow_name``; and
    * a ``done.json`` name of a *different* member of the same session, which a
      ``%auto`` chain copies into the root artifact dir when it continues
      in-process into the code step.

    The registry scan and the wipe pipeline both derive names here so the two
    cannot disagree about who owns a name.
    """
    keys = _BUNDLE_NAME_KEYS if bundle else _NAME_KEYS
    own_name = _first_name(primary, _BUNDLE_OWN_NAME_KEYS if bundle else _OWN_NAME_KEYS)
    agent_session = agent_session_from_payload(primary)

    names = _payload_names(primary, keys)
    done_names = _payload_names(secondary, keys)
    if agent_session is not None and own_name is not None:
        done_names = {
            name
            for name in done_names
            if name == own_name or agent_session_base(name) != agent_session
        }
    names |= done_names
    if agent_session is not None:
        names.discard(agent_session)
    return names


def _payload_names(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    return {
        value for key in keys if isinstance((value := payload.get(key)), str) and value
    }


def _first_name(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def artifact_owner(
    *,
    project_dir: Path,
    workflow_dir: Path,
    artifact_dir: Path,
    state: str,
) -> dict[str, Any]:
    return {
        "source": "artifact",
        "project_name": project_dir.name,
        "workflow_dir": workflow_dir.name,
        "raw_suffix": artifact_dir.name,
        "artifacts_dir": str(artifact_dir),
        "state": state,
        "created_at": artifact_dir.name,
    }


def bundle_owner(path: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "dismissed_bundle",
        "project_name": _project_name_from_bundle(bundle),
        "workflow_dir": "ace-run",
        "raw_suffix": _str_or_none(bundle.get("raw_suffix")) or path.stem,
        "artifacts_dir": _str_or_none(bundle.get("artifacts_dir")),
        "bundle_path": str(path),
        "state": "dismissed",
        "created_at": _str_or_none(bundle.get("raw_suffix")) or path.stem,
    }


def _project_name_from_bundle(bundle: dict[str, Any]) -> str | None:
    project_file = bundle.get("project_file")
    if isinstance(project_file, str) and project_file:
        return Path(project_file).parent.name
    artifacts_dir = bundle.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        parts = Path(artifacts_dir).parts
        try:
            idx = parts.index("projects")
        except ValueError:
            return None
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_dismissed_suffixes() -> set[str]:
    path = sase_home() / "dismissed_agents.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    suffixes: set[str] = set()
    for entry in data:
        raw_suffix: object | None = None
        if isinstance(entry, list) and len(entry) == 3:
            raw_suffix = entry[2]
        elif isinstance(entry, dict):
            raw_suffix = entry.get("raw_suffix")
        if isinstance(raw_suffix, str):
            suffixes.add(raw_suffix)
    return suffixes
