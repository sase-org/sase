"""Runner coverage for launch-time clan summary persistence and refresh."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.axe.clan_summary_script import (
    CLAN_SUMMARY_STDERR_LOG,
    CLAN_SUMMARY_TIMEOUT_SECONDS,
    POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
    resolve_clan_summary_script,
)
from sase.axe.run_agent_directive_metadata import (
    epic_work_environment_from_metadata,
)
from sase.axe.run_agent_markers import persist_refreshed_clan_summary
from sase.bead.work import (
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
)
from tests._clan_summary_persistence_helpers import (
    extract_clan_info_and_meta,
    extract_outside_clan,
    write_script,
)


def test_summary_script_default_timeout_covers_blocking_refresh() -> None:
    assert CLAN_SUMMARY_TIMEOUT_SECONDS == 20.0


def test_refreshed_summary_merge_preserves_current_disk_and_memory_metadata(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 100,
                "clan_summary": "early",
                "wait_completed_at": "after-wait",
                "disk_only": "preserved",
            }
        ),
        encoding="utf-8",
    )
    agent_meta: dict[str, object] = {
        "pid": 200,
        "clan_summary": "early",
        "memory_only": "preserved",
    }

    with patch(
        "sase.axe.run_agent_markers.update_agent_artifact_index_for_marker_mutation"
    ):
        merged = persist_refreshed_clan_summary(
            str(artifacts_dir),
            agent_meta,
            "after preparation",
        )

    assert merged == agent_meta
    assert merged["clan_summary"] == "after preparation"
    assert merged["wait_completed_at"] == "after-wait"
    assert merged["disk_only"] == "preserved"
    assert merged["memory_only"] == "preserved"
    assert json.loads((artifacts_dir / "agent_meta.json").read_text()) == merged


def test_only_script_backed_declaration_carries_post_preparation_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(workspace_dir / "make_summary", "print('early')")

    script_info, _ = extract_clan_info_and_meta(
        tmp_path,
        "tribe=study, summary_script=./make_summary",
        monkeypatch,
    )
    request = script_info.clan_summary_resolution
    assert request is not None
    assert request.script == "./make_summary"
    assert request.clan_name == "research"
    assert request.clan_generation == "g1"
    assert request.clan_tribe == "study"
    with pytest.raises(FrozenInstanceError):
        request.script = "changed"  # type: ignore[misc]

    literal_root = tmp_path / "literal"
    literal_root.mkdir()
    literal_info, _ = extract_clan_info_and_meta(
        literal_root,
        "summary='stable literal'",
        monkeypatch,
    )
    assert literal_info.clan_summary_resolution is None

    joiner_root = tmp_path / "joiner"
    joiner_root.mkdir()
    joiner_info, _ = extract_clan_info_and_meta(
        joiner_root,
        "",
        monkeypatch,
        declared=False,
    )
    assert joiner_info.clan_summary_resolution is None

    outside = extract_outside_clan(tmp_path / "outside")
    assert outside.clan_summary_resolution is None


def test_nominated_epic_joiner_persists_summary_and_refresh_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(
        workspace_dir / "make_summary",
        """import json
import os
print(json.dumps({
    "name": os.environ["SASE_CLAN_NAME"],
    "generation": os.environ["SASE_CLAN_GENERATION"],
    "tribe": os.environ["SASE_CLAN_TRIBE"],
    "host_script": os.environ.get("SASE_EPIC_CLAN_SUMMARY_SCRIPT"),
}))""",
    )
    monkeypatch.setenv(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV, "./make_summary")
    monkeypatch.setenv(SASE_EPIC_CLAN_TRIBE_ENV, "epic")

    info, meta = extract_clan_info_and_meta(
        tmp_path,
        "",
        monkeypatch,
        clan_name="race-epic",
        declared=False,
    )

    request = info.clan_summary_resolution
    assert request is not None
    assert request.script == "./make_summary"
    assert request.clan_name == "race-epic"
    assert request.clan_generation == "g1"
    assert request.clan_tribe == "epic"
    assert meta["clan_tribe"] == "epic"
    assert json.loads(str(meta["clan_summary"])) == {
        "name": "race-epic",
        "generation": "g1",
        "tribe": "epic",
        "host_script": None,
    }
    assert SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in os.environ
    assert SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in meta


def test_declared_summary_script_precedes_epic_joiner_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(workspace_dir / "explicit_summary", "print('explicit')")
    write_script(workspace_dir / "fallback_summary", "print('fallback')")
    monkeypatch.setenv(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV, "./fallback_summary")

    info, meta = extract_clan_info_and_meta(
        tmp_path,
        "tribe=epic, summary_script=./explicit_summary",
        monkeypatch,
    )

    assert meta["clan_summary"] == "explicit"
    assert info.clan_summary_resolution is not None
    assert info.clan_summary_resolution.script == "./explicit_summary"
    assert SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in os.environ


def test_missing_nominated_epic_joiner_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(
        SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
        "definitely_missing_epic_summary_script",
    )
    monkeypatch.setenv(SASE_EPIC_CLAN_TRIBE_ENV, "epic")

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        info, meta = extract_clan_info_and_meta(
            tmp_path,
            "",
            monkeypatch,
            clan_name="race-epic",
            declared=False,
        )

    assert "clan_summary" not in meta
    assert "was not found" in caplog.text
    assert info.clan_summary_resolution is not None
    assert (
        info.clan_summary_resolution.script == "definitely_missing_epic_summary_script"
    )


def test_post_preparation_attempt_diagnostics_have_distinct_labels(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    for attempt_label in (
        "directive-extraction",
        POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
    ):
        assert (
            resolve_clan_summary_script(
                "./not-yet-available",
                workspace_dir=str(tmp_path),
                clan_name="race-epic",
                clan_generation="g1",
                clan_tribe="epic",
                artifacts_dir=str(artifacts_dir),
                attempt_label=attempt_label,
            )
            is None
        )

    artifact = (artifacts_dir / CLAN_SUMMARY_STDERR_LOG).read_text(encoding="utf-8")
    assert "attempt: directive-extraction" in artifact
    assert "attempt: post-workspace-preparation" in artifact
    assert artifact.count("outcome: not-found") == 2


def test_plan_race_refresh_replaces_identity_fallback_with_complete_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_ref = "sase/repos/plans/202607/race-epic.md"
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "race-epic")
    monkeypatch.setenv("SASE_PHASE_BEAD_ID", "race-epic.1")
    monkeypatch.setenv("SASE_EPIC_CLAN_TRIBE", "epic")

    info, early_meta = extract_clan_info_and_meta(
        tmp_path,
        "tribe=epic, summary_script=sase_clan_summary_epic",
        monkeypatch,
        clan_name="race-epic",
    )
    request = info.clan_summary_resolution
    assert request is not None
    assert Text.from_markup(str(early_meta["clan_summary"])).plain == "EPIC race-epic"

    plan = tmp_path / "workspace" / plan_ref
    plan.parent.mkdir(parents=True)
    plan.write_text(
        """---
tier: epic
title: Race-resolved epic
goal: Restore complete clan context after workspace preparation
phases:
  - id: prepare
    title: Prepare every repository
    depends_on: []
    description: Materialize the plan and summary inputs.
    size: small
  - id: refresh
    title: Refresh the persisted clan summary
    depends_on: [prepare]
    description: Replace the identity fallback after preparation.
    size: medium
---
# Plan

Prepare the workspace, then refresh the clan summary.
""",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        **epic_work_environment_from_metadata(info.meta),
    }

    refreshed = resolve_clan_summary_script(
        request.script,
        workspace_dir=str(tmp_path / "workspace"),
        clan_name=request.clan_name,
        clan_generation=request.clan_generation,
        clan_tribe=request.clan_tribe,
        artifacts_dir=str(tmp_path / "artifacts"),
        attempt_label=POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
        environment=environment,
    )

    assert refreshed is not None
    with patch(
        "sase.axe.run_agent_markers.update_agent_artifact_index_for_marker_mutation"
    ):
        persist_refreshed_clan_summary(
            str(tmp_path / "artifacts"),
            info.meta,
            refreshed,
        )
    persisted = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    rendered = Text.from_markup(str(persisted["clan_summary"]))
    assert "Title: Race-resolved epic" in rendered.plain
    assert "Goal: Restore complete clan context after workspace preparation" in (
        rendered.plain
    )
    assert "Prepare every repository" in rendered.plain
    assert "Refresh the persisted clan summary" in rendered.plain
    assert rendered.plain != "EPIC race-epic"
