from __future__ import annotations

from typing import Any

import pytest

from sase import artifact_ref_operations, artifact_refs
from sase.artifact_ref_models import check_record_schema
from sase.artifact_refs import (
    ARTIFACT_REF_LINK_LOCATION_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
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
    candidates = artifact_refs.scan_artifact_refs("é @plans:202607/plan.md#L2-L4.")
    assert len(candidates) == 1
    assert candidates[0].reference == parsed.rendered
    assert candidates[0].candidate_span.start == len("é ".encode())
    assert candidates[0].fragment_span is not None


def test_document_scan_wrapper_separates_visible_text_from_target() -> None:
    scan = artifact_refs.scan_artifact_ref_document(
        'é [plan](plan:202607/plan.md#L2) @plans:"a b.md" @src/app.py:7',
        known_kinds=("plan",),
    )

    assert (
        scan.schema_version
        == artifact_refs.ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION
    )
    assert [
        (link.text, link.target, link.target_kind)
        for link in scan.links
        if link.well_formed
    ] == [
        ("[plan](plan:202607/plan.md#L2)", "plan:202607/plan.md#L2", "artifact_ref"),
        ('@plans:"a b.md"', "plan:a b.md", "artifact_ref"),
        ("@src/app.py:7", "src/app.py:7", "file_path"),
    ]
    assert scan.links[0].source_span.start == len("é ".encode())


def test_document_scan_wrapper_accepts_xprompt_skill_targets() -> None:
    scan = artifact_refs.scan_artifact_ref_document(
        "Use #skill/sase_plan and [repo](#skill/sase_repo).",
        known_kinds=("plan",),
    )

    assert [
        (link.text, link.target, link.target_kind)
        for link in scan.links
        if link.target_kind == "xprompt_skill"
    ] == [
        ("#skill/sase_plan", "skill/sase_plan", "xprompt_skill"),
        ("[repo](#skill/sase_repo)", "skill/sase_repo", "xprompt_skill"),
    ]


@pytest.mark.parametrize(
    ("target", "base", "line", "column", "end_line"),
    [
        ("src/app.py:12", "src/app.py", 12, None, None),
        ("src/app.py:12:5", "src/app.py", 12, 5, None),
        ("src/app.py:12-40", "src/app.py", 12, None, 40),
        ("src/app.py:12:5-40", "src/app.py", 12, 5, 40),
        ("src/app.py#L12", "src/app.py", 12, None, None),
        ("src/app.py#L12-L40", "src/app.py", 12, None, 40),
        ("src/app.py#L12C5", "src/app.py", 12, 5, None),
        ("src/app.py#L12C5-L40C2", "src/app.py", 12, 5, 40),
        ("plan:202609/x.md:12", "plan:202609/x.md", 12, None, None),
    ],
)
def test_split_link_location_wrapper_uses_core_grammar(
    target: str,
    base: str,
    line: int,
    column: int | None,
    end_line: int | None,
) -> None:
    split = artifact_refs.split_link_location(target)

    assert ARTIFACT_REF_LINK_LOCATION_WIRE_SCHEMA_VERSION == 1
    assert split.base == base
    assert split.location is not None
    assert split.location.line == line
    assert split.location.column == column
    assert split.location.end_line == end_line


@pytest.mark.parametrize(
    "target",
    [
        "docs/guide.md#usage",
        "bead:sase-uk.1",
        "commit:abc1234",
        "src/app.py:0",
        "plan:foo:12",
        "a/b.py:1:2:3",
    ],
)
def test_split_link_location_leaves_non_locations_whole(target: str) -> None:
    split = artifact_refs.split_link_location(target)

    assert split.base == target
    assert split.location is None


@pytest.mark.parametrize(
    ("reference", "kind", "payload_field", "payload_value"),
    [
        ("bead:sase-9z.1", "bead", "id", "sase-9z.1"),
        (
            "agent:alice.athena.9w--code",
            "agent",
            "name",
            "alice.athena.9w--code",
        ),
    ],
)
def test_entity_references_round_trip_through_python_facade(
    reference: str,
    kind: str,
    payload_field: str,
    payload_value: str,
) -> None:
    parsed = artifact_refs.parse_artifact_ref(reference)

    assert parsed.schema_version == ARTIFACT_REF_WIRE_SCHEMA_VERSION == 5
    assert parsed.kind == parsed.kind_type == kind
    assert getattr(parsed.payload, payload_field) == payload_value
    assert parsed.to_wire()["payload"] == {
        "type": kind,
        payload_field: payload_value,
    }


@pytest.mark.parametrize(
    "reference",
    ["bead:sase-9z#L1", "agent:9w#L1"],
)
def test_entity_references_reject_fragments(reference: str) -> None:
    with pytest.raises(ValueError, match="references do not support fragments"):
        artifact_refs.parse_artifact_ref(reference)


def test_path_filter_wrapper_preserves_allow_and_filtered_sets() -> None:
    result = artifact_refs.filter_artifact_ref_paths(
        "plans",
        ["202608/plan.md", "202608/render.png"],
        path_globs=["**/*.md"],
    )

    assert result.schema_version == ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION == 1
    assert result.kind == "plans"
    assert result.allowed == ("202608/plan.md",)
    assert result.filtered == ("202608/render.png",)
    assert (
        artifact_refs.filter_artifact_ref_paths(
            "plans",
            ["202608/plan.md"],
            path_globs=[],
        ).allowed
        == ()
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

    monkeypatch.setattr(artifact_ref_operations, "require_rust_binding", require)

    with pytest.raises(RuntimeError, match="wire is stale"):
        artifact_refs.parse_artifact_ref("plans:202607/plan.md")
    assert requested == ["artifact_ref_wire_schema_version"]


def test_record_schema_rejects_schema_one() -> None:
    assert ARTIFACT_REF_WIRE_SCHEMA_VERSION == 5
    with pytest.raises(RuntimeError, match="unsupported test wire: 1"):
        check_record_schema({"schema_version": 1}, record="test")
