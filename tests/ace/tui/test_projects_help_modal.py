"""Completeness guards for contextual Projects help."""

from __future__ import annotations

from sase.ace.tui.keymaps import load_keymap_registry, projects_help_bindings
from sase.ace.tui.modals.projects_help_modal import ProjectsHelpModal


def test_projects_help_lists_every_binding() -> None:
    keymaps = load_keymap_registry({}).projects
    modal = ProjectsHelpModal(keymaps=keymaps)
    plain = modal._content().plain
    rows = projects_help_bindings(keymaps)
    assert rows
    for key, description in rows:
        assert key in plain
        assert description in plain
    assert "Help" in plain
    assert "Show New Project" in plain
    assert "Projects Help" in modal._title().plain
