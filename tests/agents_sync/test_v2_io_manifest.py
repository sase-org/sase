from __future__ import annotations

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import (
    MAX_MANIFEST_HOODS,
    MAX_MANIFEST_JSON_BYTES,
    _owner_manifest_from_json,
    check_manifest_write_size,
    v2_json_bytes,
    validate_relative_path,
)
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")


def test_owner_manifest_and_path_validation_are_strict() -> None:
    manifest = V2OwnerManifest(OWNER, PROJECT)
    assert _owner_manifest_from_json(manifest.to_json_dict()) == manifest

    malformed = manifest.to_json_dict()
    malformed["owner"] = {"username": "Alice", "machine_name": "athena"}
    with pytest.raises(AgentsSyncFormatError, match="invalid owner"):
        _owner_manifest_from_json(malformed)

    for unsafe in ("../escape", "/absolute", "users//manifest.json", ".secret"):
        with pytest.raises(AgentsSyncFormatError):
            validate_relative_path(unsafe)
    assert validate_relative_path("agents/.gitkeep") == "agents/.gitkeep"


def test_owner_manifest_decode_is_forward_compatible_and_self_healing() -> None:
    manifest = V2OwnerManifest(
        OWNER,
        PROJECT,
        (
            (
                "foo",
                V2OwnerHoodEntry(
                    "a" * 64,
                    (
                        "agents/alice.athena.foo/README.md",
                        "users/alice/machines/athena/hoods/foo/snapshot.json",
                    ),
                    1,
                    0,
                ),
            ),
        ),
    )
    encoded = manifest.to_json_dict()
    encoded["compatibility_aliases"] = []
    encoded["hoods"]["foo"]["future_field"] = "ignored"  # type: ignore[index]

    decoded = _owner_manifest_from_json(encoded)

    assert decoded == manifest
    healed = decoded.to_json_dict()
    assert "compatibility_aliases" not in healed
    assert "future_field" not in healed["hoods"]["foo"]  # type: ignore[index]

    missing = manifest.to_json_dict()
    missing.pop("project")
    with pytest.raises(AgentsSyncFormatError, match="missing required keys: project"):
        _owner_manifest_from_json(missing)


def test_owner_manifest_hood_entries_decode_fat_and_slim_shapes() -> None:
    fat = V2OwnerManifest(
        OWNER,
        PROJECT,
        (
            (
                "foo",
                V2OwnerHoodEntry(
                    "a" * 64,
                    (
                        "agents/alice.athena.foo/README.md",
                        "users/alice/machines/athena/hoods/foo/snapshot.json",
                    ),
                    1,
                    0,
                ),
            ),
        ),
    )
    slim = V2OwnerManifest(
        OWNER,
        PROJECT,
        (("bar", V2OwnerHoodEntry("b" * 64, None, 2, 1)),),
    )

    fat_encoded = fat.to_json_dict()
    assert "files" in fat_encoded["hoods"]["foo"]  # type: ignore[index]
    assert _owner_manifest_from_json(fat_encoded) == fat

    slim_encoded = slim.to_json_dict()
    assert "files" not in slim_encoded["hoods"]["bar"]  # type: ignore[index]
    decoded_slim = _owner_manifest_from_json(slim_encoded)
    assert decoded_slim == slim
    assert decoded_slim.hoods[0][1].files is None

    # A slim entry round-trips byte-for-byte: re-encoding never resurrects
    # the omitted key.
    assert v2_json_bytes(decoded_slim.to_json_dict()) == v2_json_bytes(slim_encoded)

    missing_run_count = slim_encoded["hoods"]["bar"].copy()  # type: ignore[index]
    del missing_run_count["run_count"]
    broken = {**slim_encoded, "hoods": {"bar": missing_run_count}}
    with pytest.raises(AgentsSyncFormatError, match="missing required keys: run_count"):
        _owner_manifest_from_json(broken)


def test_owner_manifest_uses_dedicated_larger_read_caps() -> None:
    from sase.agents_sync import v2_io, v2_validation

    assert v2_validation.MAX_MANIFEST_JSON_BYTES is MAX_MANIFEST_JSON_BYTES
    assert v2_validation.MAX_MANIFEST_HOODS is MAX_MANIFEST_HOODS
    assert MAX_MANIFEST_JSON_BYTES > v2_io.MAX_JSON_BYTES
    assert MAX_MANIFEST_HOODS > v2_io.MAX_CONTAINERS

    many_hoods = V2OwnerManifest(
        OWNER,
        PROJECT,
        tuple(
            (f"hood{index:05d}", V2OwnerHoodEntry("a" * 64, None, 0, 0))
            for index in range(v2_io.MAX_CONTAINERS + 1)
        ),
    )
    encoded = many_hoods.to_json_dict()
    # Exceeds the old MAX_CONTAINERS cap but stays under MAX_MANIFEST_HOODS.
    assert _owner_manifest_from_json(encoded).hoods == many_hoods.hoods

    too_many = {
        **encoded,
        "hoods": {
            f"hood{index:05d}": {"digest": "a" * 64, "run_count": 0, "family_count": 0}
            for index in range(MAX_MANIFEST_HOODS + 1)
        },
    }
    with pytest.raises(AgentsSyncFormatError, match="too many hoods"):
        _owner_manifest_from_json(too_many)


def test_owner_manifest_write_guard_rejects_oversized_writes() -> None:
    check_manifest_write_size(0, b"{}")

    with pytest.raises(AgentsSyncFormatError, match="byte read cap"):
        check_manifest_write_size(0, b"x" * (MAX_MANIFEST_JSON_BYTES + 1))

    with pytest.raises(AgentsSyncFormatError, match="hood read cap"):
        check_manifest_write_size(MAX_MANIFEST_HOODS + 1, b"{}")


def test_old_reader_lenient_skips_a_slim_manifest_entry() -> None:
    """Freeze the pre-slim per-hood decode contract.

    Before this change, every hood entry's shape was checked with
    ``compatible_object(..., {"digest", "files", "run_count",
    "family_count"})``, which requires every one of those keys. A slim entry
    (files omitted) fails that check, so an old sase binary's
    ``read_all_owner_manifests_lenient`` catches the resulting
    ``AgentsSyncFormatError`` and skips just that manifest instead of
    hard-failing the whole read. This is the compatibility promise that lets
    a slim manifest roll out before every owner machine upgrades: keep it
    locked in by re-running that frozen legacy shape check directly.
    """
    from sase.agents_sync.v2_validation import compatible_object

    def _legacy_hood_entry_shape_check(raw_entry: object, hood: str) -> None:
        compatible_object(
            raw_entry,
            f"hood {hood!r}",
            {"digest", "files", "run_count", "family_count"},
        )

    slim_entry = {"digest": "a" * 64, "run_count": 1, "family_count": 0}
    with pytest.raises(AgentsSyncFormatError, match="missing required keys: files"):
        _legacy_hood_entry_shape_check(slim_entry, "foo")

    fat_entry = {**slim_entry, "files": []}
    _legacy_hood_entry_shape_check(fat_entry, "foo")  # does not raise
