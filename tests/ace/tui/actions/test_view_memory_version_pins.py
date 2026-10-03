"""Tests for version-pinned memory hint pager sections."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.hints._view_materialize import (
    memory_version_pin_sections,
    _snapshot_section,
)


def _pin(**override: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "scope_key": "project:sase",
        "repo_root": "/tmp/repo",
        "subject": "gotchas.md",
        "revision": "v24",
        "title": "gotchas.md",
        "snapshot_path": None,
        "snapshot_title": None,
    }
    base.update(override)
    return SimpleNamespace(**base)


def test_snapshot_section_reads_stored_bytes(tmp_path: Path) -> None:
    snapshot = tmp_path / "abc123"
    snapshot.write_text("# agents v1\n", encoding="utf-8")

    section = _snapshot_section(
        str(snapshot), "AGENTS.md as launched · not in git", "AGENTS.md"
    )

    assert section is not None
    assert section.title == "AGENTS.md as launched · not in git"
    assert "# agents v1" in section.body


def test_snapshot_section_missing_bytes_is_none(tmp_path: Path) -> None:
    assert _snapshot_section(str(tmp_path / "gone"), "title", "AGENTS.md") is None


def test_snapshot_pin_opens_stored_bytes(tmp_path: Path) -> None:
    snapshot = tmp_path / ("a" * 40)
    snapshot.write_text("# agents v1\n", encoding="utf-8")
    pin = _pin(
        revision="snapshot",
        snapshot_path=str(snapshot),
        snapshot_title="AGENTS.md as launched · not in git",
    )

    sections, failures = memory_version_pin_sections((pin,))

    assert failures == []
    assert len(sections) == 1
    assert sections[0].title == "AGENTS.md as launched · not in git"


def test_snapshot_pin_missing_bytes_reports_failure(tmp_path: Path) -> None:
    pin = _pin(
        revision="snapshot",
        title="AGENTS.md as launched",
        snapshot_path=str(tmp_path / "gone"),
        snapshot_title="AGENTS.md as launched · not in git",
    )

    sections, failures = memory_version_pin_sections((pin,))

    assert sections == []
    assert failures == ["AGENTS.md as launched: snapshot unavailable"]


def test_committed_pin_builds_history_document(monkeypatch) -> None:
    from sase.memory.history import pager_provider as provider
    from sase.memory.history import service as service_module

    built: list[tuple[str, str]] = []

    class _FakeScope:
        scope_key = "project:sase"
        repo_root = "/tmp/repo"

    class _FakeService:
        def project_scope(self, root: Any) -> _FakeScope:
            return _FakeScope()

        def home_scope(self) -> None:
            return None

    def _fake_build_document(**kwargs: Any) -> SimpleNamespace:
        built.append((kwargs["subject"], kwargs["initial_revision"]))
        return SimpleNamespace(sections=[SimpleNamespace(title="v24 section")])

    monkeypatch.setattr(
        service_module, "shared_history_service", lambda: _FakeService()
    )
    monkeypatch.setattr(provider, "build_history_document", _fake_build_document)

    sections, failures = memory_version_pin_sections((_pin(),))

    assert failures == []
    assert built == [("gotchas.md", "v24")]
    assert len(sections) == 1


def test_committed_pin_failure_is_a_warning(monkeypatch) -> None:
    from sase.memory.history import pager_provider as provider
    from sase.memory.history import service as service_module

    class _FakeScope:
        scope_key = "project:sase"
        repo_root = "/tmp/repo"

    class _FakeService:
        def project_scope(self, root: Any) -> _FakeScope:
            return _FakeScope()

        def home_scope(self) -> None:
            return None

    def _boom(**kwargs: Any) -> Any:
        raise ValueError("no version blob:dead for subject")

    monkeypatch.setattr(
        service_module, "shared_history_service", lambda: _FakeService()
    )
    monkeypatch.setattr(provider, "build_history_document", _boom)

    sections, failures = memory_version_pin_sections((_pin(),))

    assert sections == []
    assert len(failures) == 1
    assert "v24" in failures[0]


def test_empty_pins_build_nothing() -> None:
    assert memory_version_pin_sections(()) == ([], [])
