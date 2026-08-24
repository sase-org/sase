"""Memory-init coverage for flag-gated memory webs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.memory.web import START_MARKER
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _descriptor(body: str = "# Terms\n\nDescriptor body.\n") -> str:
    return (
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        "roster_label: TERMS\n"
        "---\n\n"
        f"{body}"
    )


def _strand(body: str = "Hidden strand body.\n") -> str:
    return f"---\nkeyword: Alpha Term\naliases: [alpha]\n---\n\n{body}"


def _setup_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
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
    )
    return project_root, home_root, config_dir


def test_memory_web_flag_off_treats_descriptor_as_ordinary_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    descriptor = project_root / "sase" / "memory" / "terms.md"
    write(descriptor, _descriptor())
    write(project_root / "sase" / "memory" / "terms" / "alpha.md", _strand())

    with override_flags(memory_webs=False):
        plan = plan_memory()

    action_by_path = {action.path: action for action in plan.actions}
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert descriptor not in action_by_path
    assert "Descriptor body." in agents
    assert "Alpha Term" not in agents
    assert "Hidden strand body." not in agents
    assert START_MARKER not in agents


def test_memory_web_flag_on_updates_roster_without_inlining_strand_bodies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    descriptor = project_root / "sase" / "memory" / "terms.md"
    write(descriptor, _descriptor())
    write(project_root / "sase" / "memory" / "terms" / "alpha.md", _strand())

    with override_flags(memory_webs=True):
        plan = plan_memory()

    action_by_path = {action.path: action for action in plan.actions}
    updated_descriptor = str(action_by_path[descriptor].new_content)
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert "**TERMS:** Alpha Term (alpha)" in updated_descriptor
    assert "**TERMS:** Alpha Term (alpha)" in agents
    assert "Hidden strand body." not in agents


def test_memory_web_flag_on_blocks_invalid_webs_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    write(project_root / "sase" / "memory" / "terms.md", _descriptor())
    write(
        project_root / "sase" / "memory" / "terms" / "alpha.md",
        "---\ntype: core\n---\n\nBody.\n",
    )

    with override_flags(memory_webs=True):
        plan = plan_memory()
        exit_code = run_memory(check=True)

    assert exit_code == 1
    assert any("must not declare type" in blocker for blocker in plan.blockers)
