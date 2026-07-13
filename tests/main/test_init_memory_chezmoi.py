"""Tests for ``sase memory init`` chezmoi behavior."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.amd.constants import (
    HOME_PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from sase.main import init_memory_handler
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_handler,
    write,
)


def _single_line(text: str) -> str:
    return " ".join(text.split())


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
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    write(
        chezmoi_home / "dot_config" / "sase" / "sase.yml",
        """
sibling_repos:
  - name: telegram
    path: /global/telegram
    description: Telegram workflow plugin.
  - name: chezmoi
    path: ~/.local/share/chezmoi
    description: Chezmoi-managed dotfiles and global SASE configuration source.
    workspace:
      strategy: none
""",
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    assert not (home_root / "memory").exists()
    chezmoi_memory = (chezmoi_home / "memory" / "sase.md").read_text()
    assert "`telegram`: Telegram workflow plugin." in chezmoi_memory
    assert "/global/telegram" not in chezmoi_memory
    assert "Static-path linked repositories (`workspace.strategy: none`)" not in (
        chezmoi_memory
    )
    assert (
        "- `chezmoi`: Chezmoi-managed dotfiles and global SASE configuration source."
    ) in _single_line(chezmoi_memory)
    assert 'sase repo open <linked_repo> -r "<reason>"' in chezmoi_memory
    assert "the workspace number is inferred from where you run it" in _single_line(
        chezmoi_memory
    )
    # Chezmoi writes static copies of ``AGENTS.md`` (no ``.tmpl``).
    agents = (chezmoi_home / "AGENTS.md").read_text()
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / filename).read_text() == agents
        assert not (chezmoi_home / f"{filename}.tmpl").exists()
    assert chezmoi_home / "memory" / "sase.md" in deployed
    assert chezmoi_home / "CLAUDE.md" in deployed


def test_init_memory_chezmoi_migrates_plain_provider_shim_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    write(chezmoi_home / "CLAUDE.md", HOME_PROVIDER_SHIM_CONTENT)
    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    # The legacy plain ``@~/AGENTS.md`` shim migrates to a static full copy at
    # the preferred ``CLAUDE.md`` path; no ``.tmpl`` source is written.
    agents = (chezmoi_home / "AGENTS.md").read_text()
    assert (chezmoi_home / "CLAUDE.md").read_text() == agents
    assert not (chezmoi_home / "CLAUDE.md.tmpl").exists()
    assert chezmoi_home / "CLAUDE.md" in deployed


def test_init_memory_deferred_chezmoi_collects_paths_without_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)

    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", deploy_mock)

    with defer_chezmoi_deploy() as deferred:
        assert run_handler() == 0

    deploy_mock.assert_not_called()
    assert chezmoi_home / "memory" / "sase.md" in deferred.paths
    assert chezmoi_home / "CLAUDE.md" in deferred.paths
