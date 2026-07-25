from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.io import (
    AgentsSyncFormatError,
    _compute_bundle_digest,
    _manifest_from_json,
    _portable_metadata_from_json,
    atomic_write_json,
    read_manifest,
)
from sase.agents_sync.models import AgentsManifest, CommitRecord, ManifestEntry


def _meta(**updates: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": 1,
        "name": "athena.worker",
        "machine": "athena",
        "artifact_timestamp": "20260722123456",
        "artifact_layout_version": 2,
        "model": "gpt-test",
    }
    data.update(updates)
    return data


def test_digest_is_canonical_and_chat_bytes_are_exact() -> None:
    left = _portable_metadata_from_json(_meta())
    right = _portable_metadata_from_json(
        {
            "model": "gpt-test",
            "artifact_layout_version": 2,
            "artifact_timestamp": "20260722123456",
            "machine": "athena",
            "name": "athena.worker",
            "schema_version": 1,
        }
    )
    commits = (CommitRecord("a" * 40, "subject", 42),)

    assert _compute_bundle_digest(left, commits, b"chat\n") == _compute_bundle_digest(
        right, commits, b"chat\n"
    )
    assert _compute_bundle_digest(left, commits, b"chat\n") != _compute_bundle_digest(
        left, commits, b"chat"
    )


@pytest.mark.parametrize(
    "update,match",
    [
        ({"schema_version": 2}, "schema_version"),
        ({"name": "../escape"}, "unsafe"),
        ({"name": "zeus.worker"}, "does not belong"),
        ({"workspace_dir": "/private/path"}, "unsupported fields"),
    ],
)
def test_portable_metadata_rejects_untrusted_shapes(
    update: dict[str, object], match: str
) -> None:
    with pytest.raises(AgentsSyncFormatError, match=match):
        _portable_metadata_from_json(_meta(**update))


def test_manifest_rejects_key_identity_mismatch_and_unsafe_paths() -> None:
    entry = {
        "schema_version": 1,
        "name": "athena.worker",
        "machine": "athena",
        "digest": "0" * 64,
        "artifact_timestamp": "20260722123456",
        "updated_at": "2026-07-22T12:34:56+00:00",
    }
    with pytest.raises(AgentsSyncFormatError, match="does not match"):
        _manifest_from_json({"schema_version": 1, "agents": {"athena.other": entry}})
    with pytest.raises(AgentsSyncFormatError, match="unsafe"):
        _manifest_from_json({"schema_version": 1, "agents": {"../worker": entry}})


def test_manifest_json_write_is_an_atomic_round_trip(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    manifest = AgentsManifest(
        (
            ManifestEntry(
                "athena.worker",
                "athena",
                "1" * 64,
                "20260722123456",
                "2026-07-22T12:34:56+00:00",
            ),
        )
    )
    atomic_write_json(path, manifest.to_json_dict())
    assert read_manifest(path) == manifest
    assert json.loads(path.read_text()) == manifest.to_json_dict()
    assert not list(tmp_path.glob(".*.tmp"))
