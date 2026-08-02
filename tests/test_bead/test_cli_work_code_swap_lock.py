"""Code-swap lock coverage for ``sase bead work``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.agent.launch_timing import LaunchTimingRecorder
from sase.bead import cli as bead_cli
from sase.bead.project import BeadProject
from sase.dev_update.code_swap_lock import code_swap_writer_lock
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN

from .cli_work_helpers import make_args


def test_bead_work_exits_before_plan_mutations_while_code_swap_writer_holds(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = project_dir / "incoming" / "guarded.md"
    source.parent.mkdir()
    source.write_text(EPIC_PLAN, encoding="utf-8")

    with code_swap_writer_lock() as writer:
        assert writer.acquired is True
        with pytest.raises(SystemExit) as excinfo:
            bead_cli.handle_bead_work(make_args(str(source), yes=True))

    assert excinfo.value.code == 1
    stderr = capsys.readouterr().err
    assert "sase dev update is swapping the installed source tree" in stderr
    assert "No work was started" in stderr
    assert source.is_file()
    assert not list((project_dir / "sdd").glob("plans/**/*.md"))
    with BeadProject(project_dir) as project:
        assert project.list_issues() == []


def test_preload_launch_imports_loads_deferred_launch_chain() -> None:
    from sase.bead.cli_work_handler import preload_launch_imports

    sys.modules.pop("sase.agent.launcher", None)
    sys.modules.pop("sase.ace.tui.actions.agent_workflow._ref_resolution", None)
    timer = LaunchTimingRecorder("bead_work")

    preload_launch_imports(timer)

    assert "sase.agent.launcher" in sys.modules
    assert "sase.ace.tui.actions.agent_workflow._ref_resolution" in sys.modules
