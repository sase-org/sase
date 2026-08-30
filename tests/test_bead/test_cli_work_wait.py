"""CLI coverage for ``sase bead work --wait``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead import cli_work_entry
from sase.main.parser import create_parser

from .cli_work_helpers import FakeLaunchResult, make_args, seed_diamond

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_bead_work_parser_accepts_wait_short_and_long() -> None:
    parser = create_parser()
    long_args = parser.parse_args(
        ["bead", "work", "sase-1", "--wait", "sase-s7.2,bead=sase-64.3"]
    )
    short_args = parser.parse_args(["bead", "work", "sase-1", "-w", "alice"])

    assert long_args.wait == "sase-s7.2,bead=sase-64.3"
    assert short_args.wait == "alice"


def test_invalid_wait_spec_exits_2_without_launching(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        cli_work_entry,
        "_handle_bead_work_locked",
        lambda _args, **kwargs: calls.append(kwargs["target"]),
    )

    args = create_parser().parse_args(
        ["bead", "work", "sase-1", "--wait", "time=5m", "--yes"]
    )
    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_work(args)

    assert exc_info.value.code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "Error: wait spec does not accept time=" in err


def test_invalid_wait_spec_exits_2_without_mutating_an_epic(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    launch_calls: list[str] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        launch_calls.append(query)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("invalid wait spec must not commit"),
    )

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True, wait="time=5m"))

    assert exc_info.value.code == 2
    assert launch_calls == []
    assert "time=" in capsys.readouterr().err
    from sase.bead.model import Status
    from sase.bead.project import BeadProject

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            assert proj.show(phase_id).status == Status.OPEN


def test_wait_dry_run_renders_extra_waits_on_root_wave_only(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    bead_cli.handle_bead_work(
        make_args(
            epic_id,
            dry_run=True,
            yes=True,
            wait="sase-s7.2,bead=sase-64.3",
        )
    )

    out = capsys.readouterr().out
    query = out.split("--- Multi-prompt (dry run) ---\n", 1)[1]
    segments = query.split("\n---\n")
    assert len(segments) == 5
    root, *dependents, land = segments
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in root
    assert "%w:sase-s7.2" in root
    assert "%w(bead=sase-64.3)" in root
    for segment in dependents:
        assert "%w:sase-s7.2" not in segment
        assert "%w(bead=sase-64.3)" not in segment
    assert "%w:sase-s7.2" not in land
    assert "%w(bead=sase-64.3)" not in land
    assert f"#bd/land_epic:{epic_id}" in land
