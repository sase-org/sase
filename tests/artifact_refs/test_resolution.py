from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from sase import artifact_ref_operations, artifact_refs
from sase.artifact_refs import ArtifactRefContext, ArtifactRefDocumentRoot

from .helpers import context as make_context


def test_document_chat_and_indexed_file_resolve_through_fixture_roots(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    document = tmp_path / "designs" / "202607" / "design.md"
    chat = tmp_path / "chats" / "202607" / "agent.md"
    artifact = tmp_path / "output.png"
    document.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    context.artifact_index_path.parent.mkdir(parents=True)
    document.write_text("# Design\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")
    artifact.write_bytes(b"png")
    artifact_id = "default:52895d68931185056fd0e49f"
    context.artifact_index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": {
                    "id": artifact_id,
                    "path": str(artifact),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    for path, expected in (
        (document, "designs:202607/design.md"),
        (chat, "chat:202607/agent.md"),
        (artifact, f"file:{artifact_id}"),
    ):
        reference = artifact_ref_operations.canonicalize_artifact_ref(
            path,
            context=context,
        )
        assert reference == expected
        resolution = artifact_refs.resolve_artifact_ref(
            reference,
            context=context,
        )
        assert resolution.status == "exact"
        assert resolution.resolved_path == path


def test_bug_resolution_accepts_key_and_renders_display_name(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    resolution = artifact_refs.resolve_artifact_ref(
        "bug:gh_sase-org__sase#42",
        context=context,
    )

    assert resolution.status == "exact"
    assert resolution.rendered == "bug:sase#42"
    assert resolution.locator == "sase#42"


def test_bead_resolution_statuses_and_candidates(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    page = context.bead_stores[0].root / "pages" / "sase-9z" / "README.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Bead\n", encoding="utf-8")

    exact = artifact_refs.resolve_artifact_ref("bead:sase-9z", context=context)
    assert exact.status == "exact"
    assert exact.resolved_path == page
    assert exact.locator == "sase/sase-9z"

    unknown = artifact_refs.resolve_artifact_ref("bead:other-9z", context=context)
    assert unknown.status == "unknown_project"

    missing = artifact_refs.resolve_artifact_ref("bead:sase-aa", context=context)
    assert missing.status == "missing"
    assert missing.candidates == (
        str(context.bead_stores[0].root / "pages" / "sase-aa" / "README.md"),
    )


def test_agent_resolution_globalizes_local_name_and_reports_missing(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    page = (
        context.agent_roots[0].root / "agents" / "alice.athena.9w--code" / "README.md"
    )
    page.parent.mkdir(parents=True)
    page.write_text("# Agent\n", encoding="utf-8")

    exact = artifact_refs.resolve_artifact_ref("agent:9w--code", context=context)
    assert exact.status == "exact"
    assert exact.resolved_path == page
    assert exact.rendered == "agent:alice.athena.9w--code"
    assert exact.locator == "sase/alice.athena.9w--code"

    missing = artifact_refs.resolve_artifact_ref("agent:missing", context=context)
    assert missing.status == "missing"
    assert missing.candidates


def test_context_without_entity_sidecars_preserves_other_resolution(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    context = ArtifactRefContext(
        document_roots=context.document_roots,
        chats_root=context.chats_root,
        artifact_index_path=context.artifact_index_path,
        repositories=context.repositories,
        projects=context.projects,
    )
    document = context.document_roots[0].root / "design.md"
    chat = context.chats_root / "agent.md"
    document.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    document.write_text("# Design\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")

    assert (
        artifact_refs.resolve_artifact_ref(
            "designs:design.md",
            context=context,
        ).status
        == "exact"
    )
    assert (
        artifact_refs.resolve_artifact_ref(
            "chat:agent.md",
            context=context,
        ).status
        == "exact"
    )


def test_filtered_document_resolution_preserves_core_diagnostic(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    root = context.document_roots[1].root
    path = root / "private" / "secret.md"
    path.parent.mkdir(parents=True)
    path.write_text("secret\n", encoding="utf-8")
    context = replace(
        context,
        document_roots=(
            ArtifactRefDocumentRoot(
                "plans",
                root,
                path_globs=("public/**",),
            ),
        ),
    )

    resolution = artifact_refs.resolve_artifact_ref(
        "plans:private/secret.md",
        context=context,
    )

    assert resolution.status == "filtered"
    assert resolution.resolved_path is None
    assert resolution.diagnostic is not None
    assert "kind=plans" in resolution.diagnostic
