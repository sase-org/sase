"""AXE-owned dispatch metadata for durable typed chop admission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from sase.agent.launch_admission_runtime import UnitDispatcher
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import agent_unit_dispatch_prompt, safe_launch_name
from sase.core.agent_launch_wire import AgentUnitWire, LaunchUnitWire

from .chop_agents import build_chop_launch_env

# ``launch_admission_store`` and ``monitor.transaction`` are imported lazily
# below, not at module scope: this module is reached from
# ``sase.axe.__init__`` via the chop-lifecycle typed-admission path, and
# ``launch_admission_store`` imports ``sase.monitor``, whose package init
# imports back into ``sase.axe`` — a top-level import here would cycle.

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
    bundle_dir: Path | None = None,
) -> UnitDispatcher | None:
    """Build an agent dispatcher that preserves chop ownership per logical unit."""
    metadata = _unit_metadata(data)
    if not metadata:
        return None
    admission_root: Path | None = None
    if bundle_dir is not None:
        from sase.agent.launch_admission_store import admission_dir

        admission_root = admission_dir(bundle_dir)

    def _dispatch(
        unit: LaunchUnitWire,
        fingerprint: str,
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        if not isinstance(unit.payload, AgentUnitWire):
            return False, None, "not_an_agent_unit", []
        unit_meta = metadata.get(unit.logical_id)
        if unit_meta is None:
            return False, None, f"missing AXE chop metadata for {unit.logical_id}", []

        payload = unit.payload
        clan = _str_or_none(unit_meta.get("clan"))
        if clan is not None and admission_root is not None:
            payload = _resolve_clan_dispatch_payload(
                payload,
                admission_root=admission_root,
                clan=clan,
                unit_meta=unit_meta,
            )

        prompt = agent_unit_dispatch_prompt(payload)
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


def _resolve_clan_dispatch_payload(
    payload: AgentUnitWire,
    *,
    admission_root: Path,
    clan: str,
    unit_meta: Mapping[str, Any],
) -> AgentUnitWire:
    """Promote the first eligible clan member to declarer, durably and once.

    Skipped and condition-errored units never reach dispatch, so whichever
    eligible member gets here first for an undeclared clan claims the
    declarer role even when the statically planned declarer was skipped. The
    claim is recorded on disk before the launch attempt runs so a failed
    launch cannot let a later member declare the same clan a second time, and
    so a detached coordinator resuming in a fresh process still sees it.
    """
    marker = _clan_declared_marker_path(admission_root, clan)
    if marker.exists():
        member_id = _str_or_none(unit_meta.get("member_id")) or payload.identity
        return replace(
            payload,
            identity=member_id,
            identity_explicit=True,
            clan=clan,
            clan_declared=False,
            clan_tribe=None,
            clan_summary=None,
            clan_summary_script=None,
        )
    full_name = _str_or_none(unit_meta.get("agent_name")) or payload.identity
    tribe = _str_or_none(unit_meta.get("clan_tribe")) or "chop"
    summary = _str_or_none(unit_meta.get("clan_summary"))
    from sase.monitor.transaction import write_json_marker_atomic

    write_json_marker_atomic(
        marker,
        {"clan": clan, "logical_id": str(unit_meta.get("logical_id") or "")},
    )
    return replace(
        payload,
        identity=full_name,
        identity_explicit=True,
        clan=clan,
        clan_declared=True,
        clan_tribe=tribe,
        clan_summary=summary,
        clan_summary_script=None,
    )


def _clan_declared_marker_path(admission_root: Path, clan: str) -> Path:
    from sase.agent.launch_admission_store import UNITS_DIRNAME

    return (
        admission_root / UNITS_DIRNAME / f"clan-declared-{safe_launch_name(clan)}.json"
    )


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
