"""Tests for ``sase.core.project_lifecycle_facade``."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import project_lifecycle_facade
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    normalize_project_lifecycle_state,
    normalize_project_lifecycle_state_filter,
    project_lifecycle_from_dict,
    project_lifecycle_wire_to_json_dict,
    project_record_from_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from tests.test_core_facade._helpers import force_no_rust_extension


def _lifecycle_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "state": "active",
        "explicit": False,
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _record_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "project_name": "alpha",
        "project_dir": "/tmp/projects/alpha",
        "project_file": "/tmp/projects/alpha/alpha.sase",
        "archive_file": None,
        "workspace_dir": "/tmp/workspace",
        "state": "active",
        "state_explicit": False,
        "system_managed": False,
        "active_claim_count": 0,
        "launchable": True,
        "aliases": [],
        "warnings": [],
        "parse_warnings": [],
    }
    payload.update(overrides)
    return payload


def test_project_lifecycle_wire_dict_conversion() -> None:
    wire = project_lifecycle_from_dict(
        _lifecycle_payload(state="inactive", explicit=True, warnings=["manual"])
    )

    assert wire.state == "inactive"
    assert wire.explicit is True
    assert wire.warnings == ["manual"]
    assert project_lifecycle_wire_to_json_dict(wire)["state"] == "inactive"


def test_project_record_wire_dict_conversion() -> None:
    record = project_record_from_dict(
        _record_payload(
            archive_file="/tmp/projects/alpha/alpha-archive.sase",
            active_claim_count=2,
            aliases=["docs", "bob"],
            parse_warnings=["invalid state"],
        )
    )

    assert record.project_name == "alpha"
    assert record.archive_file == "/tmp/projects/alpha/alpha-archive.sase"
    assert record.active_claim_count == 2
    assert record.aliases == ["docs", "bob"]
    assert record.parse_warnings == ["invalid state"]


def test_project_record_wire_missing_aliases_is_backward_compatible() -> None:
    payload = _record_payload()
    del payload["aliases"]

    record = project_record_from_dict(payload)

    assert record.aliases == []


def test_project_lifecycle_wire_accepts_sibling_state() -> None:
    lifecycle = project_lifecycle_from_dict(
        _lifecycle_payload(state="sibling", explicit=True)
    )
    record = project_record_from_dict(
        _record_payload(state="sibling", launchable=False)
    )

    assert lifecycle.state == "sibling"
    assert record.state == "sibling"
    assert normalize_project_lifecycle_state("sibling") == "sibling"
    assert normalize_project_lifecycle_state_filter("all") == [
        "active",
        "inactive",
        "sibling",
    ]


def test_lifecycle_facade_missing_extension_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force_no_rust_extension(monkeypatch)

    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        project_lifecycle_facade.read_project_lifecycle_from_content("")
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        project_lifecycle_facade.apply_project_lifecycle_update("", "active")
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        project_lifecycle_facade.apply_project_aliases_update("", ["bob"])
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        project_lifecycle_facade.list_project_records("/tmp/projects")


def test_lifecycle_facade_stale_binding_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    with pytest.raises(AttributeError, match="read_project_lifecycle_from_content"):
        project_lifecycle_facade.read_project_lifecycle_from_content("")
    with pytest.raises(AttributeError, match="apply_project_lifecycle_update"):
        project_lifecycle_facade.apply_project_lifecycle_update("", "active")
    with pytest.raises(AttributeError, match="apply_project_aliases_update"):
        project_lifecycle_facade.apply_project_aliases_update("", ["bob"])
    with pytest.raises(AttributeError, match="list_project_records"):
        project_lifecycle_facade.list_project_records("/tmp/projects")


def test_lifecycle_facade_calls_rust_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def fake_read(content: str) -> dict[str, Any]:
        calls.append(("read", (content,)))
        return _lifecycle_payload(state="inactive", explicit=True)

    def fake_apply(content: str, state: str) -> str:
        calls.append(("apply", (content, state)))
        return f"{content}PROJECT_STATE: {state}\n"

    def fake_apply_aliases(content: str, aliases: list[str]) -> str:
        calls.append(("apply_aliases", (content, aliases)))
        return f"{content}PROJECT_ALIASES: {', '.join(sorted(aliases))}\n"

    def fake_list(
        projects_root: str, include_states: list[str], include_home: bool
    ) -> list[dict[str, Any]]:
        calls.append(("list", (projects_root, include_states, include_home)))
        return [_record_payload(project_name="beta", state=include_states[0])]

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.read_project_lifecycle_from_content = fake_read  # type: ignore[attr-defined]
    fake.apply_project_lifecycle_update = fake_apply  # type: ignore[attr-defined]
    fake.apply_project_aliases_update = fake_apply_aliases  # type: ignore[attr-defined]
    fake.list_project_records = fake_list  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    lifecycle = project_lifecycle_facade.read_project_lifecycle_from_content(
        "NAME: x\n"
    )
    updated = project_lifecycle_facade.apply_project_lifecycle_update(
        "NAME: x\n", "inactive"
    )
    aliases_updated = project_lifecycle_facade.apply_project_aliases_update(
        "NAME: x\n", ("docs", "bob")
    )
    records = project_lifecycle_facade.list_project_records(
        "/tmp/projects", "active", include_home=True
    )

    assert lifecycle.state == "inactive"
    assert updated.endswith("PROJECT_STATE: inactive\n")
    assert aliases_updated.endswith("PROJECT_ALIASES: bob, docs\n")
    assert records[0].project_name == "beta"
    assert calls == [
        ("read", ("NAME: x\n",)),
        ("apply", ("NAME: x\n", "inactive")),
        ("apply_aliases", ("NAME: x\n", ["docs", "bob"])),
        ("list", ("/tmp/projects", ["active"], True)),
    ]


def test_lifecycle_facade_filters_invalid_project_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_list(
        projects_root: str, include_states: list[str], include_home: bool
    ) -> list[dict[str, Any]]:
        return [
            _record_payload(project_name=".sase"),
            _record_payload(project_name="alpha"),
        ]

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.list_project_records = fake_list  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    records = project_lifecycle_facade.list_project_records("/tmp/projects")

    assert [record.project_name for record in records] == ["alpha"]


def test_lifecycle_facade_real_extension_content_helpers() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "read_project_lifecycle_from_content"):
        pytest.skip("sase_core_rs is too old (no project lifecycle bindings).")
    if not hasattr(rust_module, "apply_project_aliases_update"):
        pytest.skip("sase_core_rs is too old (no project alias bindings).")

    lifecycle = project_lifecycle_facade.read_project_lifecycle_from_content(
        "PROJECT_STATE: archived\nNAME: demo\n"
    )
    sibling = project_lifecycle_facade.read_project_lifecycle_from_content(
        "PROJECT_STATE: sibling\nNAME: demo\n"
    )
    updated = project_lifecycle_facade.apply_project_lifecycle_update(
        "WORKSPACE_DIR: /tmp\nNAME: demo\n", "closed"
    )
    sibling_updated = project_lifecycle_facade.apply_project_lifecycle_update(
        "WORKSPACE_DIR: /tmp\nNAME: demo\n", "sibling"
    )
    aliases_updated = project_lifecycle_facade.apply_project_aliases_update(
        "WORKSPACE_DIR: /tmp\nRUNNING:\n\nNAME: demo\n", ["docs", "bob"]
    )
    aliases_cleared = project_lifecycle_facade.apply_project_aliases_update(
        "WORKSPACE_DIR: /tmp\nPROJECT_ALIASES: bob\nNAME: demo\n", []
    )

    assert lifecycle.state == "inactive"
    assert lifecycle.explicit is True
    assert lifecycle.warnings
    assert sibling.state == "sibling"
    assert sibling.explicit is True
    assert updated == "WORKSPACE_DIR: /tmp\nPROJECT_STATE: inactive\nNAME: demo\n"
    assert (
        sibling_updated == "WORKSPACE_DIR: /tmp\nPROJECT_STATE: sibling\nNAME: demo\n"
    )
    assert (
        aliases_updated
        == "WORKSPACE_DIR: /tmp\nPROJECT_ALIASES: bob, docs\nRUNNING:\n\nNAME: demo\n"
    )
    assert aliases_cleared == "WORKSPACE_DIR: /tmp\nNAME: demo\n"


def test_lifecycle_facade_real_extension_project_records(tmp_path: Path) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "list_project_records"):
        pytest.skip("sase_core_rs is too old (no project lifecycle bindings).")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    projects = tmp_path / "projects"
    project_dir = projects / "alpha"
    project_dir.mkdir(parents=True)
    (project_dir / "alpha.sase").write_text(
        f"PROJECT_ALIASES: bob, docs\nWORKSPACE_DIR: {workspace}\nRUNNING:\n  #1 | 123 | run | demo\n\nNAME: demo\n",
        encoding="utf-8",
    )
    sibling_dir = projects / "sibling"
    sibling_dir.mkdir()
    (sibling_dir / "sibling.sase").write_text(
        f"PROJECT_STATE: sibling\nWORKSPACE_DIR: {workspace}\nNAME: sibling\n",
        encoding="utf-8",
    )
    hidden_dir = projects / ".sase"
    hidden_dir.mkdir()
    (hidden_dir / ".sase.sase").write_text("", encoding="utf-8")

    records = project_lifecycle_facade.list_project_records(projects, ["active"])

    assert len(records) == 1
    assert records[0].project_name == "alpha"
    assert records[0].aliases == ["bob", "docs"]
    assert records[0].state == "active"
    assert records[0].active_claim_count == 1
    assert records[0].launchable is True

    siblings = project_lifecycle_facade.list_project_records(projects, ["sibling"])
    assert len(siblings) == 1
    assert siblings[0].project_name == "sibling"
    assert siblings[0].state == "sibling"
    assert siblings[0].launchable is False
