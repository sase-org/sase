"""Contract: every host-written artifact-link origin survives the real binding.

sase once stamped ``prompt_prose`` on prose-detected citations while sase-core's
``ArtifactLinkOriginWire`` had no such variant, so serde rejected every such row
and publication failed on every pass with "unknown variant `prompt_prose`".
These tests enumerate ``ARTIFACT_LINK_HOST_ORIGINS`` and push each origin through
the compiled ``sase_core_rs`` extension, never a stub, so a host origin added
without Rust support fails here.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest
import sase_core_rs

from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.agents_sync.referenced_by_planning import PROMPT_PROSE_ORIGIN
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_origins import (
    ARTIFACT_LINK_AUTOMATIC_ORIGINS,
    ARTIFACT_LINK_COMMIT_SCOPED_ORIGINS,
    ARTIFACT_LINK_CURATED_ORIGINS,
    ARTIFACT_LINK_HOST_ORIGINS,
    ARTIFACT_LINK_MACHINE_TRUSTED_ORIGINS,
    ARTIFACT_LINK_USAGE_BEARING_ORIGINS,
)


def _minimal_row(origin: str) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": "agent:citer",
        "relation": "cites",
        "target_ref": "plan:202611/research_commit_gap.md",
        "description": "host origin contract row",
        "origin": origin,
        "created_by": "agent:citer",
        "created_at": "2026-11-20T00:00:00Z",
        "uses": 1,
    }


@pytest.mark.parametrize("origin", ARTIFACT_LINK_HOST_ORIGINS)
def test_host_origin_round_trips_through_validate_row(origin: str) -> None:
    validated = sase_core_rs.artifact_link_validate_row(_minimal_row(origin))

    assert validated["origin"] == origin


@pytest.mark.parametrize("origin", ARTIFACT_LINK_HOST_ORIGINS)
def test_usage_bearing_subset_matches_core_upsert(origin: str) -> None:
    row = _minimal_row(origin)
    first = sase_core_rs.artifact_link_upsert_row([], row)
    again = sase_core_rs.artifact_link_upsert_row(first["rows"], row)

    expected_uses = 2 if origin in ARTIFACT_LINK_USAGE_BEARING_ORIGINS else 1
    assert again["row"]["uses"] == expected_uses
    assert again["row"]["origin"] == origin


def test_host_origins_are_unique() -> None:
    assert len(set(ARTIFACT_LINK_HOST_ORIGINS)) == len(ARTIFACT_LINK_HOST_ORIGINS)


def test_derived_subsets_stay_inside_host_origins() -> None:
    host = set(ARTIFACT_LINK_HOST_ORIGINS)
    for subset in (
        ARTIFACT_LINK_AUTOMATIC_ORIGINS,
        ARTIFACT_LINK_COMMIT_SCOPED_ORIGINS,
        ARTIFACT_LINK_CURATED_ORIGINS,
        ARTIFACT_LINK_MACHINE_TRUSTED_ORIGINS,
        ARTIFACT_LINK_USAGE_BEARING_ORIGINS,
    ):
        assert subset <= host
    assert not ARTIFACT_LINK_AUTOMATIC_ORIGINS & ARTIFACT_LINK_CURATED_ORIGINS


def test_prompt_prose_shares_prompt_ref_semantics() -> None:
    for subset in (
        ARTIFACT_LINK_AUTOMATIC_ORIGINS,
        ARTIFACT_LINK_COMMIT_SCOPED_ORIGINS,
        ARTIFACT_LINK_MACHINE_TRUSTED_ORIGINS,
        ARTIFACT_LINK_USAGE_BEARING_ORIGINS,
    ):
        assert ("prompt_prose" in subset) == ("prompt_ref" in subset)
    assert "prompt_prose" not in ARTIFACT_LINK_CURATED_ORIGINS


def test_referenced_by_producer_origins_are_host_origins() -> None:
    assert PROMPT_PROSE_ORIGIN in ARTIFACT_LINK_HOST_ORIGINS
    defaults = {field.name: field.default for field in fields(ReferencedByOutboxItem)}
    assert defaults["origin"] in ARTIFACT_LINK_HOST_ORIGINS
