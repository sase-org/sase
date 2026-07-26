"""Preview and CLI coverage for plan-file ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.cli_work_handler import handle_bead_work
from sase.main.parser import create_parser
from tests.test_bead.cli_work_from_plan_helpers import (
    EPIC_PLAN,
    epic_plan_with_phase_count,
)


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def test_plan_file_dry_run_is_pure_and_previews_waves(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.bead.work.get_big_epic_phase_threshold",
        lambda: 5,
    )
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    before = {
        path.relative_to(project_dir): path.read_bytes()
        for path in project_dir.rglob("*")
        if path.is_file()
    }

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=True,
    )

    after = {
        path.relative_to(project_dir): path.read_bytes()
        for path in project_dir.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert result.epic_id is None
    assert result.waves == (("core",), ("cli",), ("verify",))
    assert not result.archived_plan_path.exists()
    output = capsys.readouterr().out
    assert "core Build the core (small · @small_phase_worker)" in output
    assert "cli Add the CLI (medium · @medium_phase_worker)" in output
    assert "verify Verify the result (large · @large_phase_worker · #plan)" in output
    assert "Land    @epic_lander" in output


def test_plan_file_launch_mode_keeps_legacy_sizeless_epic_resumable(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = project_dir / "legacy.md"
    legacy_plan = "\n".join(
        line for line in EPIC_PLAN.splitlines() if not line.strip().startswith("size:")
    )
    source.write_text(legacy_plan, encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=True,
    )

    assert result.waves == (("core",), ("cli",), ("verify",))
    output = capsys.readouterr().out
    assert output.count("small · @small_phase_worker") == 3
    assert "@medium_phase_worker" not in output
    assert "@large_phase_worker" not in output
    assert "#plan" not in output


@pytest.mark.parametrize(
    ("threshold", "phase_count", "model", "expected_model"),
    [
        pytest.param(5, 4, None, "@epic_lander", id="default-below"),
        pytest.param(5, 5, None, "@big_epic_lander", id="default-exact"),
        pytest.param(5, 6, None, "@big_epic_lander", id="default-above"),
        pytest.param(3, 2, None, "@epic_lander", id="custom-below"),
        pytest.param(3, 3, None, "@big_epic_lander", id="custom-exact"),
        pytest.param(3, 4, None, "@big_epic_lander", id="custom-above"),
        pytest.param(5, 6, "claude/opus", "claude/opus", id="explicit-model"),
    ],
)
def test_plan_file_preview_matches_threshold_aware_land_model(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    threshold: int,
    phase_count: int,
    model: str | None,
    expected_model: str,
) -> None:
    monkeypatch.setattr(
        "sase.bead.work.get_big_epic_phase_threshold",
        lambda: threshold,
    )
    source = project_dir / "threshold.md"
    source.write_text(
        epic_plan_with_phase_count(phase_count, model=model),
        encoding="utf-8",
    )

    work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=True,
    )

    assert f"Land    {expected_model}" in capsys.readouterr().out


def test_plan_file_json_output_is_one_stable_object(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )
    args = create_parser().parse_args(["bead", "work", str(source), "--json", "--yes"])

    handle_bead_work(args)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.out.count("\n") == 1
    assert payload["ok"] is True
    assert payload["mode"] == "plan_file"
    assert payload["epic_id"]
    assert len(payload["phase_bead_ids"]) == 3
    assert payload["launched_agent_names"][-1] == f"{payload['epic_id']}.land"


def test_bead_id_mode_rejects_parent_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["bead", "work", "sase-64", "--parent", "top-level"]
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_bead_work(args)

    assert excinfo.value.code == 1
    assert "only applies when the bead work target is a plan file" in (
        capsys.readouterr().err
    )


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--artifacts-dir", "/tmp/planner-artifacts"),
        ("--cl-name", "demo"),
    ],
)
def test_bead_id_mode_rejects_plan_file_only_linking_options_as_json(
    option: str,
    value: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["bead", "work", "sase-64", option, value, "--json"]
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_bead_work(args)

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "ok": False,
        "mode": "bead_id",
        "epic_id": "sase-64",
        "error": (
            f"{option} option only applies when the bead work target is a plan file"
        ),
    }


def test_bead_work_help_describes_both_targets_and_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "work", "--help"])

    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "Epic bead ID, or path to a validated epic plan file" in help_text
    assert "-j JSON, --json JSON" not in help_text
    assert "-a DIR" in help_text
    assert "--artifacts-dir DIR" in help_text
    assert "-c NAME" in help_text
    assert "--cl-name NAME" in help_text
    assert "-j, --json" in help_text
    assert "--dry-run" in help_text
    assert "--no-push" in help_text
    assert "--parent BEAD_ID|top-level" in help_text
    assert "--parent top-level" in help_text
