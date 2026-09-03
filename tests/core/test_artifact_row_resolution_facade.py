"""Facade coverage for Rust-owned artifact row-resolution rules."""

from __future__ import annotations

from collections.abc import Sequence

from sase.ace.tui.relations.artifact_links import target_for_ref_kind
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_row_resolution_facade import (
    artifact_row_index_keys,
    artifact_row_ref_lookup_keys,
    parse_artifact_link_ref,
    resolve_artifact_row_target,
)


def test_parse_artifact_link_ref_uses_canonical_kind_aliases() -> None:
    assert parse_artifact_link_ref("bead:sase-1") == ("bead", "sase-1")
    assert parse_artifact_link_ref("commit:sase@abc123") == (
        "stitch",
        "sase@abc123",
    )
    assert parse_artifact_link_ref("plans:202609/a.md") == (
        "plan",
        "202609/a.md",
    )
    assert parse_artifact_link_ref("@plan:202609/a.md#why") == (
        "plan",
        "202609/a.md",
    )
    assert parse_artifact_link_ref("not-a-ref") is None


def test_artifact_row_index_keys_are_batched_per_target() -> None:
    file_target = ArtifactEntryTarget("files", ("doc", "v1"))
    patch_target = ArtifactEntryTarget("patches", ("alpha", "same"))

    keys = artifact_row_index_keys((file_target, patch_target))

    assert ("files.id", "doc") in keys[0]
    assert ("patches.project.name", "alpha", "same") in keys[1]


def test_artifact_row_ref_lookup_keys_are_ordered_by_specificity() -> None:
    assert artifact_row_ref_lookup_keys("patch", "same", project_hint="beta") == (
        ("patches.project.name", "beta", "same"),
        ("patches.name", "same"),
    )
    assert artifact_row_ref_lookup_keys(
        "agent",
        "athena.worker",
        agent_name_candidates=("athena.worker", "worker"),
    ) == (
        ("exact", "agents", "athena.worker"),
        ("agents.name", "athena.worker"),
        ("agents.name", "worker"),
    )


def test_resolve_artifact_row_target_closes_class_a_identity_gaps() -> None:
    cases: tuple[
        tuple[
            str,
            str,
            tuple[ArtifactEntryTarget, ...],
            ArtifactEntryTarget,
            str | None,
            tuple[str, ...],
        ],
        ...,
    ] = (
        (
            "bead",
            "sase-1",
            (ArtifactEntryTarget("beads", ("alpha", "epic", "sase-1")),),
            ArtifactEntryTarget("beads", ("alpha", "epic", "sase-1")),
            "alpha",
            (),
        ),
        (
            "bead",
            "sase-1.1",
            (ArtifactEntryTarget("beads", ("alpha", "phase", "sase-1.1")),),
            ArtifactEntryTarget("beads", ("alpha", "phase", "sase-1.1")),
            "alpha",
            (),
        ),
        (
            "bead",
            "sase-flag",
            (ArtifactEntryTarget("beads", ("alpha", "flag", "sase-flag")),),
            ArtifactEntryTarget("beads", ("alpha", "flag", "sase-flag")),
            "alpha",
            (),
        ),
        (
            "plan",
            "202609/design.md",
            (ArtifactEntryTarget("ref:plan", ("alpha", "active", "202609/design.md")),),
            ArtifactEntryTarget("ref:plan", ("alpha", "active", "202609/design.md")),
            "alpha",
            (),
        ),
        (
            "plan",
            "notify-1",
            (ArtifactEntryTarget("ref:plan", ("alpha", "proposal", "notify-1")),),
            ArtifactEntryTarget("ref:plan", ("alpha", "proposal", "notify-1")),
            "alpha",
            (),
        ),
        (
            "stitch",
            "sase@012345",
            (
                ArtifactEntryTarget(
                    "stitches",
                    ("sase", "0123456789abcdef0123456789abcdef01234567"),
                ),
            ),
            ArtifactEntryTarget(
                "stitches",
                ("sase", "0123456789abcdef0123456789abcdef01234567"),
            ),
            None,
            (),
        ),
        (
            "patch",
            "same",
            (ArtifactEntryTarget("patches", ("alpha", "same")),),
            ArtifactEntryTarget("patches", ("alpha", "same")),
            None,
            (),
        ),
        (
            "agent",
            "athena.worker",
            (ArtifactEntryTarget("agents", ("worker",)),),
            ArtifactEntryTarget("agents", ("worker",)),
            None,
            ("athena.worker", "worker"),
        ),
        (
            "file",
            "doc",
            (ArtifactEntryTarget("files", ("doc", "v1")),),
            ArtifactEntryTarget("files", ("doc", "v1")),
            None,
            (),
        ),
    )

    for kind, payload, candidates, expected, project_hint, agent_candidates in cases:
        assert (
            _resolve(
                kind,
                payload,
                candidates,
                project_hint=project_hint,
                agent_name_candidates=agent_candidates,
            )
            == expected
        )
        assert target_for_ref_kind(kind, payload, project_hint=project_hint) != expected


def _resolve(
    kind: str,
    payload: str,
    candidates: Sequence[ArtifactEntryTarget],
    *,
    project_hint: str | None,
    agent_name_candidates: Sequence[str],
) -> ArtifactEntryTarget | None:
    return resolve_artifact_row_target(
        kind,
        payload,
        candidates,
        project_hint=project_hint,
        agent_name_candidates=agent_name_candidates,
    )
