"""``sase plan propose`` derives candidate links for the archived plan."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.feature_flags import override_flags
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests.conftest import redirect_sase_home
from tests.plan_command_handler_helpers import (
    clear_bead_work_association_env,
    invoke_plan as _invoke_plan,
    make_artifacts_dir as _make_artifacts_dir,
)

_PLAN_WITH_BEAD = """---
tier: tale
title: Ship the planned change
goal: Ship the planned change
size: small
bead: sase-xx
---
# Plan

body
"""


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_bead_work_association_env(monkeypatch)


def test_flag_off_archives_the_plan_without_deriving_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "my_plan.md"
    plan_file.write_text(_PLAN_WITH_BEAD, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    store = ArtifactLinkStore(
        project_key="test-project", sidecar_roots={"plan": sase_home / "plans"}
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store", lambda: store
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_derivation._known_bead_ids",
        lambda _store: frozenset({"sase-xx"}),
    )

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch("sase.file_references.format_with_prettier", side_effect=lambda raw: raw),
        override_flags(),
    ):
        assert _invoke_plan(plan_file) == 0

    assert (artifacts_dir / ".sase_plan_pending").is_file()
    assert store.load_aggregate()["rows"] == []


def test_flag_on_derives_an_implements_row_for_the_archived_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "my_plan.md"
    plan_file.write_text(_PLAN_WITH_BEAD, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    store = ArtifactLinkStore(
        project_key="test-project", sidecar_roots={"plan": sase_home / "plans"}
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store", lambda: store
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_derivation._known_bead_ids",
        lambda _store: frozenset({"sase-xx"}),
    )

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ),
        patch("sase.file_references.format_with_prettier", side_effect=lambda raw: raw),
        override_flags(artifact_link_derivation=True),
    ):
        assert _invoke_plan(plan_file) == 0

    rows = store.load_aggregate()["rows"]
    assert len(rows) == 1
    assert rows[0]["relation"] == "implements"
    assert rows[0]["target_ref"] == "bead:sase-xx"
    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    archived_name = Path(marker["plan_file"]).name
    assert rows[0]["source_ref"].endswith(archived_name)
