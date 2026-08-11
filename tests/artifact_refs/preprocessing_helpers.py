from __future__ import annotations

from pathlib import Path

import pytest

from sase import artifact_ref_prompt
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)


@pytest.fixture(autouse=True)
def disable_consumption_ledger_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda _events: None,
    )


def context(tmp_path: Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot("plan", tmp_path / "plans"),
            ArtifactRefDocumentRoot("designs", tmp_path / "designs"),
        ),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(
            ArtifactRefRepository(
                "sase",
                aliases=("sase-org/sase",),
                checkout_path=tmp_path / "workspace",
                checkout_paths=(tmp_path / "workspace",),
                kind="primary",
            ),
        ),
        projects=(
            ArtifactRefProject(
                name="sase",
                key="gh_sase-org__sase",
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
