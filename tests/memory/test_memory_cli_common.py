"""Tests for shared ``sase memory`` ``-p/--project`` resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.memory import cli_common
from sase.xprompt._glossary_catalog_projects import EditorGlossaryProject


def _project(name: str = "sase", key: str = "sase") -> EditorGlossaryProject:
    return EditorGlossaryProject(
        key=key, name=name, aliases=(), workspace_dir=Path("/tmp/sase")
    )


def test_resolve_memory_cli_project_returns_none_without_a_ref() -> None:
    assert cli_common.resolve_memory_cli_project(None) is None
    assert cli_common.resolve_memory_cli_project("") is None


def test_resolve_memory_cli_project_returns_workspace_for_known_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_common, "enabled_project_records", lambda *_a, **_kw: ())
    monkeypatch.setattr(
        cli_common, "select_project", lambda *_a, **_kw: _project(name="Sase")
    )

    resolved = cli_common.resolve_memory_cli_project("sase")

    assert resolved is not None
    assert resolved.project_name == "Sase"
    assert resolved.project_root == Path("/tmp/sase")


def test_resolve_memory_cli_project_raises_when_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_common, "enabled_project_records", lambda *_a, **_kw: ())
    monkeypatch.setattr(cli_common, "select_project", lambda *_a, **_kw: None)

    with pytest.raises(cli_common.MemoryCliProjectError, match="did not resolve"):
        cli_common.resolve_memory_cli_project("missing")
