"""Runner coverage for launch-time clan summary persistence."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.agent.clan_membership import (
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.axe.clan_summary_script import (
    CLAN_SUMMARY_MAX_BYTES,
    CLAN_SUMMARY_STDERR_LOG,
    CLAN_SUMMARY_TIMEOUT_SECONDS,
    POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
    resolve_clan_summary_script,
)
from sase.axe.run_agent_directive_metadata import (
    epic_work_environment_from_metadata,
)
from sase.axe.run_agent_directives import (
    AgentInfo,
    extract_directives_and_write_meta,
)
from sase.axe.run_agent_markers import persist_refreshed_clan_summary
from sase.bead.work import (
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
)
from tests._agent_names_extract_fixtures import run_extract
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _write_script(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


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


def _extract_clan_info_and_meta(
    tmp_path: Path,
    clan_args: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path | None = None,
    clan_name: str = "research",
    declared: bool = True,
) -> tuple[AgentInfo, dict[str, object]]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir(exist_ok=True)
    artifacts_dir.mkdir(exist_ok=True)
    monkeypatch.setenv(
        CLAN_MEMBERSHIP_ENV,
        encode_clan_membership_plan(
            ClanMembershipPlan(clan_name=clan_name, generation="g1")
        ),
    )

    with (
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch(
            "sase.agent.names.agent_name_allocation_lock",
            return_value=nullcontext(),
        ),
        patch("sase.agent.names.claim_agent_name"),
        patch("sase.agent.names.claim_registered_clan_name"),
        patch(
            "sase.xprompt.process_xprompt_references",
            side_effect=lambda value, **_: value,
        ),
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        prompt = (
            f"%id:{clan_name}.worker\n%clan({clan_name}, {clan_args})\nDo work"
            if declared
            else f"%id(worker, clan={clan_name})\nDo work"
        )
        info = extract_directives_and_write_meta(
            prompt,
            str(workspace_dir),
            str(artifacts_dir),
            output_path=str(output_path) if output_path is not None else None,
        )

    persisted = json.loads(
        (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert info.meta == persisted
    assert persisted["agent_clan"] == clan_name
    assert persisted["agent_clan_generation"] == "g1"
    return info, persisted


def _extract_clan_meta(
    tmp_path: Path,
    clan_args: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path | None = None,
    clan_name: str = "research",
    declared: bool = True,
) -> dict[str, object]:
    return _extract_clan_info_and_meta(
        tmp_path,
        clan_args,
        monkeypatch,
        output_path=output_path,
        clan_name=clan_name,
        declared=declared,
    )[1]


def test_only_script_backed_declaration_carries_post_preparation_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(workspace_dir / "make_summary", "print('early')")

    script_info, _ = _extract_clan_info_and_meta(
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
    literal_info, _ = _extract_clan_info_and_meta(
        literal_root,
        "summary='stable literal'",
        monkeypatch,
    )
    assert literal_info.clan_summary_resolution is None

    joiner_root = tmp_path / "joiner"
    joiner_root.mkdir()
    joiner_info, _ = _extract_clan_info_and_meta(
        joiner_root,
        "",
        monkeypatch,
        declared=False,
    )
    assert joiner_info.clan_summary_resolution is None

    outside = run_extract(
        tmp_path / "outside",
        env_auto_dismiss=True,
        prompt="Do ordinary work",
    )
    assert outside["info"].clan_summary_resolution is None


def test_nominated_epic_joiner_persists_summary_and_refresh_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
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

    info, meta = _extract_clan_info_and_meta(
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
    _write_script(workspace_dir / "explicit_summary", "print('explicit')")
    _write_script(workspace_dir / "fallback_summary", "print('fallback')")
    monkeypatch.setenv(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV, "./fallback_summary")

    info, meta = _extract_clan_info_and_meta(
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
        info, meta = _extract_clan_info_and_meta(
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


@pytest.mark.parametrize("bare_name", [False, True], ids=["relative-path", "path"])
def test_summary_script_persists_output_env_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bare_name: bool,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    script = workspace_dir / "make_summary"
    _write_script(
        script,
        """import os
import sys
sys.stderr.write("summary diagnostic\\n")
print(
    os.environ["SASE_CLAN_NAME"]
    + "|"
    + os.environ["SASE_CLAN_GENERATION"]
    + "|"
    + os.environ["SASE_CLAN_TRIBE"]
    + "   "
)""",
    )
    script_ref = "make_summary" if bare_name else "./make_summary"
    if bare_name:
        monkeypatch.setenv("PATH", f"{workspace_dir}{os.pathsep}{os.environ['PATH']}")
    output_path = tmp_path / "agent.log"

    meta = _extract_clan_meta(
        tmp_path,
        f"tribe=research, summary_script={script_ref}",
        monkeypatch,
        output_path=output_path,
    )

    assert meta["clan_tribe"] == "research"
    assert meta["clan_summary"] == "research|g1|research"
    assert "summary diagnostic" in output_path.read_text(encoding="utf-8")
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "attempt: directive-extraction" in artifact
    assert "outcome: ok" in artifact
    assert f"argv: {script}" in artifact
    assert "SASE_CLAN_NAME" in artifact
    assert "SASE_CLAN_GENERATION" in artifact
    assert "SASE_CLAN_TRIBE" in artifact
    assert "summary diagnostic" in artifact
    assert "research|g1|research" not in artifact


@pytest.mark.parametrize(
    ("script_name", "script_value", "use_path"),
    [
        (
            "make_summary",
            'make_summary alpha "two words"',
            True,
        ),
        (
            "make_summary",
            './make_summary alpha "two words"',
            False,
        ),
    ],
    ids=["bare-command-argv", "relative-path-argv"],
)
def test_summary_script_persists_shell_quoted_argv_without_a_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script_name: str,
    script_value: str,
    use_path: bool,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / script_name,
        "import json\nimport sys\nprint(json.dumps(sys.argv[1:]))",
    )
    if use_path:
        monkeypatch.setenv("PATH", f"{workspace_dir}{os.pathsep}{os.environ['PATH']}")

    meta = _extract_clan_meta(
        tmp_path,
        f"summary_script=[[{script_value}]]",
        monkeypatch,
    )

    assert json.loads(str(meta["clan_summary"])) == ["alpha", "two words"]
    assert not (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).exists()


def test_summary_script_literal_executable_path_with_spaces_wins_before_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(workspace_dir / "make summary", "print('literal path')")

    meta = _extract_clan_meta(
        tmp_path,
        "summary_script=[[./make summary]]",
        monkeypatch,
    )

    assert meta["clan_summary"] == "literal path"


def test_summary_script_inherits_launch_environment_and_epic_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / "make_summary",
        """import json
import os
print(json.dumps({
    key: os.environ.get(key)
    for key in (
        "CUSTOM_LAUNCH_VALUE",
        "SASE_EPIC_PLAN_REF",
        "SASE_EPIC_PLAN_SNAPSHOT",
        "SASE_EPIC_BEAD_ID",
        "SASE_EPIC_CLAN_TRIBE",
        "SASE_CLAN_TRIBE",
    )
}))""",
    )
    monkeypatch.setenv("CUSTOM_LAUNCH_VALUE", "preserved")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "plans/epic.md")
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", "/state/epic.md")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-epic")
    monkeypatch.setenv("SASE_EPIC_CLAN_TRIBE", "epic")
    monkeypatch.setenv("SASE_CLAN_TRIBE", "ambient-value-must-not-leak")

    meta = _extract_clan_meta(
        tmp_path,
        "summary_script=./make_summary",
        monkeypatch,
    )

    assert meta["epic_plan_ref"] == "plans/epic.md"
    assert meta["epic_plan_snapshot"] == "/state/epic.md"
    assert meta["epic_bead_id"] == "sase-epic"
    inherited = json.loads(str(meta["clan_summary"]))
    assert inherited == {
        "CUSTOM_LAUNCH_VALUE": "preserved",
        "SASE_EPIC_PLAN_REF": "plans/epic.md",
        "SASE_EPIC_PLAN_SNAPSHOT": "/state/epic.md",
        "SASE_EPIC_BEAD_ID": "sase-epic",
        "SASE_EPIC_CLAN_TRIBE": "epic",
        "SASE_CLAN_TRIBE": None,
    }


def test_generic_plan_summary_entry_point_uses_epic_environment_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "epic.md").write_text(VALID_EPIC_PLAN, encoding="utf-8")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "epic.md")

    meta = _extract_clan_meta(
        tmp_path,
        "summary_script=sase_clan_summary_plan",
        monkeypatch,
    )

    rendered = Text.from_markup(str(meta["clan_summary"]))
    assert "▸ PLAN · epic · 1 phase" in rendered.plain
    assert "Title: Approved implementation" in rendered.plain
    assert "Implement the requested change" in rendered.plain


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

    info, early_meta = _extract_clan_info_and_meta(
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


def test_malformed_summary_script_quoting_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            'summary_script=[[missing "quote]]',
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "No closing quotation" in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: not-found" in artifact
    assert "resolution error: No closing quotation" in artifact


@pytest.mark.parametrize(
    ("script_body", "warning", "outcome", "stderr"),
    [
        (
            "import sys\nsys.stderr.write('exit detail\\n')\nraise SystemExit(7)",
            "exited with status 7",
            "exit-code",
            "exit detail",
        ),
        (
            "import sys\nsys.stderr.write('empty detail\\n')\nprint('   ')",
            "produced no output",
            "empty-output",
            "empty detail",
        ),
    ],
    ids=["non-zero", "empty"],
)
def test_failed_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    script_body: str,
    warning: str,
    outcome: str,
    stderr: str,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(workspace_dir / "make_summary", script_body)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "secret-plan-value")

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert warning in caplog.text
    assert stderr in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert f"outcome: {outcome}" in artifact
    assert "SASE_EPIC_PLAN_REF" in artifact
    assert "secret-plan-value" not in artifact
    assert stderr in artifact


def test_timed_out_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / "make_summary",
        "import sys\nimport time\nsys.stderr.write('timeout detail\\n')\n"
        "sys.stderr.flush()\ntime.sleep(60)",
    )
    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_TIMEOUT_SECONDS",
        0.3,
    )

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "timed out after 0.3s" in caplog.text
    assert "timeout detail" in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: timeout" in artifact
    assert "timeout detail" in artifact


def test_missing_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=definitely_missing_summary_script",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "was not found" in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: not-found" in artifact
    assert "definitely_missing_summary_script" in artifact


def test_summary_script_output_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / "make_summary",
        "print('x' * 40000, end='')",
    )

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert meta["clan_summary"] == "x" * CLAN_SUMMARY_MAX_BYTES
    assert "exceeded 32 KiB and was truncated" in caplog.text


def test_literal_summary_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = _extract_clan_meta(
        tmp_path,
        f"summary=[[{'x' * 40000}]]",
        monkeypatch,
    )

    assert meta["clan_summary"] == "x" * CLAN_SUMMARY_MAX_BYTES
