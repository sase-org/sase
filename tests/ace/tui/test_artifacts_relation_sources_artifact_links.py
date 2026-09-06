"""Focused coverage for the artifact_links Artifacts relation source."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.relations import ArtifactLinksSnapshot, build_files_relation_index
from sase.ace.tui.relations import artifact_links
from sase.ace.tui.widgets.artifacts.files_data import (
    FileVersion,
    FilesSnapshot,
    LogicalFile,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget


def test_artifact_links_source_emits_typed_relations_for_current_pane() -> None:
    snapshot = _files_snapshot_with_link_rows(
        (
            {
                "source_ref": "file:doc",
                "relation": "implements",
                "target_ref": "bead:sase-r8",
                "description": "extends requirement",
                "origin": "manual",
                "uses": 3,
            },
            {
                "source_ref": "plan:202608/design.md",
                "relation": "implements",
                "target_ref": "file:doc",
                "description": "frontmatter link",
                "origin": "derived",
                "uses": 2,
            },
        )
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))

    implements = index.edges_for_relation(row, "implements")
    assert implements[0].target == ArtifactEntryTarget(
        "beads", ("alpha", "task", "sase-r8")
    )
    assert implements[0].label == "implements"
    assert implements[0].description == "extends requirement"
    assert implements[0].origin == "manual"
    assert implements[0].uses == 3
    implemented_by = index.edges_for_relation(row, "implemented-by")
    assert implemented_by[0].target == ArtifactEntryTarget(
        "ref:plan", ("alpha", "archive", "202608/design.md")
    )
    assert implemented_by[0].label == "implemented-by"
    assert implemented_by[0].description == "frontmatter link"
    assert implemented_by[0].origin == "derived"
    assert implemented_by[0].uses == 2


def test_artifact_links_source_deduplicates_undirected_related_rows() -> None:
    snapshot = _files_snapshot_with_link_rows(
        (
            {
                "source_ref": "file:doc",
                "relation": "related",
                "target_ref": "file:other",
            },
            {
                "source_ref": "file:other",
                "relation": "related",
                "target_ref": "file:doc",
            },
        ),
        extra_logical_ids=("other",),
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))

    assert [
        edge.target.parts[0] for edge in index.edges_for_relation(row, "related")
    ] == ["other"]


def test_artifact_links_source_resolves_known_targets_with_one_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = (
        ArtifactEntryTarget("files", ("doc",)),
        *(ArtifactEntryTarget("files", (f"other-{index}",)) for index in range(200)),
    )
    snapshot = ArtifactLinksSnapshot(
        rows=tuple(
            {
                "source_ref": "file:doc",
                "relation": "related",
                "target_ref": f"file:other-{index}",
                "_project": "alpha",
            }
            for index in range(200)
        )
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    build_count = 0
    original_build = artifact_links._KnownTargetIndex.build

    def counted_build(known_targets: Iterable[ArtifactEntryTarget]):
        nonlocal build_count
        build_count += 1
        return original_build(known_targets)

    monkeypatch.setattr(
        artifact_links._KnownTargetIndex, "build", staticmethod(counted_build)
    )

    edges = artifact_links.artifact_link_edges(
        snapshot,
        contract=contract,
        known_targets=targets,
        project_hint="alpha",
    )

    assert len(edges) == 200
    assert build_count == 1


class _NonIterableTargets(frozenset[ArtifactEntryTarget]):
    def __iter__(self) -> Iterator[ArtifactEntryTarget]:
        raise AssertionError("_known_target_for_ref scanned indexed targets")


def test_known_target_for_ref_uses_index_lookup_without_target_scan() -> None:
    target = ArtifactEntryTarget("patches", ("alpha", "needle"))
    index = artifact_links._KnownTargetIndex(
        targets=_NonIterableTargets(),
        by_key={("patches.name", "needle"): target},
        agent_identity=None,
    )

    assert artifact_links._known_target_for_ref("patch", "needle", index) == target


def test_known_target_index_uses_project_hint_then_deterministic_fallback() -> None:
    known = frozenset(
        {
            ArtifactEntryTarget("files", ("doc",)),
            ArtifactEntryTarget("files", ("doc", "v1")),
            ArtifactEntryTarget("beads", ("alpha", "epic", "same-bead")),
            ArtifactEntryTarget("beads", ("beta", "phase", "same-bead")),
            ArtifactEntryTarget("patches", ("alpha", "same")),
            ArtifactEntryTarget("patches", ("beta", "same")),
            ArtifactEntryTarget("stitches", ("sase", "abc1234")),
            ArtifactEntryTarget("stitches", ("sase", "abc123456")),
            ArtifactEntryTarget("ref:plan", ("alpha", "active", "design.md")),
            ArtifactEntryTarget("ref:plan", ("beta", "archive", "design.md")),
        }
    )
    index = artifact_links._KnownTargetIndex.build(known)

    assert artifact_links._known_target_for_ref(
        "bead", "same-bead", index, project_hint="beta"
    ) == ArtifactEntryTarget("beads", ("beta", "phase", "same-bead"))
    assert artifact_links._known_target_for_ref("bead", "same-bead", index) == (
        ArtifactEntryTarget("beads", ("alpha", "epic", "same-bead"))
    )
    assert artifact_links._known_target_for_ref(
        "patch", "same", index, project_hint="beta"
    ) == ArtifactEntryTarget("patches", ("beta", "same"))
    assert artifact_links._known_target_for_ref("patch", "same", index) == (
        ArtifactEntryTarget("patches", ("alpha", "same"))
    )
    assert artifact_links._known_target_for_ref("stitch", "sase@abc", index) == (
        ArtifactEntryTarget("stitches", ("sase", "abc1234"))
    )
    assert artifact_links._known_target_for_ref(
        "plan", "design.md", index, project_hint="beta"
    ) == ArtifactEntryTarget("ref:plan", ("beta", "archive", "design.md"))
    assert artifact_links._known_target_for_ref("plan", "design.md", index) == (
        ArtifactEntryTarget("ref:plan", ("alpha", "active", "design.md"))
    )


def test_known_target_index_matches_legacy_for_unambiguous_targets() -> None:
    known = frozenset(
        {
            ArtifactEntryTarget("files", ("doc",)),
            ArtifactEntryTarget("files", ("doc", "v1")),
            ArtifactEntryTarget("patches", ("alpha", "only")),
            ArtifactEntryTarget("stitches", ("sase", "def4567")),
            ArtifactEntryTarget("ref:plan", ("alpha", "active", "solo.md")),
        }
    )
    index = artifact_links._KnownTargetIndex.build(known)

    for kind, payload in (
        ("file", "doc"),
        ("patch", "only"),
        ("stitch", "sase@def"),
        ("plan", "solo.md"),
    ):
        assert artifact_links._known_target_for_ref(kind, payload, index) == (
            _legacy_known_target_for_ref(kind, payload, known)
        )


def test_known_target_for_ref_prefers_project_hinted_bead_and_patch() -> None:
    index = artifact_links._KnownTargetIndex.build(
        frozenset(
            {
                ArtifactEntryTarget("beads", ("alpha", "task", "same")),
                ArtifactEntryTarget("beads", ("beta", "flag", "same")),
                ArtifactEntryTarget("patches", ("alpha", "same")),
                ArtifactEntryTarget("patches", ("beta", "same")),
            }
        )
    )

    assert artifact_links._known_target_for_ref(
        "bead", "same", index, project_hint="beta"
    ) == ArtifactEntryTarget("beads", ("beta", "flag", "same"))
    assert artifact_links._known_target_for_ref(
        "patch", "same", index, project_hint="beta"
    ) == ArtifactEntryTarget("patches", ("beta", "same"))


def _legacy_known_target_for_ref(
    kind: str,
    payload: str,
    known_targets: frozenset[ArtifactEntryTarget],
) -> ArtifactEntryTarget | None:
    if kind == "file":
        exact_file = ArtifactEntryTarget("files", (payload,))
        if exact_file in known_targets:
            return exact_file
    if kind == "agent":
        exact_agent = ArtifactEntryTarget("agents", (payload,))
        if exact_agent in known_targets:
            return exact_agent
    for target in known_targets:
        if kind == "stitch" and target.pane_id == "stitches":
            repo, at, sha = payload.partition("@")
            if at and len(target.parts) >= 2 and target.parts[0] == repo:
                if target.parts[1] == sha or str(target.parts[1]).startswith(sha):
                    return target
        elif kind == "patch" and target.pane_id == "patches":
            if target.parts and target.parts[-1] == payload:
                return target
        elif kind == "bead" and target.pane_id == "beads":
            if target.parts and target.parts[-1] == payload:
                return target
        elif kind == "file" and target.pane_id == "files":
            if target.parts and target.parts[0] == payload:
                return target
        elif kind == "agent" and target.pane_id == "agents":
            if target.parts and payload in (
                artifact_links.current_owner_agent_name_lookup_candidates(
                    str(target.parts[-1])
                )
            ):
                return target
        elif target.pane_id == f"ref:{kind}":
            if target.parts and target.parts[-1] == payload:
                return target
    return None


def _files_snapshot_with_link_rows(
    rows: tuple[dict[str, str], ...],
    *,
    extra_logical_ids: tuple[str, ...] = (),
) -> FilesSnapshot:
    logical_ids = ("doc", *extra_logical_ids)
    logical_rows: list[LogicalFile] = []
    for logical_id in logical_ids:
        version = FileVersion(
            version_id=f"{logical_id}-v1",
            logical_id=logical_id,
            label=logical_id,
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=("alpha",),
        )
        logical_rows.append(
            LogicalFile(
                logical_id=logical_id,
                label=logical_id,
                kind="file",
                versions=(version,),
                agents=(),
                projects=("alpha",),
                origins=frozenset({"ref"}),
                latest_seen_at=None,
            )
        )
    return FilesSnapshot(
        rows=tuple(logical_rows),
        project="alpha",
        complete=True,
        view_modes={f"{logical_id}-v1": "text" for logical_id in logical_ids},
        view_mode_counts={"text": len(logical_ids)},
        origin_counts={"ref": len(logical_ids)},
        artifact_links=ArtifactLinksSnapshot(
            rows=tuple({**row, "_project": "alpha"} for row in rows),
        ),
    )
