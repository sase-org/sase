"""Default agent artifact synthesis from per-run metadata."""

from __future__ import annotations

import re
from pathlib import Path

from sase.core.agent_artifact_explicit import list_explicit_agent_artifacts
from sase.core.agent_artifact_helpers import (
    artifact_id,
    association_from_metadata,
    coerce_str_list,
    dedupe_artifacts,
    file_created_at,
    first_str,
    label_for_path,
    path_key,
    read_json_object,
    read_markdown_pdf_source_paths,
    selected_plan_path,
)
from sase.core.agent_artifact_types import (
    AgentArtifact,
    AgentArtifactAssociation,
    AgentArtifactKind,
)

_IMAGE_PATH_RE = re.compile(
    r"""(?P<path>(?:~|/|\.{1,2}/|[A-Za-z0-9_.-]+)[^\s"'`<>]*?\.(?:png|jpe?g|gif|webp|bmp|tiff?))""",
    re.IGNORECASE,
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
    workspace_dir = first_str(
        done.get("workspace_dir"), agent_meta.get("workspace_dir")
    )
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

    plan_path = selected_plan_path(
        done=done,
        agent_meta=agent_meta,
        plan_marker=plan_marker,
    )
    if plan_path:
        artifacts.append(
            _default_artifact(
                association,
                label=label_for_path(plan_path, fallback="Plan"),
                kind="plan",
                path=plan_path,
                ordinal="plan",
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

    for index, image_path in enumerate(
        _discover_prompt_image_paths(artifacts_dir, workspace_dir=workspace_dir)
    ):
        artifacts.append(
            _default_artifact(
                association,
                label=label_for_path(image_path, fallback="Image"),
                kind="image",
                path=image_path,
                ordinal=f"prompt-image-{index}",
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
    return dedupe_artifacts(
        _dedupe_plan_artifacts([*chat_and_plans, *explicit, *images_and_generated])
    )


def _discover_prompt_image_paths(
    artifacts_dir: Path,
    *,
    workspace_dir: str | None,
) -> list[str]:
    image_paths: list[str] = []
    seen: set[str] = set()
    for prompt_path in _prompt_artifact_files(artifacts_dir):
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _IMAGE_PATH_RE.finditer(prompt):
            image_path = _resolve_prompt_image_path(
                match.group("path"),
                workspace_dir=workspace_dir,
            )
            if image_path is None:
                continue
            key = path_key(image_path)
            if key in seen:
                continue
            seen.add(key)
            image_paths.append(image_path)
    return image_paths


def _prompt_artifact_files(artifacts_dir: Path) -> list[Path]:
    prompt_files: list[Path] = []
    raw_prompt = artifacts_dir / "raw_xprompt.md"
    if raw_prompt.is_file():
        prompt_files.append(raw_prompt)
    try:
        step_prompts = sorted(
            path
            for path in artifacts_dir.glob("*_prompt.md")
            if path.is_file() and path != raw_prompt
        )
    except OSError:
        step_prompts = []
    prompt_files.extend(step_prompts)
    return prompt_files


def _resolve_prompt_image_path(
    path: str,
    *,
    workspace_dir: str | None,
) -> str | None:
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        candidate = expanded
    elif workspace_dir:
        candidate = Path(workspace_dir).expanduser() / expanded
    else:
        return None

    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return None
    if not resolved.is_file():
        return None
    return str(resolved)


def _dedupe_plan_artifacts(artifacts: list[AgentArtifact]) -> list[AgentArtifact]:
    plan_seen = False
    deduped: list[AgentArtifact] = []
    for artifact in artifacts:
        if artifact.kind == "plan":
            if plan_seen:
                continue
            plan_seen = True
        deduped.append(artifact)
    return deduped


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
