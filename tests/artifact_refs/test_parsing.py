from __future__ import annotations

from typing import Any

import pytest

from sase import artifact_ref_operations, artifact_refs
from sase.artifact_ref_models import check_record_schema
from sase.artifact_refs import (
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

    assert parsed.schema_version == ARTIFACT_REF_WIRE_SCHEMA_VERSION == 4
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
    assert ARTIFACT_REF_WIRE_SCHEMA_VERSION == 4
    with pytest.raises(RuntimeError, match="unsupported test wire: 1"):
        check_record_schema({"schema_version": 1}, record="test")
