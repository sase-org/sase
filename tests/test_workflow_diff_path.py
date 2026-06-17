"""Regression tests for workflow diff-path extraction semantics.

Covers the #sshot crash: an arbitrary ``"path"``-typed step output (a PNG
screenshot's ``local_path``) must not be promoted into ``diff_path``, or the
ACE file panel tries to read binary bytes as a UTF-8 diff and crashes.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._diff_path import diff_path_from_step_output
from sase.ace.tui.models._loaders._workflow_step_loaders import (
    _load_workflow_agent_steps_for_dir,
)

# --- diff_path_from_step_output helper -------------------------------------


def test_helper_returns_explicit_diff_path() -> None:
    assert diff_path_from_step_output({"diff_path": "/tmp/x.diff"}) == "/tmp/x.diff"


def test_helper_ignores_generic_path_typed_field() -> None:
    # local_path is a valid path artifact (e.g. #sshot screenshot) but NOT a
    # diff, so it must not be promoted.
    assert diff_path_from_step_output({"local_path": "/tmp/shot.png"}) is None


def test_helper_returns_none_for_non_dict() -> None:
    assert diff_path_from_step_output(None) is None
    assert diff_path_from_step_output("/tmp/shot.png") is None


def test_helper_ignores_empty_diff_path() -> None:
    assert diff_path_from_step_output({"diff_path": ""}) is None


# --- filesystem child-step loader ------------------------------------------


def _write_step_marker(
    timestamp_dir: Path, output: dict[str, object], output_types: dict[str, str]
) -> None:
    marker = {
        "workflow_name": "sshot",
        "step_name": "fetch",
        "step_type": "bash",
        "status": "completed",
        "output": output,
        "output_types": output_types,
    }
    (timestamp_dir / "prompt_step_fetch.json").write_text(
        json.dumps(marker), encoding="utf-8"
    )


def test_child_step_png_local_path_is_not_a_diff(tmp_path: Path) -> None:
    """The #sshot ``fetch`` step's PNG ``local_path`` must load with no diff."""
    project_dir = tmp_path / "myproj"
    timestamp_dir = project_dir / "artifacts" / "workflow-sshot" / "20260617080200"
    timestamp_dir.mkdir(parents=True)
    _write_step_marker(
        timestamp_dir,
        output={"local_path": "/home/bryan/tmp/screenshots/20260617_080200.png"},
        output_types={"local_path": "path"},
    )

    agents, _meta = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert len(agents) == 1
    assert agents[0].diff_path is None
    # The screenshot path is still surfaced via the step output for display.
    assert agents[0].step_output == {
        "local_path": "/home/bryan/tmp/screenshots/20260617_080200.png"
    }


def test_child_step_explicit_diff_path_still_loads(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    timestamp_dir = project_dir / "artifacts" / "workflow-gh" / "20260617080200"
    timestamp_dir.mkdir(parents=True)
    _write_step_marker(
        timestamp_dir,
        output={"diff_path": "/tmp/sase-gh-abc123.diff"},
        output_types={"diff_path": "path"},
    )

    agents, _meta = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert len(agents) == 1
    assert agents[0].diff_path == "/tmp/sase-gh-abc123.diff"


def test_child_step_marker_level_diff_path_takes_precedence(tmp_path: Path) -> None:
    """A top-level marker ``diff_path`` is honored over output fields."""
    project_dir = tmp_path / "myproj"
    timestamp_dir = project_dir / "artifacts" / "workflow-gh" / "20260617080200"
    timestamp_dir.mkdir(parents=True)
    marker = {
        "workflow_name": "gh",
        "step_name": "diff",
        "step_type": "bash",
        "status": "completed",
        "diff_path": "/tmp/marker-level.diff",
        "output": {"local_path": "/tmp/shot.png"},
        "output_types": {"local_path": "path"},
    }
    (timestamp_dir / "prompt_step_diff.json").write_text(
        json.dumps(marker), encoding="utf-8"
    )

    agents, _meta = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert len(agents) == 1
    assert agents[0].diff_path == "/tmp/marker-level.diff"
