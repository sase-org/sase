"""AXE-owned dispatch metadata for durable typed chop admission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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


@dataclass(frozen=True)
class _EffectiveChopWait:
    wait_on: int | str | None
    wait_name: str | None


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

        effective_wait = _resolve_effective_wait_from_metadata(
            unit_meta,
            metadata,
            admission_root=admission_root,
        )
        prompt, prompt_error = _agent_unit_launch_prompt(
            payload,
            unit_meta,
            wait_name=effective_wait.wait_name,
        )
        if prompt_error is not None:
            return False, None, prompt_error, []
        assert prompt is not None
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
                        effective_wait=effective_wait,
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
    effective_wait: _EffectiveChopWait | None = None,
    all_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    admission_root: Path | None = None,
) -> dict[str, Any]:
    """Build the chop run launch row for a typed-admitted agent."""
    from sase.artifacts import convert_timestamp_to_artifacts_format

    if effective_wait is None and all_metadata is not None:
        effective_wait = _resolve_effective_wait_from_metadata(
            metadata,
            all_metadata,
            admission_root=admission_root,
        )
    if effective_wait is None:
        effective_wait = _EffectiveChopWait(
            metadata.get("wait_on"),
            _str_or_none(metadata.get("wait_name")),
        )

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
        "wait_on": effective_wait.wait_on,
        "wait_name": effective_wait.wait_name,
        "admission_logical_id": logical_id or _str_or_none(metadata.get("logical_id")),
        "admission_fingerprint": fingerprint
        or _str_or_none(metadata.get("admission_fingerprint")),
    }


def _resolve_effective_wait_from_metadata(
    metadata: Mapping[str, Any],
    all_metadata: Mapping[str, Mapping[str, Any]],
    *,
    admission_root: Path | None,
) -> _EffectiveChopWait:
    """Resolve an AXE chop predecessor to the nearest launched agent identity."""
    if admission_root is None:
        return _EffectiveChopWait(None, None)

    current_logical_id = _str_or_none(metadata.get("logical_id"))
    predecessor = _metadata_wait_logical_id(metadata, all_metadata)
    visited = {current_logical_id} if current_logical_id is not None else set()
    while predecessor is not None:
        if predecessor in visited:
            return _EffectiveChopWait(None, None)
        visited.add(predecessor)
        predecessor_meta = all_metadata.get(predecessor)
        identity = _unit_receipt_identity(admission_root, predecessor)
        if identity is not None:
            wait_on = _metadata_proposal_reference(predecessor_meta)
            return _EffectiveChopWait(
                wait_on if wait_on is not None else predecessor,
                identity,
            )
        if predecessor_meta is None:
            return _EffectiveChopWait(None, None)
        predecessor = _metadata_wait_logical_id(predecessor_meta, all_metadata)
    return _EffectiveChopWait(None, None)


def _metadata_wait_logical_id(
    metadata: Mapping[str, Any],
    all_metadata: Mapping[str, Mapping[str, Any]],
) -> str | None:
    direct = _str_or_none(
        metadata.get("wait_logical_id") or metadata.get("wait_on_logical_id")
    )
    if direct is not None:
        return direct

    wait_on = metadata.get("wait_on")
    if isinstance(wait_on, int) and not isinstance(wait_on, bool):
        return _logical_id_for_proposal_index(all_metadata, wait_on)
    wait_id = _str_or_none(wait_on)
    if wait_id is not None:
        return _logical_id_for_proposal_id(all_metadata, wait_id)
    return None


def _logical_id_for_proposal_index(
    all_metadata: Mapping[str, Mapping[str, Any]],
    proposal_index: int,
) -> str | None:
    for key, value in all_metadata.items():
        if _int_or_none(value.get("proposal_index")) == proposal_index:
            return _str_or_none(value.get("logical_id")) or key
    return None


def _logical_id_for_proposal_id(
    all_metadata: Mapping[str, Mapping[str, Any]],
    proposal_id: str,
) -> str | None:
    for key, value in all_metadata.items():
        if _str_or_none(value.get("proposal_id")) == proposal_id:
            return _str_or_none(value.get("logical_id")) or key
    return None


def _metadata_proposal_reference(
    metadata: Mapping[str, Any] | None,
) -> int | str | None:
    if metadata is None:
        return None
    proposal_id = _str_or_none(metadata.get("proposal_id"))
    if proposal_id is not None:
        return proposal_id
    return _int_or_none(metadata.get("proposal_index"))


def _unit_receipt_identity(admission_root: Path, logical_id: str) -> str | None:
    if not logical_id or "/" in logical_id or "\\" in logical_id:
        return None
    from sase.agent.launch_admission_store import UNITS_DIRNAME, read_json

    receipt = read_json(admission_root / UNITS_DIRNAME / f"{logical_id}.json")
    if not isinstance(receipt, Mapping):
        return None
    return _str_or_none(receipt.get("identity"))


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


def _agent_unit_launch_prompt(
    payload: AgentUnitWire,
    metadata: Mapping[str, Any],
    *,
    wait_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Rebuild an Axe dispatch prompt with its durable project routing."""
    workspace_tag = _workspace_launch_tag(metadata)
    if workspace_tag is None:
        logical_id = _str_or_none(metadata.get("logical_id")) or "unknown"
        return None, f"missing AXE chop workspace for {logical_id}"

    prompt = agent_unit_dispatch_prompt(payload)
    prompt = _qualify_prompt_with_workspace(prompt, workspace_tag)
    if wait_name is not None:
        prompt = _add_named_wait_to_prompt(prompt, wait_name)
    return prompt, None


def _workspace_launch_tag(metadata: Mapping[str, Any]) -> str | None:
    raw_workspace = _str_or_none(metadata.get("workspace"))
    if raw_workspace is None:
        return None

    workspace = raw_workspace.strip().lstrip("#").strip()
    if not workspace:
        return None

    tag = f"#{workspace}"
    try:
        from sase.agent.launch_cwd_common import resolve_known_project_vcs_launch_ref

        known_ref = resolve_known_project_vcs_launch_ref(tag)
    except Exception:
        known_ref = None
    if known_ref is not None:
        workflow_type = _str_or_none(getattr(known_ref, "workflow_type", None))
        ref = _str_or_none(getattr(known_ref, "ref", None))
        if workflow_type is not None and ref is not None:
            return f"#{workflow_type}:{ref}"
    return tag


def _qualify_prompt_with_workspace(prompt: str, workspace_tag: str) -> str:
    from sase.xprompt._parsing_vcs_tags import (
        extract_vcs_workflow_tag,
        find_vcs_workflow_tag_prepend_offset,
        replace_vcs_workflow_tags,
    )

    if extract_vcs_workflow_tag(prompt) is not None:
        return replace_vcs_workflow_tags(prompt, workspace_tag)

    offset = find_vcs_workflow_tag_prepend_offset(prompt)
    return f"{prompt[:offset]}{workspace_tag}\n{prompt[offset:]}"


def _add_named_wait_to_prompt(prompt: str, wait_name: str) -> str:
    clean_wait_name = wait_name.strip()
    if not clean_wait_name or "\n" in clean_wait_name or "\r" in clean_wait_name:
        return prompt
    lines = prompt.splitlines()
    if not lines:
        return f"%wait:{clean_wait_name}\n"
    insert_at = _after_workspace_line_index(lines)
    lines.insert(insert_at, f"%wait:{clean_wait_name}")
    suffix = "\n" if prompt.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _after_workspace_line_index(lines: list[str]) -> int:
    from sase.xprompt._parsing_vcs_tags import extract_vcs_workflow_tag

    for index, line in enumerate(lines):
        if extract_vcs_workflow_tag(line) is not None:
            return index + 1
    return 0


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
