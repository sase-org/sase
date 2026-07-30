"""Pure parsing and result coverage for artifact reference completion."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    build_artifact_ref_completion_result,
    detect_artifact_ref_completion_context,
)
from sase.ace.tui.widgets.prompt_path_inventory import PromptPathRow

from ._artifact_ref_completion_helpers import CATALOG, KINDS


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    (
        ("@", 1, ("kind", "", "", 0, 1)),
        ("@pl", 3, ("kind", "pl", "", 0, 3)),
        ("x @plans:", 9, ("payload", "plans", "", 2, 9)),
        (
            "x @plans:202607/old.md done",
            13,
            ("payload", "plans", "2026", 2, 22),
        ),
    ),
)
def test_detect_artifact_ref_context_at_kind_and_payload_positions(
    text: str,
    cursor: int,
    expected: tuple[str, str, str, int, int],
) -> None:
    context = detect_artifact_ref_completion_context(text, cursor, KINDS)

    assert context is not None
    assert (
        context.stage,
        context.partial_kind,
        context.partial_payload,
        context.replacement_start,
        context.replacement_end,
    ) == expected


@pytest.mark.parametrize(
    "text", ("@~/notes.md", "@/tmp/notes.md", "@./notes.md", "@../notes.md")
)
def test_detector_keeps_path_shaped_tokens_in_kind_stage(text: str) -> None:
    context = detect_artifact_ref_completion_context(text, len(text), KINDS)

    assert context is not None
    assert context.stage == "kind"
    assert context.path_directory is not None


def test_detector_converts_rust_byte_spans_to_python_offsets() -> None:
    text = "😀 @pl"

    context = detect_artifact_ref_completion_context(text, len(text), KINDS)

    assert context is not None
    assert (context.replacement_start, context.replacement_end) == (2, 5)
    assert (context.query_start, context.query_end) == (3, 5)


@pytest.mark.parametrize(
    "text",
    ("person@example:thing", "(@plans:thing.md)", "`@plans:thing.md`", "@foo!"),
)
def test_detector_declines_invalid_left_context_literals_and_punctuation(
    text: str,
) -> None:
    assert detect_artifact_ref_completion_context(text, len(text), KINDS) is None


def test_kind_rows_filter_case_insensitively_and_keep_dynamic_metadata() -> None:
    context = detect_artifact_ref_completion_context("@PL", 3, KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(context, CATALOG)

    assert [candidate.insertion for candidate in result.candidates] == ["@plans:"]
    metadata = result.candidates[0].metadata
    assert isinstance(metadata, ArtifactRefKindCompletionMetadata)
    assert (metadata.kind, metadata.builtin) == ("plans", False)


def test_payload_rows_keep_full_prefix_metadata_and_shared_extension() -> None:
    context = detect_artifact_ref_completion_context(
        "@plans:202607/",
        len("@plans:202607/"),
        KINDS,
    )
    assert context is not None

    result = build_artifact_ref_completion_result(context, CATALOG)

    assert [candidate.insertion for candidate in result.candidates] == [
        "@plans:202607/beta.md",
        "@plans:202607/alpha.md",
    ]
    assert result.shared_extension == ""
    metadata = result.candidates[0].metadata
    assert isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
    assert (metadata.source, metadata.label) == ("document", "Beta plan")


@pytest.mark.parametrize(
    ("token", "display", "insertion", "source", "label", "detail"),
    (
        (
            "@bead:",
            "sase-9z",
            "@bead:sase-9z",
            "bead",
            "Artifact references",
            "in_progress · epic",
        ),
        (
            "@agent:",
            "bbugyi200.athena.9w",
            "@agent:bbugyi200.athena.9w",
            "agent",
            "9w",
            "sase",
        ),
    ),
)
def test_entity_rows_keep_readable_labels_and_durable_payloads(
    token: str,
    display: str,
    insertion: str,
    source: str,
    label: str,
    detail: str,
) -> None:
    context = detect_artifact_ref_completion_context(token, len(token), KINDS)
    assert context is not None

    candidate = build_artifact_ref_completion_result(context, CATALOG).candidates[0]

    assert (candidate.display, candidate.insertion) == (display, insertion)
    metadata = candidate.metadata
    assert isinstance(metadata, ArtifactRefPayloadCompletionMetadata)
    assert (metadata.source, metadata.label, metadata.detail) == (
        source,
        label,
        detail,
    )


def test_kind_menu_filters_artifacts_and_files_through_shared_policy() -> None:
    context = detect_artifact_ref_completion_context("@pl", 3, KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(
        context,
        CATALOG,
        paths=(PromptPathRow("plans", True), PromptPathRow("plain.txt", False)),
    )

    assert [candidate.insertion for candidate in result.candidates] == ["@plans:"]
    assert result.files_suppressed is True

    revealed = build_artifact_ref_completion_result(
        context,
        CATALOG,
        include_files=True,
        paths=(PromptPathRow("plans", True), PromptPathRow("plain.txt", False)),
    )

    assert [candidate.insertion for candidate in revealed.candidates] == [
        "@plans:",
        "@plans/",
        "@plain.txt",
    ]
    assert revealed.files_suppressed is False
    assert isinstance(
        revealed.candidates[0].metadata, ArtifactRefKindCompletionMetadata
    )
    assert all(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in revealed.candidates[1:]
    )


def test_path_query_returns_only_rows_from_the_requested_directory() -> None:
    context = detect_artifact_ref_completion_context("@src/", 5, KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(
        context,
        CATALOG,
        paths=(PromptPathRow("pkg", True), PromptPathRow("main.py", False)),
    )

    assert [candidate.insertion for candidate in result.candidates] == [
        "@src/pkg/",
        "@src/main.py",
    ]
    assert all(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in result.candidates
    )


def test_kind_miss_lists_matching_files_without_ctrl_t() -> None:
    context = detect_artifact_ref_completion_context("@zz", 3, KINDS)
    assert context is not None

    result = build_artifact_ref_completion_result(
        context,
        CATALOG,
        paths=(PromptPathRow("fizz.txt", False),),
    )

    assert [candidate.insertion for candidate in result.candidates] == ["@fizz.txt"]
    assert result.files_suppressed is False
