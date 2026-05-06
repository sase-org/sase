"""Public artifact facade API surface tests."""

from __future__ import annotations

from sase.core import artifact_facade


def test_artifact_facade_write_helpers_are_public_api() -> None:
    assert callable(artifact_facade.artifact_path_upsert_request)
    assert callable(artifact_facade.artifact_remove)
    assert callable(artifact_facade.artifact_upsert_path)
