from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.repro import load_bundle
from sase.main.parser import create_parser
from sase.main.repro_handler import handle_repro_command


FIXTURE = Path(__file__).parent / "fixtures" / "agents_tab_disappear_reappear_v1.json"


@dataclass(frozen=True)
class _LoadResult:
    all_agents: list[Agent]
    dismissed_from_loader: list[Agent]
    load_state: AgentLoadState


def _agent(cl_name: str, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/private/private.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 13, 13, 0, 0),
        raw_suffix=suffix,
        workspace_num=101,
        workspace_dir="/home/bryan/projects/private_101",
        agent_name="private-agent",
    )


def test_parser_registers_repro_replay_options() -> None:
    parser = create_parser()

    args = parser.parse_args(
        [
            "repro",
            "replay",
            "bundle.json",
            "--assert-stable",
            "--json",
            "--write-artifacts",
            "artifacts",
            "--size",
            "100x30",
        ]
    )

    assert args.command == "repro"
    assert args.repro_subcommand == "replay"
    assert args.path == "bundle.json"
    assert args.assert_stable is True
    assert args.json is True
    assert args.write_artifacts == "artifacts"
    assert args.size == "100x30"


def test_replay_handler_emits_json_and_writes_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    artifacts = tmp_path / "artifacts"
    args = parser.parse_args(
        [
            "repro",
            "replay",
            str(FIXTURE),
            "--assert-stable",
            "--json",
            "--write-artifacts",
            str(artifacts),
        ]
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_repro_command(args)

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["bundle_path"] == str(FIXTURE)
    assert payload["result"] == "passed"
    assert payload["failed_invariants"] == []
    assert len(payload["state_steps"]) == 4
    assert len(payload["screen_paths"]) == 4
    assert len(payload["screenshot_paths"]) == 4
    assert Path(payload["screen_paths"][0]).is_file()
    assert (
        Path(payload["screenshot_paths"][0])
        .read_text(encoding="utf-8")
        .startswith("<svg")
    )


def test_replay_handler_json_error_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    missing = tmp_path / "missing.json"
    args = parser.parse_args(["repro", "replay", str(missing), "--json"])

    with pytest.raises(SystemExit) as excinfo:
        handle_repro_command(args)

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "error"
    assert payload["bundle_path"] == str(missing)
    assert "No such file" in payload["error"]


def test_capture_agents_tab_out_of_band_writes_redacted_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    output = tmp_path / "capture"
    args = parser.parse_args(
        [
            "repro",
            "capture",
            "agents-tab",
            "--output",
            str(output),
            "--json",
            "--size",
            "90x25",
        ]
    )

    tier1 = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )
    tier2 = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    def load_agents(
        _dismissed: set[tuple[AgentType, str, str | None]],
        *,
        patch_snapshot: object = None,
        full_history: bool = False,
    ) -> _LoadResult:
        del patch_snapshot
        suffix = "20260513130000" if not full_history else "20260513130100"
        return _LoadResult(
            all_agents=[_agent("secret/customer/project", suffix)],
            dismissed_from_loader=[],
            load_state=tier2 if full_history else tier1,
        )

    with (
        patch("sase.ace.dismissed_agents.load_dismissed_agents", return_value=set()),
        patch(
            "sase.ace.tui.actions.agents._loading_helpers.load_agents_from_disk_with_state",
            load_agents,
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_repro_command(args)

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "captured"
    assert payload["capture_mode"] == "out_of_band"
    bundle_path = Path(payload["bundle_path"])
    raw = bundle_path.read_text(encoding="utf-8")
    bundle = load_bundle(bundle_path)
    assert bundle.manifest.source == "out_of_band_filesystem_capture"
    assert bundle.manifest.commit_safe is True
    assert bundle.load_steps[0].metadata["capture_mode"] == "out_of_band"
    assert bundle.load_steps[0].metadata["terminal_size"] == {
        "width": 90,
        "height": 25,
    }
    assert "secret/customer/project" not in raw
    assert "private-agent" not in raw
