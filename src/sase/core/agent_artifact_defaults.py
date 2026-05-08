"""Default agent artifact synthesis from per-run metadata."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_explicit import list_explicit_agent_artifacts
from sase.core.agent_artifact_helpers import (
    artifact_id,
    association_from_metadata,
    coerce_str_list,
    dedupe_artifacts,
    file_created_at,
    filter_duplicate_home_plan_paths,
    first_str,
    label_for_path,
    path_key,
    read_json_object,
    read_markdown_pdf_source_paths,
    unique_values,
)
from sase.core.agent_artifact_types import (
    AgentArtifact,
    AgentArtifactAssociation,
    AgentArtifactKind,
)


def synthesize_default_agent_artifacts(
    agent_artifacts_dir: Path | str,
) -> list[AgentArtifact]:
    """Synthesize chat/plan/image artifacts from existing run metadata."""

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    done = read_json_object(artifacts_dir / "done.json")
    agent_meta = read_json_object(artifacts_dir / "agent_meta.json")
    plan_marker = read_json_object(artifacts_dir / "plan_path.json")
    association = association_from_metadata(
        artifacts_dir, done=done, agent_meta=agent_meta
    )
    workspace_dir = first_str(done.get("workspace_dir"))
    markdown_pdf_sources = read_markdown_pdf_source_paths(artifacts_dir)

    artifacts: list[AgentArtifact] = []

    chat_path = first_str(done.get("response_path"), agent_meta.get("chat_path"))
    if chat_path:
        artifacts.append(
            _default_artifact(
                association,
                label="Chat transcript",
                kind="chat",
                path=chat_path,
                ordinal="chat",
                workspace_dir=workspace_dir,
            )
        )

    plan_paths = filter_duplicate_home_plan_paths(
        unique_values(
            done.get("plan_path"),
            agent_meta.get("plan_path"),
            agent_meta.get("sdd_plan_path"),
            plan_marker.get("plan_path"),
        ),
        workspace_dir=workspace_dir,
    )
    for index, plan_path in enumerate(plan_paths):
        artifacts.append(
            _default_artifact(
                association,
                label=label_for_path(plan_path, fallback="Plan"),
                kind="plan",
                path=plan_path,
                ordinal=f"plan-{index}",
                workspace_dir=workspace_dir,
            )
        )

    for index, image_path in enumerate(coerce_str_list(done.get("image_paths"))):
        artifacts.append(
            _default_artifact(
                association,
                label=label_for_path(image_path, fallback="Image"),
                kind="image",
                path=image_path,
                ordinal=f"image-{index}",
                workspace_dir=workspace_dir,
            )
        )

    for index, pdf_path in enumerate(coerce_str_list(done.get("markdown_pdf_paths"))):
        source_path = markdown_pdf_sources.get(path_key(pdf_path))
        artifacts.append(
            _default_artifact(
                association,
                label=label_for_path(source_path or pdf_path, fallback="PDF"),
                kind="pdf",
                path=pdf_path,
                ordinal=f"pdf-{index}",
                source_path=source_path,
                workspace_dir=workspace_dir,
            )
        )

    return dedupe_artifacts(artifacts)


def list_agent_artifacts(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Return default plus explicit artifacts for one agent in display order."""

    defaults = synthesize_default_agent_artifacts(agent_artifacts_dir)
    explicit = list_explicit_agent_artifacts(
        agent_artifacts_dir,
        index_path=index_path,
    )
    images_and_generated = [
        artifact for artifact in defaults if artifact.kind not in {"chat", "plan"}
    ]
    chat_and_plans = [
        artifact for artifact in defaults if artifact.kind in {"chat", "plan"}
    ]
    return dedupe_artifacts([*chat_and_plans, *explicit, *images_and_generated])


def _default_artifact(
    association: AgentArtifactAssociation,
    *,
    label: str,
    kind: AgentArtifactKind,
    path: str,
    ordinal: str,
    source_path: str | None = None,
    workspace_dir: str | None = None,
) -> AgentArtifact:
    return AgentArtifact(
        id=artifact_id(f"default-{ordinal}", association, path, label),
        label=label,
        kind=kind,
        path=path,
        source_path=source_path,
        workspace_dir=workspace_dir,
        created_at=file_created_at(path),
        agent_artifacts_dir=association.agent_artifacts_dir,
        project=association.project,
        workflow=association.workflow,
        raw_timestamp=association.raw_timestamp,
        agent_name=association.agent_name,
        explicit=False,
    )
