"""Tests for runner directive metadata environment transitions."""

from __future__ import annotations

import os

import pytest

from sase.axe.run_agent_directive_metadata import (
    EPIC_WORK_ENV_METADATA_NAMES,
    epic_work_environment_from_metadata,
    epic_work_metadata_from_env,
)


def test_epic_work_environment_mapping_consumes_and_reconstructs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_metadata: dict[str, str] = {}
    for index, (env_name, meta_name) in enumerate(
        EPIC_WORK_ENV_METADATA_NAMES,
        start=1,
    ):
        value = f"value-{index}"
        monkeypatch.setenv(env_name, value)
        expected_metadata[meta_name] = value

    metadata = epic_work_metadata_from_env()

    assert {key: metadata[key] for key in expected_metadata} == expected_metadata
    assert all(
        env_name not in os.environ for env_name, _ in EPIC_WORK_ENV_METADATA_NAMES
    )
    assert epic_work_environment_from_metadata(metadata) == {
        env_name: expected_metadata[meta_name]
        for env_name, meta_name in EPIC_WORK_ENV_METADATA_NAMES
    }


def test_epic_work_environment_reconstruction_uses_only_nonempty_strings() -> None:
    metadata: dict[str, object] = {
        "epic_plan_ref": "plans/epic.md",
        "epic_plan_snapshot": "/state/epic.md",
        "epic_bead_id": "",
        "phase_bead_id": 42,
        "clan_tribe": "   ",
    }

    assert epic_work_environment_from_metadata(metadata) == {
        "SASE_EPIC_PLAN_REF": "plans/epic.md",
        "SASE_EPIC_PLAN_SNAPSHOT": "/state/epic.md",
    }
