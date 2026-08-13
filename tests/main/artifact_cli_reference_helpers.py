"""Shared builders for artifact CLI reference tests."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_cli.references import ResolvedArtifactReference
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefResolution,
    parse_artifact_ref,
)
from sase.core.artifact_file_facade import ArtifactFile


ARTIFACT_DIGEST = "0123456789abcdef01234567"


def artifact_ref_context(tmp_path: Path) -> ArtifactRefContext:
    plans = tmp_path / "plans"
    chats = tmp_path / "chats"
    plans.mkdir()
    chats.mkdir()
    return ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plan", plans),),
        chats_root=chats,
        artifact_index_path=tmp_path / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject("sase", "gh_sase-org__sase"),),
        bead_stores=(
            ArtifactRefBeadStore(
                project="sase",
                prefix="sase",
                root=tmp_path / "beads",
            ),
        ),
        agent_roots=(
            ArtifactRefAgentRoot(
                project="sase",
                root=tmp_path / "agents-sidecar",
            ),
        ),
        agent_owner=ArtifactRefAgentOwner(
            username="alice",
            machine_name="athena",
        ),
    )


def artifact_file(path: Path, **overrides: object) -> ArtifactFile:
    values: dict[str, object] = {
        "id": f"explicit:{ARTIFACT_DIGEST}",
        "label": "Artifact",
        "kind": "file",
        "path": str(path),
        "source_path": None,
        "workspace_dir": None,
        "created_at": "2026-07-29T12:34:56Z",
        "agent_artifacts_dir": "/agents/run",
        "project": "gh_sase-org__sase",
        "workflow": "ace-run",
        "raw_timestamp": "20260729123456",
        "agent_name": "agent.one",
        "explicit": True,
        "sha256": "abc",
        "size_bytes": 3,
        "mime_type": "text/plain",
    }
    values.update(overrides)
    return ArtifactFile(**values)  # type: ignore[arg-type]


def resolved_reference(
    path: Path | None,
    *,
    reference: str = "plan:doc.md",
    status: str = "exact",
    candidates: tuple[str, ...] = (),
    file: ArtifactFile | None = None,
    locator: str | None = None,
    context: ArtifactRefContext | None = None,
) -> ResolvedArtifactReference:
    parsed = parse_artifact_ref(reference)
    return ResolvedArtifactReference(
        input=reference,
        canonical_reference=parsed.rendered,
        parsed=parsed,
        resolution=ArtifactRefResolution(
            schema_version=1,
            status=status,  # type: ignore[arg-type]
            rendered=parsed.rendered,
            locator=locator,
            resolved_path=path,
            candidates=candidates,
        ),
        file=file,
        context=context,
    )
