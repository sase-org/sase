from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase import artifact_refs
from sase.artifact_refs import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)


def _context(
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
    )


def test_parse_render_and_scan_wrappers_round_trip() -> None:
    parsed = artifact_refs.parse_artifact_ref("plans:202607/plan.md#L2-L4")

    assert parsed.kind == "plans"
    assert parsed.kind_type == "document"
    assert parsed.payload.path == "202607/plan.md"
    assert parsed.fragment is not None
    assert (parsed.fragment.type, parsed.fragment.start, parsed.fragment.end) == (
        "lines",
        2,
        4,
    )
    assert artifact_refs.render_artifact_ref(parsed) == parsed.rendered

    candidates = artifact_refs.scan_artifact_refs("é @plans:202607/plan.md#L2-L4.")
    assert len(candidates) == 1
    assert candidates[0].reference == parsed.rendered
    assert candidates[0].candidate_span.start == len("é ".encode())
    assert candidates[0].fragment_span is not None


def test_context_assembles_dynamic_document_role_and_namespaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Store:
        def split_sidecar_roles(self) -> tuple[str, ...]:
            return ("plans", "designs", "beads")

        def kind_root(self, role: str) -> Path:
            if role == "designs":
                return tmp_path / "missing-designs-clone"
            if role == "plans":
                return tmp_path / "repo-plans"
            raise ValueError(role)

    repo = SimpleNamespace(name="sase", slug="sase-org/sase")
    inventory = SimpleNamespace(records=(repo,))
    project_record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=["core-ui"],
    )
    monkeypatch.setattr(artifact_refs, "resolve_sdd_store", lambda *_: _Store())
    monkeypatch.setattr(
        artifact_refs,
        "collect_repo_inventory",
        lambda **_: inventory,
    )
    monkeypatch.setattr(
        artifact_refs,
        "list_project_records",
        lambda *_args, **_kwargs: [project_record],
    )
    monkeypatch.setattr(
        artifact_refs,
        "effective_project_name",
        lambda record: record.display_name,
    )
    monkeypatch.setattr(
        artifact_refs,
        "sase_subdir",
        lambda name: tmp_path / "state" / name,
    )
    monkeypatch.setattr(
        artifact_refs,
        "default_artifact_files_index_path",
        lambda: tmp_path / "artifact-index.jsonl",
    )

    context = artifact_refs.artifact_ref_context(tmp_path / "workspace", 7)

    assert [(entry.kind, entry.root) for entry in context.document_roots] == [
        ("plans", (tmp_path / "repo-plans").resolve()),
        ("plans", (tmp_path / "state" / "plans").resolve()),
        ("designs", (tmp_path / "missing-designs-clone").resolve()),
    ]
    assert context.known_kinds == (
        "commit",
        "chat",
        "bug",
        "file",
        "plans",
        "designs",
    )
    assert context.repositories[0].name == "sase"
    assert context.projects[0] == ArtifactRefProject(
        name="sase",
        key="gh_sase-org__sase",
        aliases=("core-ui",),
    )


def test_document_chat_and_indexed_file_resolve_through_fixture_roots(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
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
        reference = artifact_refs.canonicalize_artifact_ref(path, context=context)
        assert reference == expected
        resolution = artifact_refs.resolve_artifact_ref(
            reference,
            context=context,
        )
        assert resolution.status == "exact"
        assert resolution.resolved_path == path


def test_bug_resolution_accepts_key_and_renders_display_name(tmp_path: Path) -> None:
    context = _context(tmp_path)

    resolution = artifact_refs.resolve_artifact_ref(
        "bug:gh_sase-org__sase#42",
        context=context,
    )

    assert resolution.status == "exact"
    assert resolution.rendered == "bug:sase#42"
    assert resolution.locator == "sase#42"


def test_reference_for_each_entry_target_shape(tmp_path: Path) -> None:
    context = _context(tmp_path)
    chat = context.chats_root / "202607" / "agent.md"
    proposal = context.document_roots[1].root / "202607" / "proposal.md"
    archive = SimpleNamespace(
        plan=SimpleNamespace(relpath="202607/design.md", kind="designs")
    )
    issue = SimpleNamespace(design="plans:202607/epic.md")

    assert (
        artifact_refs.reference_for_entry_target(
            "commits",
            ("commit", "sase", "a" * 40),
            context=context,
        )
        == f"commit:sase@{'a' * 40}"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "chats",
            ("chat", str(chat)),
            context=context,
        )
        == "chat:202607/agent.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "bugs",
            ("bug", "gh_sase-org__sase", "42"),
            context=context,
        )
        == "bug:sase#42"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "archive", str(archive.plan.relpath)),
            context=context,
            row=SimpleNamespace(archive=archive, archive_role="designs"),
        )
        == "designs:202607/design.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "epic", "sase-av"),
            context=context,
            row=SimpleNamespace(issue=issue),
        )
        == "plans:202607/epic.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "proposal", "notification"),
            context=context,
            row=SimpleNamespace(proposal=SimpleNamespace(plan_path=str(proposal))),
        )
        == "plans:202607/proposal.md"
    )


def test_reference_rendering_declines_unrepresentable_rows(tmp_path: Path) -> None:
    context = _context(tmp_path)

    assert (
        artifact_refs.reference_for_entry_target(
            "chats",
            ("chat", str(tmp_path / "imported.md")),
            context=context,
        )
        is None
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "phase", "sase-av.2"),
            context=context,
            row=SimpleNamespace(issue=SimpleNamespace(design="")),
        )
        is None
    )


def test_schema_gate_fails_before_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def require(name: str) -> Any:
        requested.append(name)
        if name == "artifact_ref_wire_schema_version":
            return lambda: 99
        raise AssertionError(name)

    monkeypatch.setattr(artifact_refs, "require_rust_binding", require)

    with pytest.raises(RuntimeError, match="wire is stale"):
        artifact_refs.parse_artifact_ref("plans:202607/plan.md")
    assert requested == ["artifact_ref_wire_schema_version"]
