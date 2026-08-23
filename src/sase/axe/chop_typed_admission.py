"""AXE-owned dispatch metadata for durable typed chop admission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from sase.agent.launch_admission_runtime import UnitDispatcher
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import agent_unit_dispatch_prompt
from sase.core.agent_launch_wire import AgentUnitWire, LaunchUnitWire

from .chop_agents import build_chop_launch_env

AXE_CHOP_SOURCE_SURFACE = "axe_chop"
UNIT_DISPATCH_METADATA_KEY = "unit_dispatch_metadata"


def is_axe_chop_typed_request(data: Mapping[str, Any]) -> bool:
    """Return whether a typed admission bundle is owned by an AXE chop run."""
    return str(data.get("source_surface") or "") == AXE_CHOP_SOURCE_SURFACE


def make_axe_chop_agent_dispatcher(
    data: Mapping[str, Any],
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
) -> UnitDispatcher | None:
    """Build an agent dispatcher that preserves chop ownership per logical unit."""
    metadata = _unit_metadata(data)
    if not metadata:
        return None

    def _dispatch(
        unit: LaunchUnitWire,
        fingerprint: str,
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        if not isinstance(unit.payload, AgentUnitWire):
            return False, None, "not_an_agent_unit", []
        unit_meta = metadata.get(unit.logical_id)
        if unit_meta is None:
            return False, None, f"missing AXE chop metadata for {unit.logical_id}", []

        prompt = agent_unit_dispatch_prompt(unit.payload)
        extra_env = _unit_dispatch_env(unit_meta, prompt, unit.logical_id, fingerprint)
        launch = launch_agents_from_cwd_fn
        if launch is None:
            from sase.agent import launcher as launcher_mod

            launch = launcher_mod.launch_agents_from_cwd
        results = list(launch(prompt, extra_env=extra_env))
        if not results:
            return False, None, "agent_dispatch_produced_no_results", []
        if launch_recorded_fn is not None:
            for result in results:
                launch_recorded_fn(
                    launch_descriptor_from_metadata(
                        unit_meta,
                        result,
                        logical_id=unit.logical_id,
                        fingerprint=fingerprint,
                    )
                )
        identity = results[0].agent_name or f"pid:{results[0].pid}"
        return True, identity, None, cast(list[AgentLaunchResult], results)

    return _dispatch


def launch_descriptor_from_metadata(
    metadata: Mapping[str, Any],
    result: Any,
    *,
    logical_id: str | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build the chop run launch row for a typed-admitted agent."""
    from sase.artifacts import convert_timestamp_to_artifacts_format

    timestamp = str(getattr(result, "timestamp", "") or "")
    artifacts_timestamp = str(getattr(result, "artifacts_timestamp", "") or "")
    if not artifacts_timestamp and timestamp:
        artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    return {
        "index": int(metadata.get("proposal_index") or 0),
        "id": _str_or_none(metadata.get("proposal_id")),
        "agent_name": str(
            getattr(result, "agent_name", "") or metadata.get("agent_name") or ""
        ),
        "clan": _str_or_none(metadata.get("clan")),
        "member_id": _str_or_none(metadata.get("member_id")),
        "pid": int(getattr(result, "pid", 0) or 0),
        "workspace": str(metadata.get("workspace") or ""),
        "workspace_num": int(getattr(result, "workspace_num", 0) or 0),
        "workspace_dir": str(getattr(result, "workspace_dir", "") or ""),
        "project_name": str(getattr(result, "project_name", "") or ""),
        "workflow_name": str(getattr(result, "workflow_name", "") or ""),
        "patch_name": str(getattr(result, "cl_name", "") or ""),
        "cl_name": str(getattr(result, "cl_name", "") or ""),
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "artifacts_dir": str(getattr(result, "artifacts_dir", "") or ""),
        "dedupe_key": _str_or_none(metadata.get("dedupe_key")),
        "wait_on": metadata.get("wait_on"),
        "wait_name": _str_or_none(metadata.get("wait_name")),
        "admission_logical_id": logical_id or _str_or_none(metadata.get("logical_id")),
        "admission_fingerprint": fingerprint
        or _str_or_none(metadata.get("admission_fingerprint")),
    }


def _unit_metadata(data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = data.get(UNIT_DISPATCH_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and key and isinstance(value, Mapping):
            result[key] = value
    return result


def _unit_dispatch_env(
    metadata: Mapping[str, Any],
    prompt: str,
    logical_id: str,
    fingerprint: str,
) -> dict[str, str]:
    raw_env = metadata.get("env")
    env = (
        {str(key): str(value) for key, value in raw_env.items()}
        if isinstance(raw_env, Mapping)
        else {}
    )
    env.update(
        {
            "SASE_LAUNCH_DISPATCH_FINGERPRINT": fingerprint,
            "SASE_LAUNCH_LOGICAL_ID": logical_id,
        }
    )
    env.update(
        build_chop_launch_env(
            lumberjack_name=str(metadata.get("lumberjack_name") or ""),
            chop_name=str(metadata.get("chop_name") or ""),
            prompt=prompt,
            run_id=str(metadata.get("run_id") or ""),
            admission_logical_id=logical_id,
            admission_fingerprint=fingerprint,
            proposal_index=_int_or_none(metadata.get("proposal_index")),
            proposal_id=_str_or_none(metadata.get("proposal_id")),
        )
    )
    return env


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "AXE_CHOP_SOURCE_SURFACE",
    "UNIT_DISPATCH_METADATA_KEY",
    "is_axe_chop_typed_request",
    "launch_descriptor_from_metadata",
    "make_axe_chop_agent_dispatcher",
]
