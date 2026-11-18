"""Typed chop dispatch and runner coverage.

Split from ``tests.test_axe_chop_proposal_launch``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_hold import LAUNCH_HOLD_KEY_ENV
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.chop_typed_admission import make_axe_chop_agent_dispatcher
from sase.axe.config import ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.core.agent_launch_wire import AgentUnitWire, HoldFieldsWire, LaunchUnitWire
from sase.feature_flags import override_flags

from tests._axe_chop_proposal_launch_helpers import (
    config,
    known_project_resolver,
    patch_condition_workspace_lease,
    result_script,
)

pytest_plugins = ["tests.axe_chop_runner_fixtures"]

__all__ = [
    "test_runner_all_skipped_typed_admission_succeeds_without_agent",
    "test_typed_chop_dispatch_carries_launch_hold_key",
    "test_typed_chop_dispatch_fails_closed_without_workspace_metadata",
]


def test_typed_chop_dispatch_fails_closed_without_workspace_metadata() -> None:
    unit = LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="Review docs.",
            identity="refresh",
            identity_explicit=True,
        ),
    )

    def _launch(*args: object, **kwargs: object) -> list[SimpleNamespace]:
        raise AssertionError("missing workspace metadata reached the launcher")

    dispatcher = make_axe_chop_agent_dispatcher(
        {
            "unit_dispatch_metadata": {
                "unit-1": {
                    "logical_id": "unit-1",
                    "lumberjack_name": "docs",
                    "chop_name": "docs",
                    "run_id": "run-missing-workspace",
                    "env": {},
                }
            }
        },
        launch_agents_from_cwd_fn=_launch,
    )
    assert dispatcher is not None

    ok, identity, message, results = dispatcher(unit, "fp-missing-workspace")

    assert ok is False
    assert identity is None
    assert message == "missing AXE job workspace for unit-1"
    assert results == []


def test_typed_chop_dispatch_carries_launch_hold_key() -> None:
    unit = LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="Review docs.",
            identity="refresh",
            identity_explicit=True,
            hold=HoldFieldsWire(future=True),
        ),
    )
    calls: list[dict[str, str]] = []

    def _launch(
        prompt: str, *, extra_env: dict[str, str], origin: object = None
    ) -> list[SimpleNamespace]:
        del prompt, origin
        calls.append(dict(extra_env))
        return [SimpleNamespace(pid=501, agent_name="refresh")]

    dispatcher = make_axe_chop_agent_dispatcher(
        {
            "request_id": "req-axe-hold",
            "unit_dispatch_metadata": {
                "unit-1": {
                    "logical_id": "unit-1",
                    "lumberjack_name": "docs",
                    "chop_name": "docs",
                    "run_id": "run-hold",
                    "workspace": "git:sase",
                    "env": {},
                }
            },
        },
        launch_agents_from_cwd_fn=_launch,
    )
    assert dispatcher is not None

    with override_flags():
        ok, identity, message, results = dispatcher(unit, "fp-axe-hold")

    assert ok is True
    assert identity == "refresh"
    assert message is None
    assert len(results) == 1
    assert calls[0][LAUNCH_HOLD_KEY_ENV] == "launch:req-axe-hold/unit-1"


def test_runner_all_skipped_typed_admission_succeeds_without_agent(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "%if::\n```bash\nexit 1\n```\nReview stale docs.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:stale",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: known_project_resolver(repo),
    )
    patch_condition_workspace_lease(monkeypatch, repo)

    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_batch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=config(tmp_path),
        )

    assert outcome.status == "action_succeeded"
    launch_batch.assert_not_called()
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", outcome.run_id).read_text(
        encoding="utf-8"
    )
    assert "Typed admission:" in output
    assert "1 skipped" in output
    assert "once-per duplicate" not in output
