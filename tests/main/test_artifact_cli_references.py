"""Reference resolution tests for ``sase artifact``."""

from __future__ import annotations

import json
from pathlib import Path

from sase.artifact_cli.references import (
    resolution_error_lines,
    resolve_cli_reference,
)
from sase.artifact_refs import ArtifactRefContext, ArtifactRefProject
from tests.main.artifact_cli_reference_helpers import (
    ARTIFACT_DIGEST,
    artifact_file,
    artifact_ref_context,
    resolved_reference,
)


def test_shared_resolver_supports_bare_file_id_and_full_record(
    tmp_path: Path,
) -> None:
    context = artifact_ref_context(tmp_path)
    stored = tmp_path / "stored artifact.txt"
    stored.write_text("artifact", encoding="utf-8")
    row = artifact_file(stored)
    context.artifact_index_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact": dict(vars(row)),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = resolve_cli_reference(f"explicit:{ARTIFACT_DIGEST}", context=context)

    assert result.canonical_reference == f"file:explicit:{ARTIFACT_DIGEST}"
    assert result.resolution.status == "exact"
    assert result.resolution.resolved_path == stored
    assert result.file == row
    envelope = result.to_json_dict()
    assert envelope["file"]["ref"] == f"file:explicit:{ARTIFACT_DIGEST}"  # type: ignore[index]


def test_shared_resolver_supports_entity_page_references(
    tmp_path: Path,
) -> None:
    context = artifact_ref_context(tmp_path)
    bead_page = context.bead_stores[0].root / "pages" / "sase-9z" / "README.md"
    agent_page = (
        context.agent_roots[0].root / "agents" / "alice.athena.9w" / "README.md"
    )
    bead_page.parent.mkdir(parents=True)
    agent_page.parent.mkdir(parents=True)
    bead_page.write_text("# Bead\n", encoding="utf-8")
    agent_page.write_text("# Agent\n", encoding="utf-8")

    bead = resolve_cli_reference("bead:sase-9z", context=context)
    agent = resolve_cli_reference("agent:9w", context=context)

    assert bead.is_filesystem_backed is True
    assert bead.resolution.status == "exact"
    assert bead.resolution.resolved_path == bead_page
    assert bead.to_json_dict()["resolution"]["resolved_path"] == str(bead_page)  # type: ignore[index]

    assert agent.is_filesystem_backed is True
    assert agent.canonical_reference == "agent:alice.athena.9w"
    assert agent.resolution.status == "exact"
    assert agent.resolution.resolved_path == agent_page
    assert agent.to_json_dict()["reference"] == "agent:alice.athena.9w"


def test_shared_resolver_serializes_fragment_and_drift_candidates(
    tmp_path: Path,
) -> None:
    context = artifact_ref_context(tmp_path)
    drifted = context.document_roots[0].root / "nested" / "doc.md"
    drifted.parent.mkdir()
    drifted.write_text("one\ntwo\n", encoding="utf-8")

    result = resolve_cli_reference("plan:doc.md#L2", context=context)

    assert result.resolution.status == "drifted"
    assert result.resolution.resolved_path == drifted
    assert result.to_json_dict()["fragment"] == {
        "type": "lines",
        "start": 2,
        "end": 2,
        "page": None,
        "seconds": None,
    }
    assert result.to_json_dict()["resolution"]["candidates"] == [str(drifted)]  # type: ignore[index]


def test_resolution_errors_include_entity_publication_hints(
    tmp_path: Path,
) -> None:
    context = artifact_ref_context(tmp_path)
    candidate = context.bead_stores[0].root / "pages" / "sase-missing" / "README.md"
    bead = resolved_reference(
        None,
        reference="bead:sase-missing",
        status="missing",
        candidates=(str(candidate),),
        context=context,
    )
    agent = resolved_reference(
        None,
        reference="agent:missing",
        status="missing",
        candidates=(
            str(context.agent_roots[0].root / "agents" / "alice.athena.missing"),
        ),
        context=context,
    )
    foreign = resolved_reference(
        None,
        reference="bead:other-1",
        status="unknown_project",
        context=ArtifactRefContext(
            document_roots=context.document_roots,
            chats_root=context.chats_root,
            artifact_index_path=context.artifact_index_path,
            repositories=context.repositories,
            projects=(ArtifactRefProject("other", "gh_other__repo"),),
        ),
    )

    assert "hint: no published page for sase-missing" in "\n".join(
        resolution_error_lines(bead)
    )
    assert "sase bead page refresh" in "\n".join(resolution_error_lines(bead))
    assert "hint: no published page for missing" in "\n".join(
        resolution_error_lines(agent)
    )
    assert "sase agent sync" in "\n".join(resolution_error_lines(agent))
    assert (
        "hint: project other has no bead store in this reference context"
        in "\n".join(resolution_error_lines(foreign))
    )
