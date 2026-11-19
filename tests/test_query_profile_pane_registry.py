"""Memoized built-in pane query profiles (phase ui_cpu_caches)."""

from __future__ import annotations

import dataclasses

import pytest

from sase.ace.query_profile import compiler as compiler_mod
from sase.ace.query_profile import pane_registry as registry_mod
from sase.ace.query_profile import (
    clear_compiled_builtin_pane_cache,
    compiled_profile_for_builtin_pane,
)


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_compiled_builtin_pane_cache()
    yield
    clear_compiled_builtin_pane_cache()


def test_builtin_pane_profile_memoized_per_pane_id() -> None:
    first = compiled_profile_for_builtin_pane("agents")
    assert first is not None
    second = compiled_profile_for_builtin_pane("agents")
    assert second is first


def test_all_builtin_panes_compile_and_memoize() -> None:
    for pane_id in sorted(registry_mod._BUILTIN_SCHEMA_BUILDERS):
        first = compiled_profile_for_builtin_pane(pane_id)
        assert first is not None, pane_id
        assert compiled_profile_for_builtin_pane(pane_id) is first, pane_id


def test_memoized_profile_matches_fresh_compilation() -> None:
    cached = compiled_profile_for_builtin_pane("patches")
    assert cached is not None
    module = __import__(
        "sase.ace.query_profile.profiles._patches",
        fromlist=["patches_query_schema"],
    )
    fresh = compiler_mod.compile_query_profile(module.patches_query_schema())
    assert cached == fresh
    assert cached.digest == fresh.digest


def test_unknown_pane_id_returns_none_without_poisoning_cache() -> None:
    assert compiled_profile_for_builtin_pane("ref:unknown-kind") is None
    assert compiled_profile_for_builtin_pane("ref:unknown-kind") is None
    known = compiled_profile_for_builtin_pane("beads")
    assert known is not None
    assert compiled_profile_for_builtin_pane("beads") is known


def test_clear_cache_rebuilds_equal_profile() -> None:
    before = compiled_profile_for_builtin_pane("files")
    assert before is not None
    clear_compiled_builtin_pane_cache()
    after = compiled_profile_for_builtin_pane("files")
    assert after is not None
    assert after is not before
    assert after == before
    assert after.digest == before.digest


def test_shared_profile_instances_are_immutable() -> None:
    profile = compiled_profile_for_builtin_pane("procs")
    assert profile is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.digest = "tampered"  # type: ignore[misc]
