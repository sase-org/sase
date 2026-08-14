"""Metadata tests for agent directive extraction."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tests._agent_names_extract_fixtures import mock_provider, run_extract


class TestExtractDirectivesMetadata:
    def test_preserves_phase_launch_metadata_across_refreshed_extract(
        self, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        timestamp = "2026-07-13T16:00:00+00:00"
        durable_metadata = {
            "wait_completed_at": timestamp,
            "sdd_plan_path": "sdd/plans/202607/epic.md",
            "epic_bead_id": "sase-6k",
            "phase_bead_id": "sase-6k.3",
            "bead_id": "sase-6k.3",
            "plan_committed": True,
            "agent_family": "sase-6k",
            "agent_family_role": "phase",
            "agent_family_parallel": True,
            "parent_timestamp": "20260713150000",
            "workspace_num": 11,
        }
        (artifacts / "agent_meta.json").write_text(
            json.dumps({"pid": 123, **durable_metadata}),
            encoding="utf-8",
        )

        result = run_extract(
            tmp_path,
            env_auto_dismiss=True,
            prompt="%wait(60s)\ndo stuff",
        )

        for key, value in durable_metadata.items():
            assert result["info"].meta[key] == value
            assert result["meta"][key] == value

    def test_persists_wait_runners_metadata(self, tmp_path: Path) -> None:
        result = run_extract(
            tmp_path,
            env_auto_dismiss=True,
            prompt="%wait(runners=0)\ndo stuff",
        )

        assert result["info"].wait_runners == 0
        assert result["meta"]["wait_runners"] == 0

    def test_persists_explicit_wait_priority_metadata(self, tmp_path: Path) -> None:
        result = run_extract(
            tmp_path,
            env_auto_dismiss=True,
            prompt="%wait(priority=20)\ndo stuff",
        )

        assert result["info"].wait_priority == 20
        assert result["meta"]["wait_priority"] == 20

    def test_omitted_wait_priority_is_not_persisted(self, tmp_path: Path) -> None:
        result = run_extract(tmp_path, env_auto_dismiss=True)

        assert result["info"].wait_priority is None
        assert "wait_priority" not in result["meta"]

    def test_persists_wait_beads_metadata(self, tmp_path: Path) -> None:
        result = run_extract(
            tmp_path,
            env_auto_dismiss=True,
            prompt="%wait(bead=sase-87.2)\ndo stuff",
        )

        assert result["info"].wait_beads == ["sase-87.2"]
        assert result["info"].wait_names == []
        assert result["meta"]["wait_for_beads"] == ["sase-87.2"]
        assert "wait_for" not in result["meta"]

    def test_skips_auto_name_when_auto_dismiss(self, tmp_path: Path) -> None:
        """Auto-dismiss agents should not get an auto-assigned name."""
        result = run_extract(tmp_path, env_auto_dismiss=True)
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_writes_hidden_when_auto_dismiss(self, tmp_path: Path) -> None:
        """Auto-dismiss agents should be marked hidden in agent_meta.json."""
        result = run_extract(tmp_path, env_auto_dismiss=True)
        assert result["meta"].get("hidden") is True
        assert result["info"].hidden is True

    def test_normal_agent_gets_name(self, tmp_path: Path) -> None:
        """Without auto-dismiss, agents get an auto-assigned name."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, env_auto_dismiss=False)
        assert result["info"].name is not None
        assert result["meta"].get("name") is not None

    def test_tribe_wait_uses_neutral_auto_name(self, tmp_path: Path) -> None:
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.agent.names.allocate_wait_name",
                side_effect=AssertionError("tribe waits are not naming templates"),
            ),
            patch("sase.agent.names.get_next_auto_name", return_value="neutral"),
        ):
            result = run_extract(tmp_path, prompt="%wait:@epic\ndo stuff")

        assert result["info"].name == "neutral"
        assert result["info"].wait_names == ["@epic"]
        assert result["meta"]["wait_for"] == ["@epic"]

    def test_normal_agent_not_hidden(self, tmp_path: Path) -> None:
        """Without auto-dismiss, agents are not hidden."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, env_auto_dismiss=False)
        assert result["meta"].get("hidden") is not True
        assert result["info"].hidden is False

    def test_metadata_records_workspace_dir_without_vcs_provider(
        self, tmp_path: Path
    ) -> None:
        result = run_extract(tmp_path, env_auto_dismiss=True)
        expected = str(tmp_path / "workspace")
        assert result["meta"]["workspace_dir"] == expected
        assert result["meta"]["workspace_num"] == 0
        assert "vcs_provider" not in result["meta"]

    def test_metadata_records_claimed_workspace_num(self, tmp_path: Path) -> None:
        result = run_extract(
            tmp_path,
            env_auto_dismiss=True,
            workspace_num=12,
        )

        assert result["meta"]["workspace_num"] == 12

    def test_named_agent_writes_agent_metadata(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                prompt="%id:alpha do stuff",
                cl_name="feature-branch",
            )

        meta = result["meta"]
        assert meta["name"] == "alpha"
        assert meta["patch_name"] == "feature-branch"
        assert meta["changespec_name"] == "feature-branch"
        assert meta["cl_name"] == "feature-branch"

    def test_id_bead_publishes_metadata_and_environment(self, tmp_path: Path) -> None:
        result = run_extract(
            tmp_path,
            prompt="%id(bead=sase-8f.2)\nDo work",
        )

        assert result["info"].bead_id == "sase-8f.2"
        assert result["meta"]["bead_id"] == "sase-8f.2"
        assert result["bead_env"] == "sase-8f.2"

    def test_id_bead_accepts_matching_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_BEAD_ID", "sase-8f.2")

        result = run_extract(
            tmp_path,
            prompt="%id(worker, bead=sase-8f.2)\nDo work",
        )

        assert result["bead_env"] == "sase-8f.2"

    def test_id_bead_rejects_mismatching_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_BEAD_ID", "sase-other")

        with pytest.raises(RuntimeError, match="does not match SASE_BEAD_ID"):
            run_extract(
                tmp_path,
                prompt="%id(worker, bead=sase-8f.2)\nDo work",
            )

    def test_legacy_bead_environment_does_not_publish_launch_association(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_BEAD_ID", "sase-legacy")

        result = run_extract(tmp_path, prompt="%id:legacy-worker\nDo work")

        assert result["info"].bead_id is None
        assert "bead_id" not in result["meta"]

    def test_id_bead_coexists_with_epic_role_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.bead.work import SASE_EPIC_BEAD_ID_ENV, SASE_PHASE_BEAD_ID_ENV

        monkeypatch.setenv(SASE_EPIC_BEAD_ID_ENV, "sase-8f")
        monkeypatch.setenv(SASE_PHASE_BEAD_ID_ENV, "sase-8f.2")

        result = run_extract(
            tmp_path,
            prompt="%id(worker, bead=sase-8f.2)\nDo work",
        )

        assert result["meta"]["bead_id"] == "sase-8f.2"
        assert result["meta"]["epic_bead_id"] == "sase-8f"
        assert result["meta"]["phase_bead_id"] == "sase-8f.2"

    def test_unnamed_auto_dismiss_agent_writes_basic_metadata(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / "20260505120000"
        )
        workspace = tmp_path / "workspace"
        artifacts_dir.mkdir(parents=True)
        workspace.mkdir()

        from sase.axe.run_agent_phases import extract_directives_and_write_meta

        with (
            patch.dict(os.environ, {"SASE_AGENT_AUTO_DISMISS": "1"}, clear=False),
            patch(
                "sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p
            ),
            patch(
                "sase.llm_provider.registry.get_default_provider_name",
                return_value="test",
            ),
            patch(
                "sase.llm_provider.registry.get_provider",
                return_value=mock_provider(),
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("test", "test-model"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            info = extract_directives_and_write_meta(
                "do stuff",
                str(workspace),
                str(artifacts_dir),
                cl_name="feature-branch",
            )

        meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
        assert info.name is None
        assert "name" not in meta
        assert meta["workspace_dir"] == str(workspace)
        assert meta["patch_name"] == "feature-branch"
        assert meta["changespec_name"] == "feature-branch"


def test_auto_epic_writes_plan_auto_action(tmp_path: Path) -> None:
    """%auto:epic is plan-specific and does not enable full auto-approve."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = run_extract(tmp_path, prompt="%auto:epic\nDraft the epic")

    assert result["info"].plan is True
    assert result["info"].approve is False
    assert result["meta"]["plan"] is True
    assert result["meta"]["auto_approve_plan_action"] == "epic"
    assert "approve" not in result["meta"]


def test_auto_tale_writes_plan_auto_action(tmp_path: Path) -> None:
    """%auto:tale is plan-specific and does not enable full auto-approve."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = run_extract(tmp_path, prompt="%auto:tale\nDraft the tale")

    assert result["info"].plan is True
    assert result["info"].approve is False
    assert result["meta"]["plan"] is True
    assert result["meta"]["auto_approve_plan_action"] == "tale"
    assert "approve" not in result["meta"]
