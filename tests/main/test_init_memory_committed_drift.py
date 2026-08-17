"""Regression gate: this repo's committed project memory must match the generator.

``sase validate``'s memory step and ``sase init memory --check`` both resolve
through :func:`plan_init_memory` -> ``plan_memory_root`` ->
``render_expected_memory_files`` for a project-scoped generated note (see
bead sase-n0). There is exactly one generator, so the two entry points cannot
structurally disagree about project-scoped drift. This test pins that
contract against this repo's *real* committed tree, so generator/template
drift on a project-scoped note fails fast in the test suite instead of
surfacing only when someone happens to run ``sase validate`` by hand.

Home/chezmoi-root generated notes are deliberately out of scope here: they
depend on the operator's machine-specific home directory and are not
hermetic to check from a committed test.
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
