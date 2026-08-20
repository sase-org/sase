"""Regression gate: this repo's committed project memory must match the generator.

``sase validate``'s memory step and ``sase init memory --check`` both resolve
through :func:`plan_init_memory` -> ``plan_memory_root`` ->
``render_expected_memory_files`` for a project-scoped generated note (see
bead sase-n0). There is exactly one generator, so the two entry points cannot
structurally disagree about project-scoped drift. This test pins that
contract against this repo's *real* committed tree, so generator/template
drift on a project-scoped note fails fast in the test suite instead of
surfacing only when someone happens to run ``sase validate`` by hand.

Home/chezmoi-root generated notes are not checked against the operator's
live machine. Separate tests below cover project-versus-home/chezmoi
template precedence and the complete generated-note inventory in a
hermetic home README.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import plan_init_memory

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repo_project_memory_notes_match_generator_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    real_directory_map_assets: None,
) -> None:
    monkeypatch.chdir(_REPO_ROOT)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: False)

    plan = plan_init_memory(argparse.Namespace(no_commit=True))

    project_actions = [
        action
        for action in plan.actions
        if action.path == _REPO_ROOT or _REPO_ROOT in action.path.parents
    ]

    assert plan.blockers == ()
    assert project_actions == []


def test_project_memory_templates_beat_home_and_chezmoi_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import init_memory_handler as handler_mod
    from tests.main.init_memory_handler_helpers import (
        patch_standard_paths,
        run_handler,
        write,
    )

    def sase_template(marker: str) -> str:
        return (
            f"# Custom SASE\n\n{marker}\n\n"
            "{% if project_name %}\n"
            "## Project `{{ project_name }}`\n"
            "{% endif %}\n\n"
            "## Repositories\n\n"
            "{{ linked_repo_entries }}\n"
        )

    def readme_template(marker: str) -> str:
        return (
            f"# Custom Memory README\n\n{marker}\n\n"
            "{% if memory_notes %}\n"
            "{{ memory_notes }}\n"
            "{% endif %}\n\n"
            "## Counts\n\n"
            "- Total: {{ total_notes }}\n"
            "- Short: {{ short_notes }}\n"
            "- Long: {{ long_notes }}\n"
            "- Lines: {{ total_lines }}\n"
            "- Tokens: {{ total_tokens }}\n"
        )

    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    chezmoi_home.mkdir(parents=True)
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(handler_mod, "CHEZMOI_HOME", chezmoi_home)
    import sase.config.core as config_core

    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(handler_mod, "_deploy_to_chezmoi", lambda _paths: 0)

    write(
        project_root / "sase.yml",
        "is_sase_managed: true\n"
        "memory:\n"
        "  sase_template: templates/sase.md\n"
        "  readme_template: templates/readme.md\n",
    )
    write(project_root / "templates" / "sase.md", sase_template("PROJECT SASE."))
    write(
        project_root / "templates" / "readme.md",
        readme_template("PROJECT README."),
    )
    source_config_dir = chezmoi_home / "dot_config" / "sase"
    write(
        source_config_dir / "memory-sase.template.md",
        sase_template("CHEZMOI SASE."),
    )
    write(
        source_config_dir / "memory-README.template.md",
        readme_template("CHEZMOI README."),
    )

    assert run_handler() == 0

    project_sase = (project_root / "sase" / "memory" / "sase.md").read_text(
        encoding="utf-8"
    )
    chezmoi_sase = (chezmoi_home / "sase" / "memory" / "sase.md").read_text(
        encoding="utf-8"
    )
    assert "PROJECT SASE." in project_sase
    assert "CHEZMOI SASE." not in project_sase
    assert "CHEZMOI SASE." in chezmoi_sase
    assert "PROJECT SASE." not in chezmoi_sase


def test_home_readme_lists_complete_generated_note_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.init_memory.root_rendering_notes import (
        generated_memory_note_relative_paths,
    )
    from tests.main.init_memory_handler_helpers import patch_standard_paths, run_handler

    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=False,
    )

    assert run_handler() == 0

    readme = (home_root / "sase" / "memory" / "README.md").read_text(encoding="utf-8")
    generated_paths = generated_memory_note_relative_paths(include_project_memory=False)
    assert generated_paths
    for relative in generated_paths:
        assert f"### `{relative.as_posix()}`" in readme
