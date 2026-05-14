"""Tests for daemon-backed ``sase changespec`` read routing."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from sase.ace.changespec import ChangeSpec
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_to_wire
from sase.daemon.changespec_reads import load_changespecs_from_daemon
from sase.daemon.client import LocalDaemonClient
from sase.daemon import read_facade
from sase.main.changespec_handler import _handle_current
from sase.main.parser import create_parser
from sase.main.search_handler import handle_search_command


class _FakeDaemonTransport:
    def __init__(self, *, reads: dict[str, list[dict[str, Any]]]) -> None:
        self.reads = reads
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


class _FakeProvider:
    def __init__(self, *, branch: str | None = None, url: str | None = None) -> None:
        self.branch = branch
        self.url = url

    def get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        return (self.branch is not None, self.branch)

    def get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        return (self.url is not None, self.url)

    def derive_branch_name(self, changespec_name: str, project_basename: str) -> str:
        return changespec_name.removeprefix(f"{project_basename}_")

    def derive_branch_name_with_suffix(
        self, changespec_name: str, project_basename: str
    ) -> str:
        return changespec_name.removeprefix(f"{project_basename}_")


@pytest.fixture(autouse=True)
def _fresh_daemon_read_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        read_facade,
        "_PROCESS_READ_SESSION",
        read_facade._DaemonReadSession(),
    )


def test_changespec_parser_accepts_no_daemon_flags() -> None:
    current = create_parser().parse_args(["changespec", "current", "--no-daemon"])
    search = create_parser().parse_args(
        ["changespec", "search", '"feature"', "--no-daemon"]
    )

    assert current.no_daemon is True
    assert search.no_daemon is True


def test_load_changespecs_from_daemon_rehydrates_detail_records() -> None:
    changespec = _cs("proj_daemon", description="daemon detail")
    transport = _FakeDaemonTransport(reads=_reads_for([changespec]))

    result = load_changespecs_from_daemon(LocalDaemonClient(transport=transport))

    assert [cs.name for cs in result] == ["proj_daemon"]
    assert result[0].description == "daemon detail"
    assert result[0].line_number == 7
    assert [request["data"]["surface"] for request in transport.requests] == [
        "changespec_list",
        "changespec_detail",
    ]


def test_changespec_current_uses_daemon_when_available(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = "https://github.com/sase-org/sase/pull/123"
    transport = _FakeDaemonTransport(reads=_reads_for([_cs("proj_daemon", cl=url)]))
    monkeypatch.setattr(
        "sase.daemon.read_facade.LocalDaemonClient",
        lambda: LocalDaemonClient(transport=transport),
    )
    monkeypatch.setattr(
        "sase.main.changespec_handler.find_all_changespecs",
        lambda: _raise_direct_scan(),
    )
    monkeypatch.setattr(
        "sase.main.changespec_handler.get_project_from_workspace",
        lambda: "proj",
    )
    monkeypatch.setattr(
        "sase.main.changespec_handler.get_vcs_provider",
        lambda cwd: _FakeProvider(branch="other", url=url),
    )

    code = _handle_current(
        argparse.Namespace(format="json", project_file=None, no_daemon=False)
    )
    captured = capsys.readouterr()

    assert code == 0
    assert json.loads(captured.out)["name"] == "proj_daemon"
    assert transport.requests[1]["data"]["data"]["project_id"] == "proj"


def test_changespec_search_uses_daemon_when_available(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = _FakeDaemonTransport(
        reads=_reads_for([_cs("proj_daemon", description="from daemon")])
    )
    monkeypatch.setattr(
        "sase.daemon.read_facade.LocalDaemonClient",
        lambda: LocalDaemonClient(transport=transport),
    )
    monkeypatch.setattr(
        "sase.ace.changespec.find_all_changespecs",
        lambda: _raise_direct_scan(),
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_search_command(
            argparse.Namespace(
                query='"daemon"',
                format="markdown",
                no_daemon=False,
            )
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "proj_daemon" in captured.out
    assert "from daemon" in captured.out


def _cs(
    name: str,
    *,
    description: str = "test",
    project: str = "proj",
    cl: str | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description=description,
        parent="parent_spec",
        cl=cl,
        status="Ready",
        file_path=f"/home/user/.sase/projects/{project}/{project}.sase",
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


def _raise_direct_scan() -> None:
    raise AssertionError("direct ChangeSpec scan should not run")
