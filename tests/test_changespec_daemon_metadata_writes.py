"""Daemon routing for ChangeSpec hook, mentor, and archive metadata writes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.ace.changespec import HookEntry
from sase.ace.changespec.archive import move_changespec_to_file
from sase.ace.hooks.persistence import update_changespec_hooks_field
from sase.ace.mentors.status import set_mentor_status


class _ExportingDaemonClient:
    instances: list[_ExportingDaemonClient] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.requests: list[dict[str, Any]] = []
        self.instances.append(self)

    def capabilities(self) -> dict[str, Any]:
        return {"schema_version": 1, "capabilities": ["changespecs.write"]}

    def write(self, surface: str, data: dict[str, Any]) -> dict[str, Any]:
        self.requests.append({"surface": surface, "data": data})
        for export in data.get("source_exports", []):
            target = Path(export["target_path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(export["content_utf8"], encoding="utf-8")
        return {
            "schema_version": 1,
            "surface": surface,
            "outcome": {
                "schema_version": 1,
                "event_seq": 1,
                "event_type": "changespec.test",
                "duplicate": False,
                "changed": True,
                "resource_handle": "changespec:test:demo",
                "source_exports": [],
                "projection_snapshot": None,
            },
            "fallback": {"available": False, "reason": None, "message": None},
        }


def _install_exporting_daemon(monkeypatch: Any) -> type[_ExportingDaemonClient]:
    _ExportingDaemonClient.instances = []
    monkeypatch.setattr(
        "sase.daemon.write_facade.LocalDaemonClient", _ExportingDaemonClient
    )
    return _ExportingDaemonClient


def test_hook_field_update_routes_through_changespec_daemon_write(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client_class = _install_exporting_daemon(monkeypatch)
    project_file = tmp_path / "project.sase"
    project_file.write_text("NAME: demo\nSTATUS: Ready\n", encoding="utf-8")

    assert update_changespec_hooks_field(
        str(project_file), "demo", [HookEntry("pytest")]
    )

    request = client_class.instances[-1].requests[-1]
    assert request["surface"] == "changespec.hooks"
    assert request["data"]["payload"]["section_names"] == ["hooks"]
    assert "HOOKS:\n  pytest\n" in project_file.read_text(encoding="utf-8")


def test_mentor_status_update_routes_through_changespec_daemon_write(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client_class = _install_exporting_daemon(monkeypatch)
    project_file = tmp_path / "project.sase"
    project_file.write_text("NAME: demo\nSTATUS: Ready\n", encoding="utf-8")

    assert set_mentor_status(
        str(project_file),
        "demo",
        "1",
        "quality",
        "complete",
        "PASSED",
        duration="3s",
    )

    request = client_class.instances[-1].requests[-1]
    assert request["surface"] == "changespec.mentor_status"
    assert request["data"]["payload"]["section_names"] == ["mentors"]
    content = project_file.read_text(encoding="utf-8")
    assert "MENTORS:" in content
    assert "quality:complete - PASSED" in content


def test_archive_move_routes_both_exports_and_locks_paths_in_order(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client_class = _install_exporting_daemon(monkeypatch)
    source_file = tmp_path / "z-project.sase"
    dest_file = tmp_path / "a-project-archive.sase"
    source_file.write_text(
        "NAME: keep\nSTATUS: Ready\n\nNAME: demo\nSTATUS: Archived\n",
        encoding="utf-8",
    )

    acquired: list[str] = []

    @contextmanager
    def fake_lock(path: str, *args: Any, **kwargs: Any) -> Iterator[None]:
        del args, kwargs
        acquired.append(str(Path(path).resolve()))
        yield

    monkeypatch.setattr("sase.ace.changespec.archive.changespec_lock", fake_lock)

    assert move_changespec_to_file(str(source_file), str(dest_file), "demo")

    assert acquired == sorted({str(source_file.resolve()), str(dest_file.resolve())})
    request = client_class.instances[-1].requests[-1]
    assert request["surface"] == "changespec.active_archive_moved"
    assert [export["target_path"] for export in request["data"]["source_exports"]] == [
        str(source_file),
        str(dest_file),
    ]
    assert "NAME: demo" not in source_file.read_text(encoding="utf-8")
    assert "NAME: demo" in dest_file.read_text(encoding="utf-8")
