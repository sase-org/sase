"""Tests for memory-history scope assembly (no git history needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.memory.history import scopes
from sase.memory.history.scopes import (
    HistoryScopeError,
    build_home_scope,
    build_project_scope,
    map_deployed_home_path,
)


def _write(path: Path, content: str = "# Note\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_project_scope_keys_and_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(tmp_path / "sase" / "memory" / "tui.md")
    monkeypatch.setattr(scopes, "git_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(
        "sase.main.init_memory.config.project_memory_name",
        lambda _root: "sase",
    )

    scope = build_project_scope(tmp_path)

    assert scope.scope_key == "project:sase"
    assert scope.scope_kind == "project"
    assert scope.repo_root == tmp_path.as_posix()
    assert scope.memory_roots == ("sase/memory", "memory")
    assert scope.generated_notes, "generated notes must not be empty"


def test_project_scope_instruction_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(tmp_path / "src" / "sase" / "ace" / "AGENTS.md", "# Ace\n")
    monkeypatch.setattr(scopes, "git_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(
        "sase.main.init_memory.config.project_memory_name",
        lambda _root: "demo",
    )

    scope = build_project_scope(tmp_path)
    by_dir = {entry.dir: entry for entry in scope.instruction_files}

    assert set(by_dir) == {".", "src/sase/ace"}
    root_entry = by_dir["."]
    assert root_entry.agents_path == "AGENTS.md"
    assert "CLAUDE.md" in root_entry.shim_paths
    assert root_entry.managed is False
    assert root_entry.template is False
    assert by_dir["src/sase/ace"].agents_path == "src/sase/ace/AGENTS.md"


def test_project_scope_outside_git_is_an_honest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scopes, "git_repo_root", lambda _start: None)

    with pytest.raises(HistoryScopeError, match="NO VCS"):
        build_project_scope(tmp_path)


def test_project_scope_renderer_prefix_only_for_the_sase_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scopes, "git_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(
        "sase.main.init_memory.config.project_memory_name",
        lambda _root: "demo",
    )

    assert build_project_scope(tmp_path).renderer_prefixes == ()

    (tmp_path / "src" / "sase" / "amd").mkdir(parents=True)
    assert build_project_scope(tmp_path).renderer_prefixes == ("src/sase/amd",)


def test_home_scope_is_none_without_chezmoi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scopes, "_chezmoi_enabled", lambda: False)

    assert build_home_scope() is None


def test_home_scope_uses_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scopes, "_chezmoi_enabled", lambda: True)
    monkeypatch.setattr(scopes, "_home_source_repo_root", lambda: tmp_path)
    _write(tmp_path / "home" / "AGENTS.md.tmpl", "# Home\n")

    scope = build_home_scope()

    assert scope is not None
    assert scope.scope_key == "home"
    assert scope.scope_kind == "home"
    assert scope.memory_roots == ("home/sase/memory", "home/memory")
    (entry,) = scope.instruction_files
    assert entry.dir == "home"
    assert entry.agents_path == "home/AGENTS.md.tmpl"
    assert entry.template is True
    assert "home/CLAUDE.md.tmpl" in entry.shim_paths


def test_map_deployed_home_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/u")))

    assert (
        map_deployed_home_path(Path("/home/u/sase/memory/tui.md"))
        == "home/sase/memory/tui.md"
    )
    assert map_deployed_home_path(Path("/home/u/AGENTS.md")) == "home/AGENTS.md.tmpl"
    assert map_deployed_home_path(Path("/home/u/CLAUDE.md")) == "home/CLAUDE.md.tmpl"
    assert map_deployed_home_path(Path("/home/u/.zshrc")) is None
    assert map_deployed_home_path(Path("/elsewhere/AGENTS.md")) is None
