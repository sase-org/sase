"""Shared helpers for file-hook config loading and event matching tests."""

from __future__ import annotations

from sase.config.file_hooks import (
    FileHookConfig,
    FileHookEvent,
    FileHookFilters,
)
from sase.config.layers import ConfigLayer
from sase.artifact_providers.registry import (
    ArtifactProviderProvenance,
    ArtifactProviderRegistry,
    FileHookProviderRecord,
)


def _layer(
    name: str,
    hooks: object,
    *,
    strategy: str = "concatenate",
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=None,
        exists=True,
        list_strategy=strategy,
        data={"file_hooks": hooks},
    )


def _hook(
    *,
    projects: tuple[str, ...] | None = None,
    sidecars: tuple[str, ...] | None = None,
    path_globs: tuple[str, ...] | None = None,
    agent_name_globs: tuple[str, ...] | None = None,
    ops: tuple[str, ...] | None = None,
    causes: tuple[str, ...] | None = None,
    producers: tuple[str, ...] | None = None,
) -> FileHookConfig:
    return FileHookConfig(
        name="test-hook",
        description=None,
        command="check",
        timeout_seconds=120,
        filters=FileHookFilters(
            projects=projects,
            sidecars=sidecars,
            path_globs=path_globs,
            agent_name_globs=agent_name_globs,
            ops=ops,  # type: ignore[arg-type]
            causes=causes,
            producers=producers,  # type: ignore[arg-type]
        ),
    )


def _event(
    path: str,
    *,
    project: str = "sase",
    sidecar: str | None = "research",
    op: str = "ADD",
    agent: str | None = None,
    cause: str = "user",
) -> FileHookEvent:
    return FileHookEvent(
        project=project,
        repo_kind=f"sidecar:{sidecar}" if sidecar else "primary",
        sidecar_role=sidecar,
        rel_path=path,
        op=op,  # type: ignore[arg-type]
        cause=cause,
        agent_name=agent,
    )


def _registry_with_file_hook_provider() -> ArtifactProviderRegistry:
    provenance = ArtifactProviderProvenance(
        group="sase_file_hooks",
        name="research",
        package="sase-research-artifacts",
        version="1.0.0",
    )
    return ArtifactProviderRegistry(
        ref_providers=(),
        file_hook_providers=(
            FileHookProviderRecord(
                provider_id="research-highlights",
                template={
                    "description": "Render research highlights.",
                    "filters": {
                        "sidecars": ["research"],
                        "path_globs": ["reports/**/*.md", "!reports/drafts/**"],
                    },
                    "timeout": "30s",
                },
                required_fields=("command",),
                provenance=provenance,
            ),
        ),
        entry_kinds=(),
        diagnostics=(),
    )
