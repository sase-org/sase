"""Parity coverage for Patch queries across the legacy and profile engines."""

from __future__ import annotations

import pytest

from sase.ace.patch import HookEntry, HookStatusLine, Patch, Stitch
from sase.ace.query import parse_query_for_profile, to_canonical_string
from sase.ace.query.profile_reference import evaluate_query_many_for_profile
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.core import query_facade
from sase.core.query_profile_corpus_facade import (
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)


def _patch_corpus() -> list[Patch]:
    return [
        Patch(
            "grand",
            "root feature",
            None,
            status="WIP",
            file_path="/tmp/sase/sase.sase",
            refs=["task:1"],
        ),
        Patch(
            "mid",
            "middle feature",
            "grand",
            status="READY",
            file_path="/tmp/sase/sase.sase",
            pr_origin="external",
            stitches=[Stitch(1, "boom", suffix="bad", suffix_type="error")],
        ),
        Patch(
            "kid",
            "leaf needle",
            "mid",
            status="DRAFT",
            file_path="/tmp/sase/sase.sase",
            hooks=[
                HookEntry(
                    "test",
                    status_lines=[
                        HookStatusLine(
                            stitch_id="1",
                            timestamp="260101_000000",
                            status="RUNNING",
                            suffix="agent",
                            suffix_type="running_agent",
                        ),
                        HookStatusLine(
                            stitch_id="2",
                            timestamp="260101_000001",
                            status="RUNNING",
                            suffix="1234",
                            suffix_type="running_process",
                        ),
                    ],
                )
            ],
        ),
        Patch(
            "kid__1",
            "reverted sibling",
            "mid",
            status="REVERTED",
            file_path="/tmp/other/other.sase",
        ),
    ]


@pytest.mark.parametrize(
    "query",
    [
        '"feature"',
        '"task:1"',
        "needle",
        "%w",
        "%y",
        "%d",
        "%r",
        "+sase",
        "project:other",
        "^grand",
        "^mid",
        "~kid",
        "&kid__1",
        "origin:external",
        "!!!",
        "!!",
        "@@@",
        "!@",
        "$$$",
        "!$",
        "*",
        "+sase AND (%w OR %y)",
        "!+other AND ^grand",
    ],
)
def test_patch_query_profile_matches_legacy_rust_and_reference_masks(
    query: str,
) -> None:
    patches = _patch_corpus()
    profile = compiled_profile_for_builtin_pane("patches")
    assert profile is not None
    index = compile_artifact_query_index(
        pane_id="patches",
        generation=1,
        profile=profile,
        entries=patches,
    )

    legacy_mask = query_facade.evaluate_query_many(query, patches)
    profile_rust_mask = list(evaluate_artifact_query_many(query, index).matched_mask)
    reference_mask = evaluate_query_many_for_profile(query, patches, profile)

    assert profile_rust_mask == legacy_mask
    assert reference_mask == legacy_mask


@pytest.mark.parametrize(
    "query",
    [
        '"feature"',
        "%w",
        "+sase",
        "^grand",
        "~kid",
        "&kid__1",
        "!!!",
        "!!",
        "@@@",
        "!@",
        "$$$",
        "!$",
        "*",
        "+sase AND (%w OR %y)",
        "!+other AND ^grand",
    ],
)
def test_patch_profile_parser_canonicalizes_like_legacy_parser(query: str) -> None:
    profile = compiled_profile_for_builtin_pane("patches")
    assert profile is not None

    assert to_canonical_string(parse_query_for_profile(query, profile)) == (
        to_canonical_string(query_facade.parse_query(query))
    )
