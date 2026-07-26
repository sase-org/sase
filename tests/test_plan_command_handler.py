"""Tests for ``sase plan`` command handlers."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main import plan_command_handler
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_validate import validate_plan
from tests.conftest import redirect_sase_home


VALID_TALE = """---
tier: tale
title: Ship the planned change
goal: Ship the planned change
---
# Plan

body
"""

VALID_EPIC = """---
tier: epic
title: Ship the planned change
goal: Deliver the complete capability
phases:
  - id: implementation
    title: Implement the capability
    depends_on: []
    description: "implementation: build and verify the complete capability."
    size: small
---
# Plan

body
"""


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep proposal tests independent from the launching agent's bead env."""
    monkeypatch.delenv("SASE_PHASE_BEAD_ID", raising=False)
    monkeypatch.delenv("SASE_EPIC_BEAD_ID", raising=False)
    monkeypatch.delenv("SASE_EPIC_PLAN_REF", raising=False)


def _make_artifacts_dir(sase_home: Path) -> Path:
    """Create a realistic artifacts dir layout and return the timestamp dir."""
    artifacts_dir = (
        sase_home
        / "projects"
        / "demo"
        / "artifacts"
        / "workflow-plan"
        / "20260428120000"
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def _invoke_plan(plan_file: Path) -> int:
    """Invoke ``handle_plan_propose_command`` and return its exit code."""
    with pytest.raises(SystemExit) as exc_info:
        plan_command_handler.handle_plan_propose_command(str(plan_file))
    return int(exc_info.value.code)


def _assert_archived_associations(
    artifacts_dir: Path,
    content: str,
    expected_fields: dict[str, str],
) -> None:
    """Assert the archived plan has exactly the expected managed associations."""
    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    archived = Path(marker["plan_file"])
    archived_content = archived.read_text(encoding="utf-8")
    frontmatter, _body, _had_frontmatter = parse_frontmatter(archived_content)
    for field in ("bead", "parent", "parent_bead"):
        if field in expected_fields:
            assert frontmatter[field] == expected_fields[field]
        else:
            assert field not in frontmatter

    tier = "epic" if content == VALID_EPIC else "tale"
    validation = validate_plan(archived_content, tier)
    assert validation.ok
    assert validation.plan is not None
    assert validation.plan.bead == expected_fields.get("bead")
    assert validation.plan.parent == expected_fields.get("parent")
    assert validation.plan.parent_bead == expected_fields.get("parent_bead")


def test_plan_command_dispatches_propose() -> None:
    """``sase plan propose`` routes to the proposal handler."""
    args = argparse.Namespace(plan_subcommand="propose", plan_file="plan.md")

    with (
        patch.object(
            plan_command_handler,
            "handle_plan_propose_command",
            side_effect=SystemExit(0),
        ) as propose_mock,
        pytest.raises(SystemExit) as exc_info,
    ):
        plan_command_handler.handle_plan_command(args)

    assert exc_info.value.code == 0
    propose_mock.assert_called_once_with("plan.md")


def test_plan_command_writes_refresh_pulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sase plan propose`` pulses ``.ace_refresh_pulse`` in ``artifacts/``."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)
    project_artifacts_root = artifacts_dir.parents[1]

    plan_file = tmp_path / "my_plan.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    pulse_path = project_artifacts_root / ".ace_refresh_pulse"
    assert not pulse_path.exists()

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        kill_mock.side_effect = SystemExit(0)
        assert _invoke_plan(plan_file) == 0

    assert pulse_path.is_file()
    assert pulse_path.parent == project_artifacts_root
    # The pulse file lives directly inside the watched ``artifacts/`` dir, so
    # it is a direct child of a path the ACE inotify watcher actually sees.


def test_plan_command_pulse_mtime_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeat invocations rewrite the pulse so its mtime moves forward."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)
    pulse_path = artifacts_dir.parents[1] / ".ace_refresh_pulse"

    plan_file = tmp_path / "my_plan.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        kill_mock.side_effect = SystemExit(0)

        assert _invoke_plan(plan_file) == 0
        first_mtime = pulse_path.stat().st_mtime_ns

        # The first invocation consumes the scratch plan, so recreate it before
        # proposing again.
        plan_file.write_text(VALID_TALE, encoding="utf-8")

        # Force the filesystem clock to advance so mtime resolution differences
        # don't cause flakes on filesystems with coarse mtime granularity.
        time.sleep(0.01)
        assert _invoke_plan(plan_file) == 0
        second_mtime = pulse_path.stat().st_mtime_ns

    assert second_mtime > first_mtime


def test_plan_command_moves_source_into_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sase plan propose`` archives the formatted plan and consumes the source."""
    import json

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)

    plan_file = tmp_path / "sase_plan_feature.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    formatted = VALID_TALE.replace("body", "formatted body")
    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw.replace("body", "formatted body"),
        ),
    ):
        kill_mock.side_effect = SystemExit(0)
        assert _invoke_plan(plan_file) == 0

    # The scratch source file is consumed by the move into the archive.
    assert not plan_file.exists()

    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    # ``plan_file`` points at the durable archive copy, which exists on disk.
    archived_path = Path(marker["plan_file"])
    assert archived_path.is_file()
    assert archived_path.parent.parent == sase_home / "plans"
    assert archived_path.name == "feature.md"  # "sase_plan_" prefix stripped
    # The archive holds the prettier-formatted content, not the raw source.
    assert archived_path.read_text(encoding="utf-8") == formatted
    # ``original_file`` is retained as provenance even though it no longer exists.
    assert marker["original_file"] == str(plan_file.resolve())


def test_plan_command_accepts_valid_epic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An authored epic is validated against the epic schema before queuing."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "epic.md"
    plan_file.write_text(VALID_EPIC, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    kill_mock.assert_called_once_with(str(artifacts_dir))
    assert (artifacts_dir / ".sase_plan_pending").is_file()


@pytest.mark.parametrize(
    ("content", "phase_bead", "epic_bead", "plan_ref", "expected_fields"),
    [
        pytest.param(
            VALID_TALE,
            "sase-7z.5",
            "sase-7z",
            "sase/repos/plans/202607/parent.md",
            {
                "bead": "sase-7z.5",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="tale-phase-agent",
        ),
        pytest.param(
            VALID_TALE,
            None,
            "sase-7z",
            "sase/repos/plans/202607/parent.md",
            {
                "bead": "sase-7z",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="tale-land-agent",
        ),
        pytest.param(
            VALID_EPIC,
            "sase-7z.5",
            "sase-7z",
            "sase/repos/plans/202607/parent.md",
            {
                "parent_bead": "sase-7z.5",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="epic-phase-precedes-epic",
        ),
        pytest.param(
            VALID_EPIC,
            None,
            "sase-7z",
            "sase/repos/plans/202607/parent.md",
            {
                "parent_bead": "sase-7z",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="epic-land-agent",
        ),
        pytest.param(
            VALID_TALE,
            "sase-7z.5",
            "sase-7z",
            None,
            {"bead": "sase-7z.5"},
            id="missing-plan-ref",
        ),
        pytest.param(
            VALID_EPIC,
            None,
            None,
            None,
            {},
            id="outside-bead-work",
        ),
    ],
)
def test_plan_command_stamps_associations_from_bead_work_env(
    content: str,
    phase_bead: str | None,
    epic_bead: str | None,
    plan_ref: str | None,
    expected_fields: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proposals inherit tier-specific bead and parent-plan associations."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    if phase_bead is not None:
        monkeypatch.setenv("SASE_PHASE_BEAD_ID", phase_bead)
    if epic_bead is not None:
        monkeypatch.setenv("SASE_EPIC_BEAD_ID", epic_bead)
    if plan_ref is not None:
        monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(artifacts_dir, content, expected_fields)


@pytest.mark.parametrize(
    ("content", "metadata", "expected_fields"),
    [
        pytest.param(
            VALID_TALE,
            {
                "phase_bead_id": "sase-meta.1",
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/parent.md",
            },
            {
                "bead": "sase-meta.1",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="tale-phase-agent",
        ),
        pytest.param(
            VALID_TALE,
            {
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/parent.md",
            },
            {
                "bead": "sase-meta",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="tale-land-agent",
        ),
        pytest.param(
            VALID_EPIC,
            {
                "phase_bead_id": "sase-meta.1",
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/parent.md",
            },
            {
                "parent_bead": "sase-meta.1",
                "parent": "sase/repos/plans/202607/parent.md",
            },
            id="child-epic",
        ),
        pytest.param(
            VALID_TALE,
            {"phase_bead_id": "sase-meta.1"},
            {"bead": "sase-meta.1"},
            id="missing-plan-ref",
        ),
    ],
)
def test_plan_command_stamps_associations_from_agent_metadata(
    content: str,
    metadata: dict[str, str],
    expected_fields: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production proposals inherit associations from ``agent_meta.json``."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(artifacts_dir, content, expected_fields)


def test_plan_command_association_env_overrides_agent_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-empty env associations override the same metadata fields."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "phase_bead_id": "sase-meta.1",
                "epic_bead_id": "sase-meta",
                "epic_plan_ref": "sase/repos/plans/202607/meta-parent.md",
            }
        ),
        encoding="utf-8",
    )
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_PHASE_BEAD_ID", "sase-env.1")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-env")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "sase/repos/plans/202607/env-parent.md")

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(
        artifacts_dir,
        VALID_TALE,
        {
            "bead": "sase-env.1",
            "parent": "sase/repos/plans/202607/env-parent.md",
        },
    )


@pytest.mark.parametrize("agent_meta_contents", [None, "{not-json"])
def test_plan_command_ignores_missing_or_malformed_agent_metadata(
    agent_meta_contents: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable agent metadata leaves otherwise valid proposals unstamped."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    if agent_meta_contents is not None:
        (artifacts_dir / "agent_meta.json").write_text(
            agent_meta_contents, encoding="utf-8"
        )
    plan_file = tmp_path / "unassociated.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(artifacts_dir, VALID_TALE, {})


def test_plan_command_stamps_after_runner_consumes_bead_work_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production env-to-marker transition preserves proposal stamps."""
    from sase.axe.run_agent_directive_metadata import epic_work_metadata_from_env

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "associated.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_PHASE_BEAD_ID", "sase-prod.1")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-prod")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "sase/repos/plans/202607/prod-parent.md")

    metadata = epic_work_metadata_from_env()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    assert "SASE_PHASE_BEAD_ID" not in os.environ
    assert "SASE_EPIC_BEAD_ID" not in os.environ
    assert "SASE_EPIC_PLAN_REF" not in os.environ

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    _assert_archived_associations(
        artifacts_dir,
        VALID_TALE,
        {
            "bead": "sase-prod.1",
            "parent": "sase/repos/plans/202607/prod-parent.md",
        },
    )


@pytest.mark.parametrize(
    ("content", "auto_action", "expected_tier", "expected_code"),
    [
        ("# Plan\n\nbody\n", None, "tale", "frontmatter-missing"),
        (
            """---
tier: tale
goal: '   '
---
# Plan
""",
            None,
            "tale",
            "value-empty",
        ),
        (
            """---
tier: epic
title: Empty epic
goal: Deliver it
phases: []
---
# Plan
""",
            None,
            "epic",
            "phases-empty",
        ),
        (VALID_TALE, "epic", "tale", "invalid-auto-argument"),
        (VALID_EPIC, "tale", "epic", "invalid-auto-argument"),
    ],
)
def test_plan_command_rejects_invalid_or_auto_mismatched_plan_without_side_effects(
    content: str,
    auto_action: str | None,
    expected_tier: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed gate leaves the source and proposal queue untouched."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "invalid.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    if auto_action is not None:
        monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE_PLAN_ACTION", auto_action)

    with (
        patch("sase.main.plan_propose_handler.kill_agent_runner_group") as kill_mock,
        patch("sase.file_references.format_with_prettier") as format_mock,
    ):
        assert _invoke_plan(plan_file) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"error [{expected_code}]" in captured.err.lower()
    if expected_code == "invalid-auto-argument":
        assert f"conflicts with the authored {expected_tier} plan tier" in captured.err
    else:
        assert f"Expected {expected_tier} frontmatter schema" in captured.err
        assert "Validation failed" in captured.err
    assert plan_file.read_text(encoding="utf-8") == content
    assert not (artifacts_dir / ".sase_plan_pending").exists()
    assert not (artifacts_dir.parents[1] / ".ace_refresh_pulse").exists()
    format_mock.assert_not_called()
    kill_mock.assert_not_called()
