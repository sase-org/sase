"""Tests for daemon-backed ACE ChangeSpec provider reads."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.changespec._loading import ChangeSpecLoadingMixin
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_to_wire
from sase.daemon.client import LocalDaemonClient


class _FakeDaemonTransport:
    def __init__(self, changespecs: list[ChangeSpec]) -> None:
        self.reads = _reads_for(changespecs)
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        if payload["type"] == "capabilities":
            return _response(
                "capabilities",
                {"schema_version": 1, "capabilities": ["changespecs.read"]},
            )
        if payload["type"] == "read":
            surface = payload["data"]["surface"]
            return _response(
                "read", {"surface": surface, "data": self.reads[surface].pop(0)}
            )
        raise AssertionError(f"unexpected request: {payload}")


class _FakeApp(ChangeSpecLoadingMixin):
    def __init__(self, client: LocalDaemonClient) -> None:
        self._daemon_read_client = client


def test_ace_changespec_provider_uses_daemon_without_broad_disk_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changespec = _cs("proj_daemon")
    transport = _FakeDaemonTransport([changespec])
    app = _FakeApp(LocalDaemonClient(transport=transport))
    monkeypatch.setattr(
        "sase.ace.changespec.find_all_changespecs_cached",
        lambda: (_ for _ in ()).throw(AssertionError("broad changespec scan")),
    )

    result = app._read_changespecs_from_provider()

    assert [cs.name for cs in result] == ["proj_daemon"]
    assert app._changespec_provider_used_daemon is True
    assert [request["data"]["surface"] for request in transport.requests[1:]] == [
        "changespec_list",
        "changespec_detail",
    ]


def _cs(name: str) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="daemon detail",
        parent="parent_spec",
        cl=None,
        status="Ready",
        file_path="/home/user/.sase/projects/proj/proj.sase",
        line_number=7,
    )


def _reads_for(changespecs: list[ChangeSpec]) -> dict[str, list[dict[str, Any]]]:
    summaries = [
        _summary(cs, handle=f"changespec:{cs.project_basename}:{cs.name}")
        for cs in changespecs
    ]
    return {
        "changespec_list": [_list_page(summaries)],
        "changespec_detail": [
            _detail_page(cs, handle=f"changespec:{cs.project_basename}:{cs.name}")
            for cs in changespecs
        ],
    }


def _summary(cs: ChangeSpec, *, handle: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "handle": handle,
        "project_id": cs.project_basename,
        "name": cs.name,
        "project_basename": cs.project_basename,
        "file_path": cs.file_path,
        "source_path": cs.file_path,
        "is_archive": False,
        "status": cs.status,
        "parent": cs.parent,
        "cl_or_pr": cs.cl,
        "bug": cs.bug,
        "updated_at": "2026-05-14T00:00:00Z",
        "last_seq": 1,
    }


def _list_page(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-changespecs"},
        "page": {"schema_version": 1, "next_cursor": None},
        "entries": {"schema_version": 1, "entries": entries, "next_offset": None},
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _detail_page(cs: ChangeSpec, *, handle: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-changespecs"},
        "detail": {
            "schema_version": 1,
            "summary": _summary(cs, handle=handle),
            "spec": to_json_dict(changespec_to_wire(cs)),
            "sections": [],
        },
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": payload_type, "data": data},
    }
