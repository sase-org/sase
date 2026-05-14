"""Tests for daemon projection and indexing maintenance requests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.daemon.client import LocalDaemonClient
from tests._daemon_client_helpers import serve_one


def test_rebuild_sends_storage_reset_request(tmp_path: Path) -> None:
    request_holder: dict[str, Any] = {}
    socket_path = tmp_path / "daemon.sock"
    response = {
        "schema_version": 1,
        "request_id": "req_rebuild",
        "snapshot_id": None,
        "payload": {
            "type": "rebuild",
            "data": {
                "schema_version": 1,
                "mode": "projection_storage_rebuild",
                "storage_reset_only": True,
                "limitation": "storage reset/replay only",
                "report": {"seeded_events": 0},
            },
        },
    }
    thread = serve_one(socket_path, response, request_holder)

    result = LocalDaemonClient(socket_path, timeout=1.0).rebuild()
    thread.join(timeout=1)

    assert result["mode"] == "projection_storage_rebuild"
    assert request_holder["request"]["payload"] == {
        "type": "rebuild",
        "data": {"surface": "all", "storage_reset_only": False},
    }


def test_rebuild_can_request_explicit_storage_reset(tmp_path: Path) -> None:
    request_holder: dict[str, Any] = {}
    socket_path = tmp_path / "daemon.sock"
    response = {
        "schema_version": 1,
        "request_id": "req_rebuild",
        "snapshot_id": None,
        "payload": {
            "type": "rebuild",
            "data": {
                "schema_version": 1,
                "mode": "projection_storage_rebuild",
                "storage_reset_only": True,
                "surface": "beads",
                "project_id": "demo",
                "limitation": "storage reset/replay only",
                "report": {"seeded_events": 0},
                "summaries": [],
            },
        },
    }
    thread = serve_one(socket_path, response, request_holder)

    result = LocalDaemonClient(socket_path, timeout=1.0).rebuild(
        storage_reset_only=True,
        surface="beads",
        project_id="demo",
    )
    thread.join(timeout=1)

    assert result["storage_reset_only"] is True
    assert request_holder["request"]["payload"] == {
        "type": "rebuild",
        "data": {
            "surface": "beads",
            "project_id": "demo",
            "storage_reset_only": True,
        },
    }


def test_verify_and_diff_send_indexing_selectors(tmp_path: Path) -> None:
    verify_holder: dict[str, Any] = {}
    verify_socket = tmp_path / "verify.sock"
    verify_response = {
        "schema_version": 1,
        "request_id": "req_verify",
        "snapshot_id": None,
        "payload": {
            "type": "verify",
            "data": {
                "schema_version": 1,
                "ok": True,
                "summaries": [],
            },
        },
    }
    verify_thread = serve_one(verify_socket, verify_response, verify_holder)

    verify = LocalDaemonClient(verify_socket, timeout=1.0).verify(
        surface="agents",
        project_id="demo",
    )
    verify_thread.join(timeout=1)

    assert verify["ok"] is True
    assert verify_holder["request"]["payload"] == {
        "type": "verify",
        "data": {"surface": "agents", "project_id": "demo"},
    }

    diff_holder: dict[str, Any] = {}
    diff_socket = tmp_path / "diff.sock"
    diff_response = {
        "schema_version": 1,
        "request_id": "req_diff",
        "snapshot_id": None,
        "payload": {
            "type": "diff",
            "data": {
                "schema_version": 1,
                "surface": "beads",
                "records": [],
                "counts": {"missing": 0, "stale": 0, "extra": 0, "corrupt": 0},
                "next_cursor": None,
                "bounded": {"max_payload_bytes": 1048576, "truncated": False},
            },
        },
    }
    diff_thread = serve_one(diff_socket, diff_response, diff_holder)

    diff = LocalDaemonClient(diff_socket, timeout=1.0).diff(
        surface="beads",
        limit=7,
        cursor="14",
    )
    diff_thread.join(timeout=1)

    assert diff["records"] == []
    assert diff_holder["request"]["payload"] == {
        "type": "diff",
        "data": {
            "surface": "beads",
            "page": {"limit": 7, "cursor": "14"},
        },
    }


def test_projection_maintenance_requests(tmp_path: Path) -> None:
    checkpoint_holder: dict[str, Any] = {}
    checkpoint_socket = tmp_path / "checkpoint.sock"
    checkpoint_response = {
        "schema_version": 1,
        "request_id": "req_checkpoint",
        "snapshot_id": None,
        "payload": {
            "type": "projection_checkpoint",
            "data": {
                "schema_version": 1,
                "report": {
                    "schema_version": 1,
                    "mode": "truncate",
                    "busy": 0,
                    "log_frames": 1,
                    "checkpointed_frames": 1,
                },
            },
        },
    }
    checkpoint_thread = serve_one(
        checkpoint_socket, checkpoint_response, checkpoint_holder
    )

    checkpoint = LocalDaemonClient(checkpoint_socket, timeout=1.0).checkpoint(
        mode="truncate"
    )
    checkpoint_thread.join(timeout=1)

    assert checkpoint["report"]["mode"] == "truncate"
    assert checkpoint_holder["request"]["payload"] == {
        "type": "projection_checkpoint",
        "data": {"mode": "truncate"},
    }

    backup_holder: dict[str, Any] = {}
    backup_socket = tmp_path / "backup.sock"
    backup_response = {
        "schema_version": 1,
        "request_id": "req_backup",
        "snapshot_id": None,
        "payload": {
            "type": "projection_backup",
            "data": {
                "schema_version": 1,
                "report": {
                    "schema_version": 1,
                    "path": "/tmp/projection.sqlite",
                    "metadata_path": "/tmp/projection.sqlite.json",
                    "bytes": 10,
                    "metadata": {"event_max_sequence": 7},
                },
            },
        },
    }
    backup_thread = serve_one(backup_socket, backup_response, backup_holder)

    backup = LocalDaemonClient(backup_socket, timeout=1.0).backup(path="manual.sqlite")
    backup_thread.join(timeout=1)

    assert backup["report"]["bytes"] == 10
    assert backup_holder["request"]["payload"] == {
        "type": "projection_backup",
        "data": {"path": "manual.sqlite"},
    }

    restore_holder: dict[str, Any] = {}
    restore_socket = tmp_path / "restore.sock"
    restore_response = {
        "schema_version": 1,
        "request_id": "req_restore",
        "snapshot_id": None,
        "payload": {
            "type": "projection_restore",
            "data": {
                "schema_version": 1,
                "report": {
                    "schema_version": 1,
                    "backup_path": "/tmp/projection.sqlite",
                    "restored_path": "/tmp/run/projections/projection.sqlite",
                    "bytes": 10,
                    "replaced_existing": True,
                    "projection_only": True,
                    "metadata": {"event_max_sequence": 7},
                },
            },
        },
    }
    restore_thread = serve_one(restore_socket, restore_response, restore_holder)

    restore = LocalDaemonClient(restore_socket, timeout=1.0).restore(
        path="/tmp/projection.sqlite",
        live_recovery=True,
        allow_host_mismatch=True,
    )
    restore_thread.join(timeout=1)

    assert restore["report"]["projection_only"] is True
    assert restore_holder["request"]["payload"] == {
        "type": "projection_restore",
        "data": {
            "path": "/tmp/projection.sqlite",
            "live_recovery": True,
            "allow_host_mismatch": True,
        },
    }
