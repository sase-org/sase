"""Publication of `wait_for_beads` as portable agent metadata."""

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


def test_live_wait_for_beads_survive_portable_metadata() -> None:
    metadata = dict(
        inventory_io.portable_metadata(
            {"model": "gpt", "wait_for_beads": ["sase-17m.1", "sase-17m.2"]}
        )
    )

    assert metadata["wait_for_beads"] == ["sase-17m.1", "sase-17m.2"]


def test_portable_metadata_normalizes_bead_waits() -> None:
    metadata = dict(
        inventory_io.portable_metadata(
            {
                "wait_for_beads": [
                    " sase-b ",
                    "sase-a",
                    "sase-a",
                    "",
                    "   ",
                    7,
                    None,
                ]
            }
        )
    )

    assert metadata["wait_for_beads"] == ["sase-b", "sase-a"]


def test_portable_metadata_omits_empty_bead_waits() -> None:
    assert "wait_for_beads" not in dict(inventory_io.portable_metadata({}))
    assert "wait_for_beads" not in dict(
        inventory_io.portable_metadata({"wait_for_beads": []})
    )
    assert "wait_for_beads" not in dict(
        inventory_io.portable_metadata({"wait_for_beads": ["", "  "]})
    )


def test_dismissed_waiting_for_beads_alias_is_normalized() -> None:
    metadata = dict(inventory_io.portable_metadata({"waiting_for_beads": ["sase-xx"]}))

    assert metadata["wait_for_beads"] == ["sase-xx"]


def test_published_waits_round_trip_through_run_metadata() -> None:
    published = dict(inventory_io.portable_metadata({"wait_for_beads": ["sase-xx"]}))

    payload = run_metadata_from_json(_published_meta(published))

    assert dict(payload.metadata)["wait_for_beads"] == ["sase-xx"]


def test_published_waits_round_trip_through_hood_snapshot() -> None:
    published = dict(inventory_io.portable_metadata({"wait_for_beads": ["sase-xx"]}))

    snapshot = decode_hood_snapshot(_snapshot_with_metadata(published))

    assert dict(snapshot.runs[0].metadata)["wait_for_beads"] == ["sase-xx"]
