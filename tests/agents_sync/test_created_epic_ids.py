"""Publication of `created_epic_ids` as portable agent metadata."""

from __future__ import annotations

from sase.agents_sync import inventory_io
from sase.agents_sync.v2_run_io import run_metadata_from_json
from sase.agents_sync.v2_snapshot_io import decode_hood_snapshot

_OWNER = {"username": "alice", "machine_name": "athena"}
_PROJECT = {"key": "gh_sase-org__sase", "name": "sase"}


def _published_meta(metadata: dict) -> dict:
    return {
        "schema_version": 2,
        "owner": _OWNER,
        "project": _PROJECT,
        "source_run_id": "abc123",
        "local_name": "9w",
        "global_name": "alice.athena.9w",
        "metadata": metadata,
    }


def _snapshot_with_metadata(metadata: dict) -> dict:
    return {
        "schema_version": 2,
        "owner": _OWNER,
        "project": _PROJECT,
        "hood": {"local_name": "test", "global_name": "alice.athena.test"},
        "structural_ancestors": [],
        "runs": [
            {
                "source_run_id": "abc123",
                "local_name": "9w",
                "global_name": "alice.athena.9w",
                "state": "completed",
                "started_at": None,
                "finished_at": None,
                "dismissed_at": None,
                "metadata": metadata,
                "commits": [],
                "files": {},
            }
        ],
        "relationships": [],
        "containers": [],
    }


def test_recorded_created_epics_survive_portable_metadata() -> None:
    metadata = dict(
        inventory_io.portable_metadata(
            {
                "model": "gpt",
                "created_epics": [
                    {
                        "bead_id": "sase-7k",
                        "project": "sase",
                        "plan_ref": "202610/epic.md",
                        "created_at": "2026-10-06T00:00:00+00:00",
                        "via": "host_launch",
                    }
                ],
            }
        )
    )

    assert metadata["created_epic_ids"] == ["sase-7k"]
    assert "created_epics" not in metadata


def test_portable_metadata_normalizes_created_epic_ids() -> None:
    metadata = dict(
        inventory_io.portable_metadata(
            {
                "created_epic_ids": [
                    " sase-b ",
                    "sase-a",
                    "sase-a",
                    "",
                    "   ",
                    7,
                    None,
                ],
                "created_epics": [
                    {"bead_id": "sase-c"},
                    {"bead_id": "sase-a"},
                    {"bead_id": ""},
                    {"nope": 1},
                    "sase-d",
                    42,
                ],
            }
        )
    )

    assert metadata["created_epic_ids"] == ["sase-b", "sase-a", "sase-c", "sase-d"]


def test_portable_metadata_omits_empty_created_epic_ids() -> None:
    assert "created_epic_ids" not in dict(inventory_io.portable_metadata({}))
    assert "created_epic_ids" not in dict(
        inventory_io.portable_metadata({"created_epic_ids": []})
    )
    assert "created_epic_ids" not in dict(
        inventory_io.portable_metadata({"created_epic_ids": ["", "  "]})
    )
    assert "created_epic_ids" not in dict(
        inventory_io.portable_metadata({"created_epics": [{"bead_id": ""}]})
    )


def test_published_epic_ids_round_trip_through_run_metadata() -> None:
    published = dict(
        inventory_io.portable_metadata({"created_epics": [{"bead_id": "sase-7k"}]})
    )

    payload = run_metadata_from_json(_published_meta(published))

    assert dict(payload.metadata)["created_epic_ids"] == ["sase-7k"]


def test_published_epic_ids_round_trip_through_hood_snapshot() -> None:
    published = dict(
        inventory_io.portable_metadata({"created_epics": [{"bead_id": "sase-7k"}]})
    )

    snapshot = decode_hood_snapshot(_snapshot_with_metadata(published))

    assert dict(snapshot.runs[0].metadata)["created_epic_ids"] == ["sase-7k"]
