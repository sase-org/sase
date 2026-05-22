"""Tests for the ``sase init memory`` command."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import handle_init_memory_command


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_handler() -> int:
    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(argparse.Namespace())
    return int(exc.value.code)


def _patch_standard_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    home_root: Path,
    config_dir: Path,
    use_chezmoi: bool = False,
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: use_chezmoi)


def test_init_memory_uses_local_siblings_for_project_and_global_for_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    _write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../local-core
    description: Local Rust core.
""",
    )
    _write(
        config_dir / "sase.yml",
        """
sibling_repos:
  - name: github
    path: /global/github
    description: Global GitHub plugin.
""",
    )

    assert _run_handler() == 0
    out = capsys.readouterr().out
    assert "init memory: initialized memory" in out

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "short" / "sase.md").read_text()
    assert "`core`: Local Rust core." in project_memory
    assert "`github`: Global GitHub plugin." not in project_memory
    assert "../local-core" not in project_memory
    assert "`github`: Global GitHub plugin." in home_memory
    assert "`core`: Local Rust core." not in home_memory
    assert "/global/github" not in home_memory

    for root in (project_root, home_root):
        assert (root / "memory" / "long").is_dir()
        assert (root / "memory" / "README.md").is_file()
        assert "@memory/short/sase.md" in (root / "AGENTS.md").read_text()
        for filename in ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md"):
            assert (root / filename).read_text() == "@AGENTS.md\n"


def test_init_memory_reports_missing_sibling_descriptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert _run_handler() == 1
    err = capsys.readouterr().err
    assert "cannot generate project memory" in err
    assert "field 'description'" in err
    assert not (project_root / "memory").exists()


def test_init_memory_overwrites_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(project_root / "AGENTS.md", "@memory/short/sase.md\n")
    _write(project_root / "CLAUDE.md", "old instructions\n")

    assert _run_handler() == 0

    assert (project_root / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    for filename in ("GEMINI.md", "QWEN.md", "OPENCODE.md"):
        assert (project_root / filename).read_text() == "@AGENTS.md\n"


def test_init_memory_allows_transitive_memory_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(
        project_root / "AGENTS.md",
        "@memory/short/sase.md\n\nmemory/long/index.md\n",
    )
    _write(
        project_root / "memory" / "long" / "index.md",
        "# Index\n\n@memory/long/detail.md\n",
    )
    _write(project_root / "memory" / "long" / "detail.md", "# Detail\n")

    assert _run_handler() == 0


def test_init_memory_rejects_unreferenced_memory_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(project_root / "AGENTS.md", "@memory/short/sase.md\n")
    _write(
        project_root / "memory" / "long" / "orphan.md",
        "# Orphan\n\n@memory/long/orphan.md\n",
    )

    assert _run_handler() == 1
    err = capsys.readouterr().err
    assert "unreferenced memory files" in err
    assert "memory/long/orphan.md" in err


def test_init_memory_uses_chezmoi_home_and_global_config_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    _write(
        chezmoi_home / "dot_config" / "sase" / "sase.yml",
        """
sibling_repos:
  - name: telegram
    path: /global/telegram
    description: Telegram workflow plugin.
""",
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert _run_handler() == 0

    assert not (home_root / "memory").exists()
    chezmoi_memory = (chezmoi_home / "memory" / "short" / "sase.md").read_text()
    assert "`telegram`: Telegram workflow plugin." in chezmoi_memory
    assert "/global/telegram" not in chezmoi_memory
    assert chezmoi_home / "memory" / "short" / "sase.md" in deployed
