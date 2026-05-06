"""Durable mobile agent launch, kill, and retry context state."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._mobile_agent_common import (
    MOBILE_AGENT_SCHEMA_VERSION,
    MobileProjectContext,
    optional_str,
    optional_uint,
    option_id,
)
from ._mobile_agent_context import (
    project_context_from_agent,
    project_context_to_record,
)
from ._mobile_agent_deps import KillResult, RunningAgentInfo
from ._mobile_agent_paths import (
    mobile_kill_context_dir,
    mobile_launch_context_store_path,
)


def persist_mobile_kill_context(
    name: str,
    request: dict[str, Any],
    before: RunningAgentInfo | None,
    result: KillResult,
) -> None:
    context_dir = mobile_kill_context_dir()
    context_dir.mkdir(parents=True, exist_ok=True)
    project_context = project_context_from_agent(before) if before is not None else None
    context = {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agent_name": name,
        "artifact_dir": result.artifacts_dir
        or (before.artifacts_dir if before is not None else None),
        "artifacts_timestamp": result.timestamp
        or artifact_timestamp(before.artifacts_dir if before else None),
        "project": result.project or (before.project if before is not None else None),
        "project_file": project_context.project_file
        if project_context is not None
        else None,
        "project_context": project_context_to_record(project_context),
        "raw_prompt": before.prompt if before is not None else None,
        "killed_pid": optional_uint(result.pid),
        "device_id": optional_str(request.get("device_id")),
        "reason": optional_str(request.get("reason")),
        "status": result.status or "killed",
        "killed_at": datetime.now(UTC).isoformat(),
    }
    final_path = context_dir / f"{option_id(name)}.json"
    tmp_path = final_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(context, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, final_path)


def persist_mobile_launch_contexts(
    response: dict[str, Any],
    prompt: str,
    request: dict[str, Any],
    *,
    launch_kind: str,
    image_host_path: str | None,
    source_agent_name: str | None,
    retry_of_agent: str | None,
    project_context: MobileProjectContext | None,
) -> None:
    slots = response.get("slots")
    if not isinstance(slots, list):
        return

    store_path = mobile_launch_context_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    launched_at = datetime.now(UTC).isoformat()
    request_id = optional_str(request.get("request_id"))
    device_id = optional_str(request.get("device_id"))
    rows: list[dict[str, Any]] = []

    for slot in slots:
        if not isinstance(slot, dict) or slot.get("status") != "launched":
            continue
        agent_name = optional_str(slot.get("name"))
        artifact_dir = optional_str(slot.get("artifact_dir"))
        if not agent_name and artifact_dir:
            agent_name = agent_name_from_artifact_meta(artifact_dir)
        if not agent_name:
            continue
        row = {
            "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
            "launch_kind": launch_kind,
            "agent_name": agent_name,
            "source_agent_name": source_agent_name,
            "retry_of_agent": retry_of_agent,
            "artifact_dir": artifact_dir,
            "artifacts_timestamp": artifact_timestamp(artifact_dir),
            "project": (project_context.project if project_context else None)
            or optional_str(request.get("project"))
            or project_from_artifact_dir(artifact_dir),
            "project_file": project_context.project_file
            if project_context is not None
            else None,
            "project_context": project_context_to_record(project_context),
            "raw_prompt_path": str(Path(artifact_dir) / "raw_xprompt.md")
            if artifact_dir
            else None,
            "prompt_snapshot": prompt,
            "image_host_path": image_host_path,
            "request_id": request_id,
            "device_id": device_id,
            "launched_at": launched_at,
        }
        rows.append(row)

    if not rows:
        return
    with store_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def latest_mobile_launch_context(name: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for row in iter_mobile_launch_contexts():
        agent_name = optional_str(row.get("agent_name"))
        artifact_dir = optional_str(row.get("artifact_dir"))
        artifacts_timestamp = optional_str(row.get("artifacts_timestamp"))
        if (
            agent_name == name
            or artifacts_timestamp == name
            or (artifact_dir and Path(artifact_dir).name == name)
        ):
            latest = row
    return latest


def iter_mobile_launch_contexts() -> list[dict[str, Any]]:
    path = mobile_launch_context_store_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def mobile_kill_context(name: str) -> dict[str, Any] | None:
    path = mobile_kill_context_dir() / f"{option_id(name)}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("agent_name", name)
    data.setdefault("prompt_snapshot", data.get("raw_prompt"))
    return data


def context_from_agent(agent: RunningAgentInfo) -> dict[str, Any]:
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agent_name": agent.name or "(unnamed)",
        "artifact_dir": agent.artifacts_dir,
        "artifacts_timestamp": artifact_timestamp(agent.artifacts_dir),
        "project": agent.project,
        "raw_prompt_path": str(Path(agent.artifacts_dir) / "raw_xprompt.md")
        if agent.artifacts_dir
        else None,
        "prompt_snapshot": agent.prompt,
        "source_agent_name": None,
    }


def artifact_timestamp(artifacts_dir: str | None) -> str | None:
    if not artifacts_dir:
        return None
    return Path(artifacts_dir).name


def read_prompt_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        prompt = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    prompt = prompt.strip()
    return prompt or None


def agent_name_from_artifact_meta(artifact_dir: str) -> str | None:
    try:
        data = json.loads((Path(artifact_dir) / "agent_meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return optional_str(data.get("name"))


def project_from_artifact_dir(artifact_dir: str | None) -> str | None:
    if not artifact_dir:
        return None
    parts = Path(artifact_dir).parts
    try:
        index = parts.index("projects")
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def project_context_from_kill_or_launch_context(
    context: dict[str, Any],
) -> MobileProjectContext | None:
    from ._mobile_agent_context import project_context_from_context

    return project_context_from_context(context)
