"""Stale-binding fallbacks for registry entries newer than the installed core."""

from __future__ import annotations

import pytest

from sase.sdd._artifact_link_store_support import (
    artifact_relation_label_with_fallback,
    lookup_artifact_relation_with_fallback,
)


def test_lookup_falls_back_to_the_assembled_registry() -> None:
    info = lookup_artifact_relation_with_fallback("awaits")

    assert info["slug"] == "awaits"
    assert info["inverse"] == "awaited-by"
    assert info["written_by"] == "projection"


def test_lookup_still_rejects_truly_unknown_slugs() -> None:
    with pytest.raises((ValueError, TypeError, RuntimeError, AttributeError)):
        lookup_artifact_relation_with_fallback("bogus-relation")


def test_label_falls_back_from_both_perspectives() -> None:
    assert artifact_relation_label_with_fallback("awaits", True) == "awaits"
    assert artifact_relation_label_with_fallback("awaits", False) == "awaited-by"


def test_label_still_rejects_truly_unknown_slugs() -> None:
    with pytest.raises((ValueError, TypeError, RuntimeError, AttributeError)):
        artifact_relation_label_with_fallback("bogus-relation", True)
