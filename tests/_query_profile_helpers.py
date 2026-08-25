"""Shared helpers for query profile tests."""

from __future__ import annotations

from sase.ace.query_profile import CompiledQueryProfile
from sase.ace.query_profile.registry import HOST_PREDICATES


def assert_closed_host_predicates(profile: CompiledQueryProfile) -> None:
    assert profile.predicates == tuple(sorted(HOST_PREDICATES))
    assert profile.any_special is True
