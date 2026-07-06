"""Default agent artifact synthesis from per-run metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sase.core.agent_artifact_explicit import (
    list_indexed_agent_artifacts,
    store_default_agent_artifact,
)
from sase.core.commit_finalizer_prompt_artifacts import (
    is_commit_finalizer_followup_prompt,
)
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

_PROMPT_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
)
_PROMPT_VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".webm"})
_PROMPT_MEDIA_SUFFIX_PATTERN = "|".join(
    re.escape(suffix.lstrip("."))
    for suffix in sorted(
        _PROMPT_IMAGE_SUFFIXES | _PROMPT_VIDEO_SUFFIXES,
        key=len,
        reverse=True,
    )
)
_PROMPT_MEDIA_PATH_RE = re.compile(
    rf"""(?P<path>(?:~|/|\.{{1,2}}/|[A-Za-z0-9_.-]+)[^\s"'`<>]*?\.(?:{_PROMPT_MEDIA_SUFFIX_PATTERN}))""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _MediaCandidate:
    path: str
    kind: AgentArtifactKind
    label_fallback: str
    ordinal: str


def synthesize_default_agent_artifacts(
    agent_artifacts_dir: Path | str,
) -> list[AgentArtifact]:
    """Synthesize chat/plan/media artifacts from existing run metadata.

    When ``done.json`` has ``default_artifacts_persisted: True`` the
    generated-media branches are skipped — those rows now live in the
    persistent JSONL index. Legacy agents without that marker still get the
    on-the-fly media synthesis as a best-effort fallback.
    """

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
    default_artifacts_persisted = bool(done.get("default_artifacts_persisted"))

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

    if not default_artifacts_persisted:
        for candidate in _media_candidates(
            artifacts_dir,
            image_paths=coerce_str_list(done.get("image_paths")),
            video_paths=coerce_str_list(done.get("video_paths")),
            workspace_dir=workspace_dir,
        ):
            artifacts.append(
                _default_artifact(
                    association,
                    label=label_for_path(
                        candidate.path, fallback=candidate.label_fallback
                    ),
                    kind=candidate.kind,
                    path=candidate.path,
                    ordinal=candidate.ordinal,
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


def persist_default_agent_artifacts(
    agent_artifacts_dir: Path | str,
    *,
    image_paths: list[str] | None = None,
    video_paths: list[str] | None = None,
    workspace_dir: str | None = None,
    artifacts_root: Path | str | None = None,
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Copy auto-discovered media artifacts into the persistent global store.

    Called by the agent finalization path while the workspace files still
    exist. Combines explicit ``image_paths`` and ``video_paths`` (from
    ``done.json``) with prompt media discovery, deduplicates by resolved path,
    silently skips paths that don't exist, and writes a row to the JSONL index
    for each persisted file.

    Idempotent: re-running over the same workspace yields the same set of
    persisted artifacts and the same index rows.
    """

    artifacts_dir = Path(agent_artifacts_dir).expanduser()

    persisted: list[AgentArtifact] = []
    for candidate in _media_candidates(
        artifacts_dir,
        image_paths=image_paths or [],
        video_paths=video_paths or [],
        workspace_dir=workspace_dir,
    ):
        artifact = store_default_agent_artifact(
            candidate.path,
            artifacts_dir,
            label=label_for_path(candidate.path, fallback=candidate.label_fallback),
            kind=candidate.kind,
            artifacts_root=artifacts_root,
            index_path=index_path,
            workspace_dir=workspace_dir,
        )
        if artifact is not None:
            persisted.append(artifact)
    return persisted


def _media_candidates(
    artifacts_dir: Path,
    *,
    image_paths: list[str],
    video_paths: list[str],
    workspace_dir: str | None,
) -> list[_MediaCandidate]:
    candidates: list[_MediaCandidate] = []
    candidates.extend(
        _MediaCandidate(
            path=path,
            kind="image",
            label_fallback="Image",
            ordinal=f"image-{index}",
        )
        for index, path in enumerate(image_paths)
        if path
    )
    candidates.extend(
        _MediaCandidate(
            path=path,
            kind="file",
            label_fallback="Video",
            ordinal=f"video-{index}",
        )
        for index, path in enumerate(video_paths)
        if path
    )
    candidates.extend(
        _discover_prompt_media_candidates(
            artifacts_dir,
            workspace_dir=workspace_dir,
        )
    )
    return _dedupe_media_candidates(candidates)


def list_agent_artifacts(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Return default plus explicit artifacts for one agent in display order."""

    defaults = synthesize_default_agent_artifacts(agent_artifacts_dir)
    indexed = list_indexed_agent_artifacts(
        agent_artifacts_dir,
        index_path=index_path,
    )
    non_chat_plan_defaults = [
        artifact for artifact in defaults if artifact.kind not in {"chat", "plan"}
    ]
    chat_and_plans = [
        artifact for artifact in defaults if artifact.kind in {"chat", "plan"}
    ]
    return dedupe_artifacts(
        _dedupe_plan_artifacts([*chat_and_plans, *indexed, *non_chat_plan_defaults])
    )


def _discover_prompt_media_candidates(
    artifacts_dir: Path,
    *,
    workspace_dir: str | None,
) -> list[_MediaCandidate]:
    candidates: list[_MediaCandidate] = []
    seen: set[str] = set()
    prompt_indexes = {"image": 0, "video": 0}
    for prompt_path in _prompt_artifact_files(artifacts_dir):
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _PROMPT_MEDIA_PATH_RE.finditer(prompt):
            media_path = _resolve_prompt_media_path(
                match.group("path"),
                workspace_dir=workspace_dir,
            )
            if media_path is None:
                continue
            key = path_key(media_path)
            if key in seen:
                continue
            seen.add(key)
            kind, label_fallback, ordinal_prefix = _media_candidate_attributes(
                media_path
            )
            index = prompt_indexes[ordinal_prefix]
            prompt_indexes[ordinal_prefix] = index + 1
            candidates.append(
                _MediaCandidate(
                    path=media_path,
                    kind=kind,
                    label_fallback=label_fallback,
                    ordinal=f"prompt-{ordinal_prefix}-{index}",
                )
            )
    return candidates


def _prompt_artifact_files(artifacts_dir: Path) -> list[Path]:
    prompt_files: list[Path] = []
    raw_prompt = artifacts_dir / "raw_xprompt.md"
    if raw_prompt.is_file():
        prompt_files.append(raw_prompt)
    try:
        step_prompts = sorted(
            path
            for path in artifacts_dir.glob("*_prompt.md")
            if path.is_file()
            and path != raw_prompt
            and not is_commit_finalizer_followup_prompt(path.name)
        )
    except OSError:
        step_prompts = []
    prompt_files.extend(step_prompts)
    return prompt_files


def _resolve_prompt_media_path(
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


def _media_candidate_attributes(
    path: str,
) -> tuple[AgentArtifactKind, str, str]:
    suffix = Path(path).suffix.lower()
    if suffix in _PROMPT_VIDEO_SUFFIXES:
        return "file", "Video", "video"
    return "image", "Image", "image"


def _dedupe_media_candidates(
    candidates: list[_MediaCandidate],
) -> list[_MediaCandidate]:
    deduped: list[_MediaCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = path_key(candidate.path)
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


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
