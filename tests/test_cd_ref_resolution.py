"""Reference-resolution tests for the built-in ``#cd`` workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests._cd_launch_resolution_helpers import patch_cd_metadata


def test_resolve_ref_from_prompt_cd_skips_numbered_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    with (
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.workspace_provider.get_workspace_directory") as workspace_dir,
    ):
        result = resolve_ref_from_prompt(f"#cd:{tmp_path} do work", "cd")

    assert result is not None
    project_file, project_name, resolved_dir, workspace_num, ref_value = result
    assert project_file.endswith("/projects/home/home.sase")
    assert project_name == tmp_path.name
    assert resolved_dir == str(tmp_path.resolve())
    assert workspace_num == 0
    assert ref_value == str(tmp_path)
    first_ws.assert_not_called()
    workspace_dir.assert_not_called()


def test_resolve_ref_from_prompt_bad_cd_path_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="does not exist"):
        resolve_ref_from_prompt(f"#cd:{missing} do work", "cd")


def test_resolve_agent_workspace_dir_prefers_explicit_directory(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
        resolve_agent_workspace_dir,
    )

    target = tmp_path / "target"
    target.mkdir()

    assert resolve_agent_workspace_dir(
        0,
        str(tmp_path / "home.gp"),
        str(target),
    ) == str(target)
