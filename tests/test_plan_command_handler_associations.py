"""Association stamping tests for ``sase plan propose``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.frontmatter import parse_frontmatter
from tests.conftest import redirect_sase_home
from tests.plan_command_handler_helpers import (
    VALID_EPIC,
    VALID_TALE,
    assert_archived_associations as _assert_archived_associations,
    clear_bead_work_association_env,
    invoke_plan as _invoke_plan,
    make_artifacts_dir as _make_artifacts_dir,
)


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_bead_work_association_env(monkeypatch)


@pytest.mark.parametrize(
    ("content", "association_env", "expected_association"),
    [
        pytest.param(
            VALID_TALE,
            {"SASE_PHASE_BEAD_ID": "sase-bv.3"},
            {"bead": "sase-bv.3"},
            id="tale",
        ),
        pytest.param(
            VALID_EPIC,
            {"SASE_EPIC_BEAD_ID": "sase-bv"},
            {"parent_bead": "sase-bv"},
            id="epic",
        ),
    ],
)
def test_plan_command_stamps_proposer_before_formatting(
    content: str,
    association_env: dict[str, str],
    expected_association: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both plan tiers archive their acting agent and existing associations."""
    from sase.core.agent_identity_facade import globalize_owned_agent_name

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "proposed.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "q8--plan")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    for key, value in association_env.items():
        monkeypatch.setenv(key, value)

    formatted_inputs: list[str] = []

    def format_plan(raw: str) -> str:
        formatted_inputs.append(raw)
        return raw.replace("body", "formatted body")

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=format_plan,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    proposer = globalize_owned_agent_name("q8--plan")
    expected_fields = {**expected_association, "proposed_by": proposer}
    _assert_archived_associations(artifacts_dir, content, expected_fields)
    assert len(formatted_inputs) == 1
    stamped_frontmatter, _body, _had_frontmatter = parse_frontmatter(
        formatted_inputs[0]
    )
    assert stamped_frontmatter["proposed_by"] == proposer
    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    assert "formatted body" in Path(marker["plan_file"]).read_text(encoding="utf-8")


def test_plan_command_without_resolvable_agent_omits_proposer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launcher run marker alone is not recorded as an agent creator."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "human.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "1")
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


@pytest.mark.parametrize(
    (
        "content",
        "phase_bead",
        "epic_bead",
        "agent_bead",
        "plan_ref",
        "expected_fields",
    ),
    [
        pytest.param(
            VALID_TALE,
            "sase-7z.5",
            "sase-7z",
            None,
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
            None,
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
            None,
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
            None,
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
            None,
            {"bead": "sase-7z.5"},
            id="missing-plan-ref",
        ),
        pytest.param(
            VALID_TALE,
            None,
            None,
            "sase-iq",
            None,
            {"bead": "sase-iq"},
            id="task-worker-tale",
        ),
        pytest.param(
            VALID_EPIC,
            None,
            None,
            "sase-iq",
            None,
            {"parent_bead": "sase-iq"},
            id="task-worker-epic",
        ),
        pytest.param(
            VALID_TALE,
            "sase-7z.5",
            None,
            "sase-other",
            None,
            {"bead": "sase-7z.5"},
            id="tale-phase-precedes-agent-bead",
        ),
        pytest.param(
            VALID_EPIC,
            None,
            "sase-7z",
            "sase-other",
            None,
            {"parent_bead": "sase-7z"},
            id="epic-land-precedes-agent-bead",
        ),
        pytest.param(
            VALID_EPIC,
            None,
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
    agent_bead: str | None,
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
    if agent_bead is not None:
        monkeypatch.setenv("SASE_BEAD_ID", agent_bead)
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
