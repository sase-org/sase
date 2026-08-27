from __future__ import annotations

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    agent_scan_wire_from_dict,
    agent_scan_wire_to_json_dict,
)

from .core_agent_scan_wire_helpers import record_payload


def test_used_xprompts_round_trip_survives_the_json_projection() -> None:
    """Index staleness is diffed on the projected dict, so it must carry usage.

    ``verify_agent_artifact_index`` compares a fresh scan against the cached
    index through :func:`agent_scan_wire_to_json_dict`. Dropping
    ``used_xprompts`` here would report a row seeded with a late
    ``xprompts.json`` as fresh even though the cached projection is empty.
    """
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                record_payload(
                    used_xprompts=[
                        {
                            "name": "gh",
                            "kind": "workflow",
                            "tags": ["rollover", "vcs"],
                            "references": 2,
                            "added_by_newer_writer": 1,
                        },
                        {"name": "split_file", "kind": "part", "references": 1},
                    ]
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert [used.name for used in record.used_xprompts] == ["gh", "split_file"]
    assert record.used_xprompts[0].kind == "workflow"
    assert record.used_xprompts[0].tags == ["rollover", "vcs"]
    assert record.used_xprompts[0].references == 2
    assert record.used_xprompts[1].tags == []
    assert not hasattr(record.used_xprompts[0], "added_by_newer_writer")

    projected = agent_scan_wire_to_json_dict(record)
    assert projected["used_xprompts"] == [
        {
            "name": "gh",
            "kind": "workflow",
            "tags": ["rollover", "vcs"],
            "references": 2,
        },
        {"name": "split_file", "kind": "part", "tags": [], "references": 1},
    ]


def test_used_xprompts_defaults_to_empty_for_older_payloads() -> None:
    """An older core build reports no usage rather than failing the scan."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [record_payload(), record_payload(used_xprompts=None)],
        }
    )

    assert [record.used_xprompts for record in snapshot.records] == [[], []]
