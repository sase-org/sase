from pathlib import Path

from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)


def context(
    tmp_path: Path,
    *,
    document_kind: str = "designs",
) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot(document_kind, tmp_path / document_kind),
            ArtifactRefDocumentRoot("plans", tmp_path / "plans"),
        ),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(ArtifactRefRepository("sase"),),
        projects=(
            ArtifactRefProject(
                name="sase",
                key="gh_sase-org__sase",
                aliases=("core-ui",),
            ),
        ),
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
