"""Default artifact-file synthesis from per-run metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.core.artifact_file_explicit import (
    list_indexed_artifact_files,
    store_default_artifact_file,
)
from sase.core.commit_finalizer_prompt_artifacts import (
    is_commit_finalizer_followup_prompt,
)
from sase.core.artifact_file_helpers import (
    artifact_file_id,
    artifact_file_association_from_metadata,
    artifact_file_mime_type,
    coerce_str_list,
    dedupe_artifact_files,
    file_created_at,
    first_str,
    hash_file,
    label_for_path,
    path_key,
    read_json_object,
    read_markdown_pdf_source_paths,
    selected_plan_path,
)
from sase.core.artifact_file_types import (
    ArtifactFile,
    ArtifactFileAssociation,
    ArtifactFileKind,
)

if TYPE_CHECKING:
    from sase.core.artifact_capture_policy import (
        CaptureDecision,
        CaptureLimits,
        VcsProbe,
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
    kind: ArtifactFileKind
    label_fallback: str
    ordinal: str
    origin: Literal["changed", "mentioned"]


def synthesize_default_artifact_files(
    agent_artifacts_dir: Path | str,
) -> list[ArtifactFile]:
    """Synthesize chat, plan, and media artifact files from run metadata.

    When ``done.json`` has ``default_artifacts_persisted: True`` the
    generated-media branches are skipped — those rows now live in the
    persistent JSONL index. Legacy agents without that marker still get the
    on-the-fly media synthesis as a best-effort fallback.
    """

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    done = read_json_object(artifacts_dir / "done.json")
    agent_meta = read_json_object(artifacts_dir / "agent_meta.json")
    plan_marker = read_json_object(artifacts_dir / "plan_path.json")
    association = artifact_file_association_from_metadata(
        artifacts_dir, done=done, agent_meta=agent_meta
    )
    workspace_dir = first_str(
        done.get("workspace_dir"), agent_meta.get("workspace_dir")
    )
    markdown_pdf_sources = read_markdown_pdf_source_paths(artifacts_dir)
    default_artifact_files_persisted = bool(done.get("default_artifacts_persisted"))

    artifact_files: list[ArtifactFile] = []

    chat_path = first_str(done.get("response_path"), agent_meta.get("chat_path"))
    if chat_path:
        artifact_files.append(
            _default_artifact_file(
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
        artifact_files.append(
            _default_artifact_file(
                association,
                label=label_for_path(plan_path, fallback="Plan"),
                kind="plan",
                path=plan_path,
                ordinal="plan",
                workspace_dir=workspace_dir,
            )
        )

    if not default_artifact_files_persisted:
        for candidate in _media_candidates(
            artifacts_dir,
            image_paths=coerce_str_list(done.get("image_paths")),
            video_paths=coerce_str_list(done.get("video_paths")),
            workspace_dir=workspace_dir,
        ):
            artifact_files.append(
                _default_artifact_file(
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
        artifact_files.append(
            _default_artifact_file(
                association,
                label=label_for_path(source_path or pdf_path, fallback="PDF"),
                kind="pdf",
                path=pdf_path,
                ordinal=f"pdf-{index}",
                source_path=source_path,
                workspace_dir=workspace_dir,
            )
        )

    return dedupe_artifact_files(artifact_files)


def persist_default_artifact_files(
    agent_artifacts_dir: Path | str,
    *,
    image_paths: list[str] | None = None,
    video_paths: list[str] | None = None,
    workspace_dir: str | None = None,
    project: str | None = None,
    workspace_num: int | None = None,
    artifact_files_root: Path | str | None = None,
    index_path: Path | str | None = None,
    print_summary: bool = False,
    capture_limits: CaptureLimits | None = None,
    probe: VcsProbe | None = None,
) -> list[ArtifactFile]:
    """Persist auto-discovered media artifact files into the global store.

    Called by the agent finalization path while the workspace files still
    exist. Combines explicit ``image_paths`` and ``video_paths`` (from
    ``done.json``) with prompt media discovery, deduplicates by resolved path,
    silently skips paths that don't exist, applies the capture policy when VCS
    context is available, and writes a row to the JSONL index for each
    persisted or VCS-backed file.

    Idempotent: re-running over the same workspace yields the same set of
    persisted artifact files and the same index rows.
    """

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    association = artifact_file_association_from_metadata(artifacts_dir)
    candidates = _existing_media_candidates(
        _media_candidates(
            artifacts_dir,
            image_paths=image_paths or [],
            video_paths=video_paths or [],
            workspace_dir=workspace_dir,
        )
    )
    decisions = _capture_decisions(
        candidates,
        artifacts_dir=artifacts_dir,
        association_project=association.project,
        project=project,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        capture_limits=capture_limits,
        probe=probe,
    )

    persisted: list[ArtifactFile] = []
    stored_count = 0
    referenced_count = 0
    skipped_count = 0
    cap_fired = False
    for candidate, decision in zip(candidates, decisions, strict=True):
        if decision.outcome == "skip":
            skipped_count += 1
            cap_fired = cap_fired or decision.reason == "capture_cap"
            continue

        artifact_file = store_default_artifact_file(
            candidate.path,
            artifacts_dir,
            label=label_for_path(candidate.path, fallback=candidate.label_fallback),
            kind=candidate.kind,
            artifact_files_root=artifact_files_root,
            index_path=index_path,
            workspace_dir=workspace_dir,
            vcs_repo=decision.vcs_repo,
            vcs_sha=decision.vcs_sha,
            vcs_relpath=decision.vcs_relpath,
            sha256=candidate.sha256,
            size_bytes=candidate.size_bytes,
            mime_type=candidate.mime_type,
        )
        if artifact_file is not None:
            persisted.append(artifact_file)
            if decision.outcome == "reference":
                referenced_count += 1
            else:
                stored_count += 1
    if print_summary:
        print(
            "[artifacts] default capture: "
            f"stored={stored_count} referenced={referenced_count} "
            f"skipped={skipped_count} cap_fired={str(cap_fired).lower()}"
        )
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
            origin="changed",
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
            origin="changed",
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


def list_artifact_files(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[ArtifactFile]:
    """Return default plus explicit artifact files in display order."""

    defaults = synthesize_default_artifact_files(agent_artifacts_dir)
    indexed = list_indexed_artifact_files(
        agent_artifacts_dir,
        index_path=index_path,
    )
    non_chat_plan_defaults = [
        artifact_file
        for artifact_file in defaults
        if artifact_file.kind not in {"chat", "plan"}
    ]
    chat_and_plans = [
        artifact_file
        for artifact_file in defaults
        if artifact_file.kind in {"chat", "plan"}
    ]
    return dedupe_artifact_files(
        _dedupe_plan_artifact_files(
            [*chat_and_plans, *indexed, *non_chat_plan_defaults]
        )
    )


def _discover_prompt_media_candidates(
    artifacts_dir: Path,
    *,
    workspace_dir: str | None,
) -> list[_MediaCandidate]:
    candidates: list[_MediaCandidate] = []
    seen: set[str] = set()
    prompt_indexes = {"image": 0, "video": 0}
    for prompt_path in _prompt_source_files(artifacts_dir):
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
                    origin="mentioned",
                )
            )
    return candidates


@dataclass(frozen=True)
class _HashedMediaCandidate:
    path: str
    kind: ArtifactFileKind
    label_fallback: str
    origin: Literal["changed", "mentioned"]
    sha256: str
    size_bytes: int
    mime_type: str


def _existing_media_candidates(
    candidates: list[_MediaCandidate],
) -> list[_HashedMediaCandidate]:
    hashed: list[_HashedMediaCandidate] = []
    for candidate in candidates:
        source = Path(candidate.path).expanduser()
        if not source.is_file():
            continue
        try:
            sha256 = hash_file(source)
            size_bytes = source.stat().st_size
        except OSError:
            continue
        hashed.append(
            _HashedMediaCandidate(
                path=candidate.path,
                kind=candidate.kind,
                label_fallback=candidate.label_fallback,
                origin=candidate.origin,
                sha256=sha256,
                size_bytes=size_bytes,
                mime_type=artifact_file_mime_type(source),
            )
        )
    return hashed


def _capture_decisions(
    candidates: list[_HashedMediaCandidate],
    *,
    artifacts_dir: Path,
    association_project: str | None,
    project: str | None,
    workspace_dir: str | None,
    workspace_num: int | None,
    capture_limits: CaptureLimits | None,
    probe: VcsProbe | None,
) -> list[CaptureDecision]:
    from sase.config import (
        get_artifact_capture_max_history_scan,
        get_artifact_capture_max_stored_per_agent,
    )
    from sase.core.artifact_capture_policy import (
        CaptureCandidate,
        CaptureDecision,
        CaptureLimits,
        GitVcsProbe,
        VcsProbe,
        decide_captures,
    )

    policy_project = project or association_project
    if not candidates:
        return []
    if not workspace_dir or not policy_project or workspace_num is None:
        return [CaptureDecision("store", "missing_policy_context") for _ in candidates]
    selected_probe: VcsProbe = probe if probe is not None else GitVcsProbe()
    return decide_captures(
        [
            CaptureCandidate(
                path=candidate.path,
                origin=candidate.origin,
                sha256=candidate.sha256,
                size_bytes=candidate.size_bytes,
            )
            for candidate in candidates
        ],
        artifacts_dir=artifacts_dir,
        workspace_dir=workspace_dir,
        project=policy_project,
        workspace_num=workspace_num,
        run_started_at=_run_started_at(artifacts_dir),
        probe=selected_probe,
        limits=capture_limits
        or CaptureLimits(
            max_stored_per_agent=get_artifact_capture_max_stored_per_agent(),
            max_history_scan=get_artifact_capture_max_history_scan(),
        ),
    )


def _run_started_at(artifacts_dir: Path) -> float:
    raw_timestamp = artifacts_dir.name
    try:
        return datetime.strptime(raw_timestamp, "%Y%m%d%H%M%S").timestamp()
    except ValueError:
        pass
    try:
        return artifacts_dir.stat().st_mtime
    except OSError:
        return 0.0


def _prompt_source_files(artifacts_dir: Path) -> list[Path]:
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
) -> tuple[ArtifactFileKind, str, str]:
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


def _dedupe_plan_artifact_files(
    artifact_files: list[ArtifactFile],
) -> list[ArtifactFile]:
    plan_seen = False
    deduped: list[ArtifactFile] = []
    for artifact_file in artifact_files:
        if artifact_file.kind == "plan":
            if plan_seen:
                continue
            plan_seen = True
        deduped.append(artifact_file)
    return deduped


def _default_artifact_file(
    association: ArtifactFileAssociation,
    *,
    label: str,
    kind: ArtifactFileKind,
    path: str,
    ordinal: str,
    source_path: str | None = None,
    workspace_dir: str | None = None,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_file_id(f"default-{ordinal}", association, path, label),
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
