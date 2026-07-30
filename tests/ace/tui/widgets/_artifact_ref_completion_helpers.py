"""Shared fixtures for artifact reference completion tests."""

from __future__ import annotations

from sase.ace.tui.widgets._artifact_ref_entity_catalogs import (
    ArtifactRefAgentCandidate,
    ArtifactRefBeadCandidate,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ArtifactRefCompletionCatalog,
    _ArtifactRefChatCandidate,
    _ArtifactRefDocumentCandidate,
    _ArtifactRefFileCandidate,
)
from sase.ace.tui.widgets.prompt_path_inventory import (
    PromptPathRow,
    PromptPathSnapshot,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


KINDS = (
    "commit",
    "chat",
    "bug",
    "file",
    "bead",
    "agent",
    "plans",
    "designs",
)
CATALOG = ArtifactRefCompletionCatalog(
    project=None,
    kinds=KINDS,
    documents=(
        _ArtifactRefDocumentCandidate(
            "plans",
            "202607/alpha.md",
            "Alpha plan",
            "2026-07-29T12:00:00Z",
        ),
        _ArtifactRefDocumentCandidate(
            "plans",
            "202607/beta.md",
            "Beta plan",
            "2026-07-28T12:00:00Z",
        ),
        _ArtifactRefDocumentCandidate(
            "designs",
            "202607/layout.md",
            "Layout",
            "2026-07-27T12:00:00Z",
        ),
    ),
    artifact_files=(
        _ArtifactRefFileCandidate(
            "explicit:abc123",
            "Architecture diagram",
            "image",
            "2026-07-29T12:00:00Z",
        ),
    ),
    chats=(_ArtifactRefChatCandidate("202607/agent.md", 1_785_326_400),),
    beads=(
        ArtifactRefBeadCandidate(
            "sase-9z",
            "Artifact references",
            "in_progress · epic",
            "2026-07-29T12:00:00Z",
        ),
    ),
    agents=(
        ArtifactRefAgentCandidate(
            "bbugyi200.athena.9w",
            "9w",
            "sase",
            1_785_326_400,
        ),
    ),
)


def seed_catalog(
    text_area: PromptTextArea,
    catalog: ArtifactRefCompletionCatalog,
    *,
    project: str | None = None,
) -> None:
    text_area._artifact_ref_known_kinds_by_project[project] = frozenset(catalog.kinds)
    text_area._artifact_ref_completion_catalogs_by_project[project] = catalog


def seed_paths(
    text_area: PromptTextArea,
    directory: str,
    rows: tuple[PromptPathRow, ...],
) -> str:
    key = text_area._prompt_path_directory_key(directory)
    text_area._prompt_path_snapshots[key] = PromptPathSnapshot(key, rows, (1, 1))
    # Keep the synthetic snapshot stable instead of letting a real worker
    # revalidate the test process's directory.
    text_area._prompt_path_inflight.add(key)
    return key
