"""Mobile project-context resolution and launch cwd handling."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._mobile_agent_common import (
    MOBILE_AGENT_SCHEMA_VERSION,
    MobileAgentBridgeError,
    MobileProjectContext,
    _SAFE_PROJECT_NAME_RE,
    optional_str,
    safe_context_id,
)
from ._mobile_agent_deps import RunningAgentInfo
from ._mobile_agent_paths import device_project_context_path, sase_home


def project_context_from_request(
    request: dict[str, Any],
    prompt: str,
) -> MobileProjectContext | None:
    project_context = project_context_from_project_value(
        optional_str(request.get("project"))
    )
    vcs_context = project_context_from_prompt(prompt, project_context)
    return vcs_context or project_context


def project_context_from_project_value(
    raw_project: str | None,
) -> MobileProjectContext | None:
    if raw_project is None:
        return None
    value = raw_project.strip()
    if not value:
        return None
    if value.startswith("project:"):
        value = value.split(":", 1)[1].strip()
    if value in {"home", "home-mode"}:
        return MobileProjectContext(
            context_id="home",
            mode="home",
            project="home",
            project_file=str(known_project_file("home")),
        )
    if (
        "/" in value
        or "\\" in value
        or value in {".", ".."}
        or not _SAFE_PROJECT_NAME_RE.fullmatch(value)
    ):
        raise MobileAgentBridgeError(
            "project must be a known SASE project name, not a path"
        )
    project_file = known_project_file(value)
    if not project_file.is_file():
        raise MobileAgentBridgeError(f"unknown mobile project context: {value}")
    return MobileProjectContext(
        context_id=f"project:{value}",
        mode="project",
        project=value,
        project_file=str(project_file),
    )


def project_context_from_prompt(
    prompt: str,
    base: MobileProjectContext | None,
) -> MobileProjectContext | None:
    ref = mobile_prompt_vcs_ref(prompt)
    if ref is None:
        return None
    workflow, ref_value = ref
    base_id = base.context_id if base is not None else "current"
    context_id = safe_context_id(f"{base_id}:{workflow}:{ref_value}")
    return MobileProjectContext(
        context_id=context_id,
        mode="vcs_ref",
        project=base.project if base is not None else None,
        project_file=base.project_file if base is not None else None,
        workflow=workflow,
        ref=ref_value,
    )


def mobile_prompt_vcs_ref(prompt: str) -> tuple[str, str] | None:
    try:
        from sase.workspace_provider import get_ref_patterns

        patterns = get_ref_patterns()
    except Exception:
        return None
    for workflow, pattern in patterns.items():
        match = pattern.search(prompt)
        if match is None:
            continue
        ref_value = match.group(1) or match.group(2)
        if ref_value:
            return workflow, ref_value
    return None


def known_project_file(project: str) -> Path:
    return sase_home() / "projects" / project / f"{project}.gp"


@contextmanager
def mobile_launch_cwd(
    project_context: MobileProjectContext | None,
) -> Iterator[None]:
    cwd = launch_cwd_for_project_context(project_context)
    if cwd is None:
        yield
        return

    previous = os.getcwd()
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(previous)


def launch_cwd_for_project_context(
    project_context: MobileProjectContext | None,
) -> str | None:
    if project_context is None or project_context.project_file is None:
        return None
    if project_context.project == "home":
        return None

    from sase.workspace_provider.utils import parse_workspace_dir

    workspace_dir = parse_workspace_dir(project_context.project_file)
    if not workspace_dir:
        raise MobileAgentBridgeError(
            f"project context {project_context.project} has no workspace directory"
        )
    workspace_path = Path(workspace_dir).expanduser()
    if not workspace_path.is_dir():
        raise MobileAgentBridgeError(
            f"project context {project_context.project} workspace is unavailable"
        )
    return str(workspace_path)


def project_context_to_record(
    context: MobileProjectContext | None,
) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "context_id": context.context_id,
        "mode": context.mode,
        "project": context.project,
        "project_file": context.project_file,
        "workflow": context.workflow,
        "ref": context.ref,
    }


def project_context_from_context(
    context: dict[str, Any],
) -> MobileProjectContext | None:
    raw = context.get("project_context")
    if isinstance(raw, dict):
        context_id = optional_str(raw.get("context_id"))
        mode = optional_str(raw.get("mode"))
        if context_id and mode:
            return MobileProjectContext(
                context_id=context_id,
                mode=mode,
                project=optional_str(raw.get("project")),
                project_file=optional_str(raw.get("project_file")),
                workflow=optional_str(raw.get("workflow")),
                ref=optional_str(raw.get("ref")),
            )
    project = optional_str(context.get("project"))
    project_file = optional_str(context.get("project_file"))
    if project:
        project_path = known_project_file(project)
        return MobileProjectContext(
            context_id="home" if project == "home" else f"project:{project}",
            mode="home" if project == "home" else "project",
            project=project,
            project_file=project_file
            or (str(project_path) if project_path.is_file() else None),
        )
    return None


def project_context_from_agent(
    agent: RunningAgentInfo,
) -> MobileProjectContext | None:
    if not agent.project:
        return None
    project_file = known_project_file(agent.project)
    return MobileProjectContext(
        context_id="home" if agent.project == "home" else f"project:{agent.project}",
        mode="home" if agent.project == "home" else "project",
        project=agent.project,
        project_file=str(project_file),
    )


def persist_last_mobile_project_context(
    device_id: str | None,
    context: MobileProjectContext | None,
) -> None:
    if not device_id or context is None:
        return
    final_path = device_project_context_path(device_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "device_id": device_id,
        "project_context": project_context_to_record(context),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    tmp_path = final_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, final_path)
