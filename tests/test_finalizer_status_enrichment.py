"""Tests for the finalizer_status row-summary mirror (plan §4.7).

The same fixture must produce an equal ``Agent.finalizer_status`` through
both the snapshot (wire) and filesystem enrichment paths, dedup must carry
the field, and session containers must never mirror it.
"""

import json
from pathlib import Path

from sase.ace.tui.models._dedup import _merge_agent_fields
from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import (
    FinalizerStatusSummaryWire,
    agent_scan_wire_from_dict,
    finalizer_status_from_mapping,
)
from tests._enrich_agent_helpers import make_agent

STATUS_FIXTURE = {
    "schema_version": 1,
    "phase": "executing",
    "status": "failed",
    "run_id": "abc123",
    "instances": [{"id": "commit", "status": "running", "op": "stitch main"}],
    "instance_count": 1,
}


def _wire_meta(raw: object):
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": 10,
            "projects_root": "/tmp/projects",
            "records": [
                {
                    "project_name": "proj",
                    "project_dir": "/tmp/projects/proj",
                    "project_file": "/tmp/projects/proj/proj.sase",
                    "workflow_dir_name": "ace-run",
                    "artifact_dir": "/tmp/projects/proj/artifacts/ace-run/1",
                    "timestamp": "1",
                    "agent_meta": {"finalizer_status": raw},
                }
            ],
        }
    )
    record = snapshot.records[0]
    assert record.agent_meta is not None
    return record.agent_meta


def test_snapshot_and_filesystem_paths_agree(tmp_path: Path) -> None:
    """The same fixture produces an equal Agent.finalizer_status either way."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"finalizer_status": STATUS_FIXTURE})
    )

    fs_agent = make_agent()
    enrich_agent_from_meta(fs_agent, str(tmp_path))

    wire_agent = make_agent()
    enrich_agent_from_meta_wire(wire_agent, _wire_meta(STATUS_FIXTURE), None)

    assert fs_agent.finalizer_status is not None
    assert fs_agent.finalizer_status == wire_agent.finalizer_status
    assert fs_agent.finalizer_status.phase == "executing"
    assert [entry.id for entry in fs_agent.finalizer_status.instances] == ["commit"]


def test_malformed_summary_leaves_field_unset(tmp_path: Path) -> None:
    """A malformed summary degrades to None on both paths, never an error."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"finalizer_status": {"status": "failed"}})
    )

    fs_agent = make_agent()
    enrich_agent_from_meta(fs_agent, str(tmp_path))

    wire_agent = make_agent()
    enrich_agent_from_meta_wire(wire_agent, _wire_meta({"status": "failed"}), None)

    assert fs_agent.finalizer_status is None
    assert wire_agent.finalizer_status is None


def test_missing_summary_leaves_field_unset(tmp_path: Path) -> None:
    """Legacy markers without the key keep finalizer_status None."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))

    fs_agent = make_agent()
    enrich_agent_from_meta(fs_agent, str(tmp_path))

    wire_agent = make_agent()
    enrich_agent_from_meta_wire(wire_agent, _wire_meta(None), None)

    assert fs_agent.finalizer_status is None
    assert wire_agent.finalizer_status is None


def test_dedup_carries_finalizer_status() -> None:
    """Dedup merges the summary onto rows that lack it, without overwriting."""
    source = make_agent()
    source.finalizer_status = finalizer_status_from_mapping(STATUS_FIXTURE)

    target = make_agent()
    _merge_agent_fields(target, source)
    assert target.finalizer_status == source.finalizer_status

    other = finalizer_status_from_mapping({"phase": "settled", "status": "success"})
    keeper = make_agent()
    keeper.finalizer_status = other
    _merge_agent_fields(keeper, source)
    assert keeper.finalizer_status == other


def test_containers_do_not_mirror(tmp_path: Path) -> None:
    """Clan, imported, and pure session containers never carry the summary."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"finalizer_status": STATUS_FIXTURE})
    )
    wire_meta = _wire_meta(STATUS_FIXTURE)

    clan = make_agent()
    clan.is_clan_container = True
    enrich_agent_from_meta(clan, str(tmp_path))
    assert clan.finalizer_status is None

    clan_wire = make_agent()
    clan_wire.is_clan_container = True
    enrich_agent_from_meta_wire(clan_wire, wire_meta, None)
    assert clan_wire.finalizer_status is None

    imported = make_agent()
    imported.is_imported_agent_session_container = True
    enrich_agent_from_meta(imported, str(tmp_path))
    assert imported.finalizer_status is None

    # A session root that is only a container label (name == session name)
    # does not represent a member, so mirroring would double-count.
    pure_root = make_agent()
    pure_root.agent_session = "sess"
    pure_root.agent_session_role = "root"
    pure_root.agent_name = "sess"
    enrich_agent_from_meta(pure_root, str(tmp_path))
    assert pure_root.finalizer_status is None

    pure_root_wire = make_agent()
    pure_root_wire.agent_session = "sess"
    pure_root_wire.agent_session_role = "root"
    pure_root_wire.agent_name = "sess"
    enrich_agent_from_meta_wire(pure_root_wire, wire_meta, None)
    assert pure_root_wire.finalizer_status is None


def test_root_representing_member_keeps_summary(tmp_path: Path) -> None:
    """A session root that is also a concrete turn keeps its own summary."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"finalizer_status": STATUS_FIXTURE})
    )

    root = make_agent()
    root.agent_session = "sess"
    root.agent_session_role = "root"
    root.agent_name = "sess.code1"
    enrich_agent_from_meta(root, str(tmp_path))

    assert root.finalizer_status is not None
    assert isinstance(root.finalizer_status, FinalizerStatusSummaryWire)
    assert root.finalizer_status.phase == "executing"


def test_bundle_round_trips_finalizer_status() -> None:
    """Dismissed bundles persist the summary as JSON-native data."""
    agent = make_agent()
    agent.finalizer_status = finalizer_status_from_mapping(STATUS_FIXTURE)

    payload = json.loads(json.dumps(agent.to_bundle_dict()))

    from sase.ace.tui.models.agent_bundle import from_bundle_dict

    revived = from_bundle_dict(payload)
    assert revived.finalizer_status == agent.finalizer_status
    assert revived.finalizer_status is not None
    assert revived.finalizer_status.phase == "executing"
    assert [entry.id for entry in revived.finalizer_status.instances] == ["commit"]
