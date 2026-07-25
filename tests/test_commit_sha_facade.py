"""Coverage for shared commit-SHA equivalence."""

from __future__ import annotations

import pytest

from sase.core.commit_sha_facade import commit_shas_equivalent

FULL_SHA = "d7e06b77b42d89ecf4bb1538c6f89c6fe700124e"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (FULL_SHA, FULL_SHA),
        ("d7e06b77b", FULL_SHA),
        (FULL_SHA, "d7e06b77b"),
        ("d7e06b7", FULL_SHA),
        ("D7E06B77B", FULL_SHA),
        ("d7e06b77b", FULL_SHA.upper()),
    ],
)
def test_commit_shas_equivalent_round_trips_binding(
    left: str,
    right: str,
) -> None:
    assert commit_shas_equivalent(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("d7e06b", FULL_SHA),
        ("", FULL_SHA),
        ("d7e06bg", FULL_SHA),
        ("d7e06b7", "e7e06b77b42d89ecf4bb1538c6f89c6fe700124e"),
        ("d7e06b77c", FULL_SHA),
    ],
)
def test_commit_shas_equivalent_rejects_invalid_or_distinct_values(
    left: str,
    right: str,
) -> None:
    assert not commit_shas_equivalent(left, right)
