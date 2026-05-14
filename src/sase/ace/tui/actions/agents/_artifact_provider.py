"""ACE agent artifact/detail provider helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from sase.core.agent_artifact_facade import (
    AGENT_ARTIFACT_KINDS,
    AgentArtifact,
    AgentArtifactKind,
    infer_artifact_kind,
    list_agent_artifacts,
)
from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    AgentArtifactAssociation,
    AgentDetailRead,
    agent_detail_from_dict,
)

from ...data_providers import agent_row_handle
from ...models.agent import Agent
from ...provider_contract import (
    AceDetailRequest,
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceRowHandle,
    AceSnapshot,
    SelectionGeneration,
    make_snapshot,
    trace_provider_snapshot,
)


@dataclass(frozen=True)
class _AceAgentArtifactPage:
    """Artifacts associated with one selected agent row."""

    artifacts: list[AgentArtifact] = field(default_factory=list)
    request: AceDetailRequest | None = None
    shared_snapshot: AceSnapshot[AgentArtifact] | None = None
    bounded: bool = False
    truncated: bool = False


def read_agent_artifacts_for_tui(
    agent: Agent,
    *,
    selection_generation: SelectionGeneration | None = None,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[_AceAgentArtifactPage]:
    """Return selected-agent artifact associations through daemon/detail reads."""

    row_handle = agent_row_handle(agent)
    generation = selection_generation or SelectionGeneration()
    request = generation.request(row_handle)
    parsed = _parse_agent_handle(row_handle)
    if parsed is None:
        return DaemonReadResult(
            value=_direct_agent_artifact_page(
                agent,
                request=request,
                provider_source="direct",
                prefers_daemon=False,
                fallback_reason="missing_agent_handle",
                fallback_message="agent row does not have a daemon detail handle",
            ),
            surface="ace_artifact_detail",
            used_daemon=False,
            fallback_reason="missing_agent_handle",
            fallback_message="agent row does not have a daemon detail handle",
        )
    project_id, agent_id = parsed

    result = read_or_fallback(
        "ace_artifact_detail",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_agent_artifact_page(
            daemon,
            agent,
            project_id=project_id,
            agent_id=agent_id,
            request=request,
        ),
        direct_loader=lambda: _direct_agent_artifact_page(
            agent,
            request=request,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
        ),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=_agent_artifact_page_with_shared_metadata(
            result.value,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=(
                result.value.shared_snapshot.snapshot_id
                if result.value.shared_snapshot is not None
                else None
            ),
            full_reload=True,
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def _daemon_agent_artifact_page(
    client: LocalDaemonClient,
    agent: Agent,
    *,
    project_id: str,
    agent_id: str,
    request: AceDetailRequest,
) -> _AceAgentArtifactPage:
    detail = agent_detail_from_dict(
        client.agent_detail(project_id=project_id, agent_id=agent_id)
    )
    bounded = detail.bounded
    page = _AceAgentArtifactPage(
        artifacts=[
            _artifact_from_daemon_association(association, agent, project_id=project_id)
            for association in detail.artifacts
        ],
        request=request,
        bounded=bounded is not None,
        truncated=bool(bounded.truncated) if bounded is not None else False,
    )
    return _agent_artifact_page_from_detail(
        page,
        detail=detail,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
    )


def _direct_agent_artifact_page(
    agent: Agent,
    *,
    request: AceDetailRequest,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
) -> _AceAgentArtifactPage:
    try:
        artifacts_dir = agent.get_artifacts_dir()
        artifacts = [] if artifacts_dir is None else list_agent_artifacts(artifacts_dir)
    except Exception:
        artifacts = []
    return _agent_artifact_page_with_shared_metadata(
        _AceAgentArtifactPage(artifacts=artifacts, request=request),
        provider_source=provider_source,
        prefers_daemon=prefers_daemon,
        fallback_reason=fallback_reason,
        fallback_message=fallback_message,
        snapshot_id=None,
        full_reload=True,
    )


def _agent_artifact_page_from_detail(
    page: _AceAgentArtifactPage,
    *,
    detail: AgentDetailRead,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
) -> _AceAgentArtifactPage:
    return _agent_artifact_page_with_shared_metadata(
        page,
        provider_source=provider_source,
        prefers_daemon=prefers_daemon,
        fallback_reason=fallback_reason,
        fallback_message=fallback_message,
        snapshot_id=detail.snapshot.snapshot_id,
        full_reload=False,
    )


def _agent_artifact_page_with_shared_metadata(
    page: _AceAgentArtifactPage,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    full_reload: bool,
) -> _AceAgentArtifactPage:
    shared_snapshot = make_snapshot(
        surface="agent_artifacts",
        rows=page.artifacts,
        row_handles=[_artifact_row_handle(artifact) for artifact in page.artifacts],
        provider=AceProviderInfo(
            identity=f"agent_artifacts:{provider_source}",
            surface="agent_artifacts",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                lazy_details=provider_source == "daemon",
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=1,
        metadata={
            "bounded": page.bounded,
            "truncated": page.truncated,
            "selection_generation": (
                page.request.selection_generation if page.request is not None else None
            ),
        },
        full_reload=full_reload,
    )
    trace_provider_snapshot(shared_snapshot)
    return _AceAgentArtifactPage(
        artifacts=page.artifacts,
        request=page.request,
        shared_snapshot=shared_snapshot,
        bounded=page.bounded,
        truncated=page.truncated,
    )


def _artifact_row_handle(artifact: AgentArtifact) -> AceRowHandle:
    """Return a stable row handle for an agent artifact association."""

    stable_id = f"agent_artifact:{artifact.id}"
    return AceRowHandle(
        surface="agent_artifacts",
        stable_id=stable_id,
        daemon_handle=stable_id,
        local_identity=artifact.path,
    )


def _artifact_from_daemon_association(
    association: AgentArtifactAssociation,
    agent: Agent,
    *,
    project_id: str,
) -> AgentArtifact:
    path = association.artifact_path
    kind = association.artifact_kind
    if kind in AGENT_ARTIFACT_KINDS:
        artifact_kind = cast(AgentArtifactKind, kind)
    else:
        artifact_kind = infer_artifact_kind(path)
    label = association.display_name or Path(path).name or path
    artifacts_dir = agent.get_artifacts_dir()
    return AgentArtifact(
        id=path,
        label=label,
        kind=artifact_kind,
        path=path,
        agent_artifacts_dir=artifacts_dir,
        project=project_id,
        workflow=agent.workflow,
        raw_timestamp=agent.raw_suffix,
        agent_name=getattr(agent, "agent_name", None),
        explicit=association.role == "explicit",
    )


def _parse_agent_handle(handle: AceRowHandle) -> tuple[str, str] | None:
    daemon_handle = handle.daemon_handle or handle.stable_id
    parts = daemon_handle.split(":", 2)
    if len(parts) != 3 or parts[0] != "agent" or not parts[1] or not parts[2]:
        return None
    return parts[1], daemon_handle


__all__ = [
    "read_agent_artifacts_for_tui",
]
