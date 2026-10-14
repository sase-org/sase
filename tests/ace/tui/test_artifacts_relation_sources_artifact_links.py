"""Focused coverage for the artifact_links Artifacts relation source."""

from __future__ import annotations

import json

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
from tests.perf.artifact_link_index_bench import (
    FIXTURE_PATCH_INDEX_PATH,
    build_patch_index,
    fixture_patches,
    fixture_snapshot,
    identity_from_payload,
    load_fixture_input,
    parity_diff,
    pinned_identity,
    serialize_relation_index,
)


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
    import sase.ace.tui.relations._native_link_index as native_link_index

    build_count = 0
    original_build = native_link_index.build_index

    def counted_build(*args: object, **kwargs: object):
        nonlocal build_count
        build_count += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(native_link_index, "build_index", counted_build)

    edges = artifact_links.artifact_link_edges(
        snapshot,
        contract=contract,
        known_targets=targets,
        project_hint="alpha",
    )

    assert len(edges) == 200
    assert build_count == 1


def test_projection_never_calls_per_row_target_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pane projection must not resolve targets row by row in Python."""

    def _forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("projection walked rows through per-ref resolution")

    monkeypatch.setattr(artifact_links, "resolve_artifact_row_target", _forbidden)
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
        )
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))
    assert index.edges_for_relation(row, "implements")


def test_projection_candidate_set_ignores_unrelated_rows() -> None:
    """Unrelated aggregate rows must not grow the indexed candidate set."""

    import sase.ace.tui.relations._native_link_index as native_link_index
    from sase.core.artifact_link_index_facade import index_project

    patch_rows = [
        {
            "source_ref": "patch:root",
            "relation": "implements",
            "target_ref": "bead:sase-1",
            "description": "",
            "origin": "manual",
            "uses": 1,
            "_project": "alpha",
        },
        {
            "source_ref": "patch:root_child",
            "relation": "related",
            "target_ref": "patch:root",
            "description": "",
            "origin": "manual",
            "uses": 1,
            "_project": "alpha",
        },
    ]
    noise_rows = [
        {
            "source_ref": f"bead:sase-noise-{index}",
            "relation": "related",
            "target_ref": f"plan:202608/noise-{index}.md",
            "description": "",
            "origin": "manual",
            "uses": 1,
            "_project": "alpha",
        }
        for index in range(200)
    ]
    known = (
        ArtifactEntryTarget("patches", ("alpha", "root")),
        ArtifactEntryTarget("patches", ("alpha", "root_child")),
    )
    snapshot = ArtifactLinksSnapshot(
        rows=(*patch_rows, *noise_rows), source_key=("test-candidates",)
    )
    handle = native_link_index.native_handle_for_snapshot(snapshot)
    response = index_project(
        handle,
        known_targets=known,
        permitted_relations=("implements", "related"),
        project_hint="alpha",
    )
    assert response["candidate_row_count"] <= len(patch_rows)
    assert response["candidate_row_count"] < len(snapshot.rows)


def test_known_target_for_ref_resolves_without_target_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ArtifactEntryTarget("patches", ("alpha", "needle"))
    calls = 0
    original = artifact_links.resolve_artifact_row_target

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(artifact_links, "resolve_artifact_row_target", counted)

    assert (
        artifact_links.known_target_for_ref("patch", "needle", frozenset({target}))
        == target
    )
    assert calls == 1


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
    assert artifact_links._known_target_for_ref(
        "bead", "same-bead", known, project_hint="beta"
    ) == ArtifactEntryTarget("beads", ("beta", "phase", "same-bead"))
    assert artifact_links._known_target_for_ref("bead", "same-bead", known) == (
        ArtifactEntryTarget("beads", ("alpha", "epic", "same-bead"))
    )
    assert artifact_links._known_target_for_ref(
        "patch", "same", known, project_hint="beta"
    ) == ArtifactEntryTarget("patches", ("beta", "same"))
    assert artifact_links._known_target_for_ref("patch", "same", known) == (
        ArtifactEntryTarget("patches", ("alpha", "same"))
    )
    assert artifact_links._known_target_for_ref("stitch", "sase@abc", known) == (
        ArtifactEntryTarget("stitches", ("sase", "abc1234"))
    )
    assert artifact_links._known_target_for_ref(
        "plan", "design.md", known, project_hint="beta"
    ) == ArtifactEntryTarget("ref:plan", ("beta", "archive", "design.md"))
    assert artifact_links._known_target_for_ref("plan", "design.md", known) == (
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
    for kind, payload in (
        ("file", "doc"),
        ("patch", "only"),
        ("stitch", "sase@def"),
        ("plan", "solo.md"),
    ):
        assert artifact_links._known_target_for_ref(kind, payload, known) == (
            _legacy_known_target_for_ref(kind, payload, known)
        )


def test_known_target_for_ref_prefers_project_hinted_bead_and_patch() -> None:
    known = frozenset(
        {
            ArtifactEntryTarget("beads", ("alpha", "task", "same")),
            ArtifactEntryTarget("beads", ("beta", "flag", "same")),
            ArtifactEntryTarget("patches", ("alpha", "same")),
            ArtifactEntryTarget("patches", ("beta", "same")),
        }
    )

    assert artifact_links._known_target_for_ref(
        "bead", "same", known, project_hint="beta"
    ) == ArtifactEntryTarget("beads", ("beta", "flag", "same"))
    assert artifact_links._known_target_for_ref(
        "patch", "same", known, project_hint="beta"
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


def test_parity_fixture_pins_every_patch_relation_edge_and_target() -> None:
    payload = load_fixture_input()
    expected = json.loads(FIXTURE_PATCH_INDEX_PATH.read_text(encoding="utf-8"))
    snapshot = fixture_snapshot(payload)
    patches = fixture_patches(payload)
    with pinned_identity(identity_from_payload(payload)):
        actual = serialize_relation_index(build_patch_index(snapshot, patches))
    diffs = parity_diff(actual, expected)
    assert diffs == [], "\n".join(diffs[:50])
    assert actual["edges"], "parity fixture must emit Patch relation edges"
    for edge in actual["edges"]:
        assert set(edge) == {
            "dangling",
            "derived",
            "description",
            "kind",
            "label",
            "origin",
            "relation",
            "source",
            "target",
            "uses",
        }
