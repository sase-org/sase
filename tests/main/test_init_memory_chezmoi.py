"""Tests for ``sase memory init`` chezmoi behavior."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sase.config.core as config_core
from sase.amd.constants import (
    HOME_PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from sase.main import init_memory_handler
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    short_note,
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

    def fake_deploy(
        paths: Iterable[Path],
        delete_targets: Sequence[Path] = (),
    ) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    assert not (home_root / "sase" / "memory").exists()
    chezmoi_memory = (chezmoi_home / "sase" / "memory" / "sase.md").read_text()
    assert "`telegram`: Telegram workflow plugin." in chezmoi_memory
    assert "/global/telegram" not in chezmoi_memory
    assert "Static-path linked repositories (`workspace.strategy: none`)" not in (
        chezmoi_memory
    )
    assert (
        "- `chezmoi`: Chezmoi-managed dotfiles and global SASE configuration source."
    ) in _single_line(chezmoi_memory)
    assert "agents MUST use your `/sase_repo` skill first" in _single_line(
        chezmoi_memory
    )
    assert "another SASE project's repo" in _single_line(chezmoi_memory)
    assert "This rule applies regardless of transport" in _single_line(chezmoi_memory)
    assert "raw.githubusercontent.com" in chezmoi_memory
    assert (
        "locate, clone, or web-fetch another repo's contents any other way than "
        "by using `/sase_repo` or `sase artifact read`!"
    ) in _single_line(chezmoi_memory)
    assert 'sase repo open <linked_repo> -r "<reason>"' not in chezmoi_memory
    # Chezmoi writes static copies of ``AGENTS.md`` (no ``.tmpl``).
    agents = (chezmoi_home / "AGENTS.md").read_text()
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / filename).read_text() == agents
        assert not (chezmoi_home / f"{filename}.tmpl").exists()
    assert chezmoi_home / "sase" / "memory" / "sase.md" in deployed
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

    def fake_deploy(
        paths: Iterable[Path],
        delete_targets: Sequence[Path] = (),
    ) -> int:
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
    assert chezmoi_home / "sase" / "memory" / "sase.md" in deferred.paths
    assert chezmoi_home / "CLAUDE.md" in deferred.paths


def test_init_memory_chezmoi_retired_source_deletes_live_target(
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
        chezmoi_home / "sase" / "memory" / "task_types.md",
        short_note(
            "# Task Bead Types\n\n"
            "Stale generated catalog from an older SASE.\n\n"
            "## Types\n\n"
            "No agent-creatable task types are registered.\n"
        ),
    )

    deployed: list[Path] = []
    deleted: list[Path] = []

    def fake_deploy(
        paths: Iterable[Path],
        delete_targets: Sequence[Path] = (),
    ) -> int:
        deployed.extend(paths)
        deleted.extend(delete_targets)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    source_path = chezmoi_home / "sase" / "memory" / "task_types.md"
    live_path = Path.home() / "sase" / "memory" / "task_types.md"
    assert not source_path.exists()
    assert source_path in deployed
    assert live_path in deleted


def _machine_ignore_text() -> str:
    return (
        "tags\n"
        '{{ if ne .chezmoi.fqdnHostname "bbugyi.c.googlers.com" }}\n'
        ".config/sase/sase_work.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "athena" }}\n'
        ".config/sase/sase_athena.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "Kellys-MBP" }}\n'
        ".config/sase/sase_kellys_mbp.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "apollo" }}\n'
        ".config/sase/sase_apollo.yml\n"
        "{{ end }}\n"
    )


def _write_machine_layout(
    chezmoi_home: Path,
    *,
    titles: dict[str, str],
    ignore: str | None = None,
) -> None:
    config_dir = chezmoi_home / "dot_config" / "sase"
    write(config_dir / "sase.yml", "use_chezmoi: true\n")
    for machine_name in ("apollo", "athena", "kellys_mbp"):
        body = f"id:\n  username: bbugyi200\n  machine_name: {machine_name}\n"
        title = titles.get(machine_name)
        if title is not None:
            body += f'\nmemory:\n  h1_title: "{title}"\n'
        write(config_dir / f"sase_{machine_name}.yml", body)
    write(chezmoi_home / ".chezmoiignore", ignore or _machine_ignore_text())


def _patch_chezmoi_home(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    home_root: Path,
    config_dir: Path,
    chezmoi_home: Path,
) -> None:
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
    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)


def test_init_memory_chezmoi_templates_machine_h1_titles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _patch_chezmoi_home(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        chezmoi_home=chezmoi_home,
    )
    _write_machine_layout(
        chezmoi_home,
        titles={
            "apollo": "apollo - Bryan Bugyi's Rendezvous Server",
            "athena": "athena - Bryan Bugyi's Home Server",
        },
    )
    write(
        chezmoi_home / "AGENTS.md",
        "# athena - Bryan Bugyi's Home Server\n\n## Core Memory\n\nOld copy.\n",
    )
    write(
        chezmoi_home / "CLAUDE.md",
        "# athena - Bryan Bugyi's Home Server\n\n## Core Memory\n\nOld copy.\n",
    )

    deployed: list[Path] = []
    deleted: list[Path] = []

    def fake_deploy(
        paths: Iterable[Path],
        delete_targets: Sequence[Path] = (),
    ) -> int:
        deployed.extend(paths)
        deleted.extend(delete_targets)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    template_path = chezmoi_home / "AGENTS.md.tmpl"
    assert template_path.is_file()
    assert not (chezmoi_home / "AGENTS.md").exists()
    first_line = template_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == (
        '{{ if eq .chezmoi.hostname "apollo" }}'
        "# apollo - Bryan Bugyi's Rendezvous Server"
        '{{ else if eq .chezmoi.hostname "athena" }}'
        "# athena - Bryan Bugyi's Home Server"
        "{{ else }}# athena - Bryan Bugyi's Home Server{{ end }}"
    )
    templated = template_path.read_text(encoding="utf-8")
    for filename in PROVIDER_SHIM_FILES:
        shim = chezmoi_home / f"{filename}.tmpl"
        assert shim.read_text(encoding="utf-8") == templated
        assert not (chezmoi_home / filename).exists()
    assert chezmoi_home / "AGENTS.md.tmpl" in deployed
    assert chezmoi_home / "CLAUDE.md.tmpl" in deployed
    assert chezmoi_home / "AGENTS.md" in deployed
    assert home_root / "AGENTS.md" in deleted
    assert home_root / "CLAUDE.md" in deleted

    assert run_handler() == 0
    assert plan_memory().actions == ()
    assert plan_memory().blockers == ()


def test_init_memory_chezmoi_without_machine_titles_stays_static(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _patch_chezmoi_home(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        chezmoi_home=chezmoi_home,
    )
    _write_machine_layout(chezmoi_home, titles={})
    write(
        chezmoi_home / "dot_config" / "sase" / "sase.yml",
        'memory:\n  h1_title: "Home Instructions"\n',
    )

    monkeypatch.setattr(
        init_memory_handler, "_deploy_to_chezmoi", lambda *_args, **_kwargs: 0
    )

    assert run_handler() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Home Instructions\n")
    assert not (chezmoi_home / "AGENTS.md.tmpl").exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (chezmoi_home / filename).read_text(encoding="utf-8") == agents
        assert not (chezmoi_home / f"{filename}.tmpl").exists()


def test_init_memory_chezmoi_title_without_hostname_guard_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _patch_chezmoi_home(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        chezmoi_home=chezmoi_home,
    )
    _write_machine_layout(
        chezmoi_home,
        titles={"apollo": "apollo title"},
        ignore="tags\n",
    )

    plan = plan_memory()
    assert any("hostname guard" in blocker for blocker in plan.blockers)
    assert run_handler() == 1
    assert not (chezmoi_home / "AGENTS.md.tmpl").exists()
