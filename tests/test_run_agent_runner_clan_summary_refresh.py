"""Runner coverage for post-preparation clan summary refreshes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.axe.run_agent_phases import ClanSummaryResolutionRequest
from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    BOOTSTRAP,
    LAUNCH,
    base_patches,
    exec_result,
    run_main,
)


def _summary_info() -> Any:
    return AGENT_INFO._replace(
        clan_summary_resolution=ClanSummaryResolutionRequest(
            script="./describe-clan",
            clan_name="epic-1",
            clan_generation="generation-1",
            clan_tribe="epic",
        ),
        meta={
            "pid": 1,
            "clan_summary": "early summary",
            "epic_plan_ref": "sase/repos/plans/epic.md",
            "epic_plan_snapshot": "/state/epic.md",
            "epic_bead_id": "epic-1",
            "phase_bead_id": "epic-1.1",
            "clan_tribe": "epic",
        },
    )


def _extract_and_seed(info: Any) -> Any:
    def extract(
        _prompt: str,
        _workspace_dir: str,
        artifacts_dir: str,
        **_kwargs: Any,
    ) -> Any:
        Path(artifacts_dir, "agent_meta.json").write_text(
            json.dumps(info.meta),
            encoding="utf-8",
        )
        return info

    return extract


def test_successful_post_preparation_summary_survives_later_metadata_write(
    tmp_path: Path,
) -> None:
    artifacts_dir = str(tmp_path / "artifacts")
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    info = _summary_info()
    events: list[str] = []
    patches = base_patches(artifacts_dir)
    patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = _extract_and_seed(info)

    def prepare(**_kwargs: Any) -> frozenset[str]:
        meta_path = Path(artifacts_dir, "agent_meta.json")
        current = json.loads(meta_path.read_text(encoding="utf-8"))
        current["wait_completed_at"] = "preserved-after-wait"
        meta_path.write_text(json.dumps(current), encoding="utf-8")
        os.environ["PREPARED_SUMMARY_INPUT"] = "ready"
        events.append("prepare")
        return frozenset()

    def resolve(_script: str, **kwargs: Any) -> str:
        environment = kwargs["environment"]
        assert environment["PREPARED_SUMMARY_INPUT"] == "ready"
        assert environment["SASE_EPIC_PLAN_REF"] == "sase/repos/plans/epic.md"
        assert environment["SASE_EPIC_PLAN_SNAPSHOT"] == "/state/epic.md"
        assert environment["SASE_EPIC_BEAD_ID"] == "epic-1"
        assert environment["SASE_PHASE_BEAD_ID"] == "epic-1.1"
        assert environment["SASE_EPIC_CLAN_TRIBE"] == "epic"
        events.append("summary")
        return "summary after preparation"

    def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
        assert ctx.agent_meta["clan_summary"] == "summary after preparation"
        assert ctx.agent_meta["wait_completed_at"] == "preserved-after-wait"
        assert ctx.agent_meta["sdd_base_sha"] == "base-sha"
        events.append("run")
        return exec_result(artifacts_dir)

    patches[f"{LAUNCH}.prepare_workspace_if_needed"] = prepare
    patches[f"{LAUNCH}.resolve_clan_summary_script"] = resolve
    patches[f"{LAUNCH}.capture_sdd_base_sha"] = lambda *_args: "base-sha"
    patches[f"{LAUNCH}.run_execution_loop"] = run_loop

    run_main(patches, tmp_path, workspace_dir=workspace_dir)

    persisted = json.loads(
        Path(artifacts_dir, "agent_meta.json").read_text(encoding="utf-8")
    )
    assert persisted["clan_summary"] == "summary after preparation"
    assert persisted["wait_completed_at"] == "preserved-after-wait"
    assert persisted["sdd_base_sha"] == "base-sha"
    assert events == ["prepare", "summary", "run"]


def test_unsuccessful_post_preparation_summary_keeps_earlier_success(
    tmp_path: Path,
) -> None:
    artifacts_dir = str(tmp_path / "artifacts")
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    info = _summary_info()
    patches = base_patches(artifacts_dir)
    patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = _extract_and_seed(info)
    patches[f"{LAUNCH}.resolve_clan_summary_script"] = lambda *_args, **_kwargs: None
    patches[f"{LAUNCH}.capture_sdd_base_sha"] = lambda *_args: "base-sha"
    patches[f"{LAUNCH}.run_execution_loop"] = lambda *_args: exec_result(artifacts_dir)

    run_main(patches, tmp_path, workspace_dir=workspace_dir)

    persisted = json.loads(
        Path(artifacts_dir, "agent_meta.json").read_text(encoding="utf-8")
    )
    assert persisted["clan_summary"] == "early summary"
    assert persisted["sdd_base_sha"] == "base-sha"
