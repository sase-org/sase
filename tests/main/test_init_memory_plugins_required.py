"""``plugins.required`` blockers run before memory drift comparison."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    write,
)


def test_memory_plan_blockers_missing_required_plugin_before_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nplugins:\n  required:\n    - sase-github\n",
    )
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {},
    )

    plan = plan_memory()

    assert any(
        "required plugin `sase-github` is not installed" in blocker
        for blocker in plan.blockers
    )
    assert plan.actions == ()


def test_memory_plan_undeclared_use_prefix_is_a_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    write(
        project_root / "sase.yml",
        (
            "is_sase_managed: true\n"
            "repos:\n"
            "  sidecar:\n"
            "    custom:\n"
            "      research:\n"
            "        ref:\n"
            "          use: sase-research-artifacts@research\n"
        ),
    )
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {},
    )

    plan = plan_memory()

    assert any(
        "sase-research-artifacts" in blocker and "plugins.required" in blocker
        for blocker in plan.blockers
    )
    assert plan.actions == ()


def test_memory_plan_continues_when_required_plugins_are_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nplugins:\n  required:\n    - sase-github\n",
    )
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {"sase-github": "1.0.0"},
    )

    plan = plan_memory()

    assert not any("required plugin" in blocker for blocker in plan.blockers)
    assert plan.actions
