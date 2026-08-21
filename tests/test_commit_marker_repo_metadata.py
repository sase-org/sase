"""Tests for how commit markers scope repo names and agent_meta.json updates."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit.commit_tracking import (
    write_commit_diff_artifact,
    write_result_marker,
)
from tests._sdd_commit_helpers import make_sidecar_workspace_topology


class TestWriteResultMarkerRepoMetadata:
    """Verify repo-name resolution and primary-commit metadata persistence."""

    def test_persists_primary_commit_metadata_without_graph_relationships(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            diff_path = str(Path(tmpdir) / "commit.diff")
            payload = {"message": "fix: bug", "bead_id": "sase-1.2"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    diff_path,
                    "abc123",
                    "proj_feat_1",
                    entry_id="7",
                )

            meta = json.loads(meta_path.read_text())
            assert meta == {
                "name": "agent-alpha",
                "commit_diff_path": diff_path,
                "commit_patch_name": "proj_feat_1",
                "commit_changespec_name": "proj_feat_1",
            }
            assert "commit_entry_id" not in meta
            assert "commit_result" not in meta
            update_index.assert_called_once_with(tmpdir)

    @pytest.mark.parametrize("existing_diff", [None, "/tmp/primary.diff"])
    def test_external_commit_neither_seeds_nor_overwrites_primary_diff(
        self,
        tmp_path: Path,
        existing_diff: str | None,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        sidecar = primary / ".sase" / "sdd"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        (sidecar / ".git").mkdir(parents=True)
        meta = {
            "name": "agent-alpha",
            "workspace_dir": str(primary),
            "commit_changespec_name": "primary_spec",
        }
        if existing_diff is not None:
            meta["commit_diff_path"] = existing_diff
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(sidecar)),
            patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index,
        ):
            write_result_marker(
                "create_commit",
                {"message": "docs: sidecar"},
                "/tmp/sidecar.diff",
                "def456",
                "sidecar_spec",
            )

        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted.get("commit_diff_path") == existing_diff
        assert persisted["commit_changespec_name"] == "primary_spec"
        results = json.loads(
            (artifacts_dir / "commit_results.json").read_text(encoding="utf-8")
        )
        assert results[0]["cwd"] == str(sidecar)
        assert results[0]["diff_path"] == "/tmp/sidecar.diff"
        update_index.assert_not_called()

    def test_explicit_sidecar_commit_cwd_ignores_ambient_primary_cwd(
        self,
        tmp_path: Path,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        sidecar = primary / ".sase" / "sdd"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        (sidecar / ".git").mkdir(parents=True)
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "name": "agent-alpha",
                    "workspace_dir": str(primary),
                    "commit_diff_path": "/tmp/primary.diff",
                    "commit_changespec_name": "primary_spec",
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(primary)),
            patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index,
        ):
            write_result_marker(
                "create_commit",
                {"message": "docs: sidecar"},
                "/tmp/sidecar.diff",
                "def456",
                "sidecar_spec",
                commit_cwd=str(sidecar),
            )

        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted["commit_diff_path"] == "/tmp/primary.diff"
        assert persisted["commit_changespec_name"] == "primary_spec"
        results = json.loads(
            (artifacts_dir / "commit_results.json").read_text(encoding="utf-8")
        )
        assert results[0]["cwd"] == str(sidecar)
        update_index.assert_not_called()

    def test_primary_subdirectory_commit_updates_primary_diff(
        self,
        tmp_path: Path,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        source_dir = primary / "src"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        source_dir.mkdir()
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps({"workspace_dir": str(primary)}),
            encoding="utf-8",
        )

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(source_dir)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "fix: primary"},
                "/tmp/primary.diff",
                "abc123",
                "primary_spec",
            )

        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted["commit_diff_path"] == "/tmp/primary.diff"
        assert persisted["commit_changespec_name"] == "primary_spec"

    def test_sidecar_commit_records_role_name(
        self,
        tmp_path: Path,
    ) -> None:
        topology = make_sidecar_workspace_topology(
            tmp_path,
            owner="sase-org",
            project="sase",
        )
        artifacts_dir = tmp_path / "artifacts"
        sidecar = topology.plans
        artifacts_dir.mkdir()
        sidecar.mkdir(parents=True)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"workspace_dir": str(topology.workspace)}),
            encoding="utf-8",
        )

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(sidecar)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "docs: update plan"},
                "/tmp/plans.diff",
                "abc123",
                None,
            )

        marker = json.loads(
            (artifacts_dir / "commit_result.json").read_text(encoding="utf-8")
        )
        assert marker["repo_name"] == "plans"

    def test_beads_sidecar_commit_records_role_name(
        self,
        tmp_path: Path,
    ) -> None:
        topology = make_sidecar_workspace_topology(
            tmp_path,
            owner="sase-org",
            project="sase",
        )
        artifacts_dir = tmp_path / "artifacts"
        beads = topology.beads
        artifacts_dir.mkdir()
        beads.mkdir(parents=True)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"workspace_dir": str(topology.workspace)}),
            encoding="utf-8",
        )

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(beads)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "chore(beads): update state"},
                "/tmp/beads.diff",
                "def456",
                None,
            )

        marker = json.loads(
            (artifacts_dir / "commit_result.json").read_text(encoding="utf-8")
        )
        assert marker["repo_name"] == "beads"

    @pytest.mark.parametrize(
        ("clone_parts", "repo_name"),
        [
            (("gh", "acme", "widget"), "gh:acme/widget"),
            (("projects", "dotdrop"), "dotdrop"),
        ],
    )
    def test_external_commit_records_canonical_repo_and_own_diff(
        self,
        tmp_path: Path,
        clone_parts: tuple[str, ...],
        repo_name: str,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        external = primary.joinpath("sase", "repos", "external", *clone_parts)
        source_dir = external / "src"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        (external / ".git").mkdir(parents=True)
        source_dir.mkdir()
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "workspace_dir": str(primary),
                    "commit_diff_path": "/tmp/primary.diff",
                    "commit_changespec_name": "primary_spec",
                }
            ),
            encoding="utf-8",
        )
        diff_path = write_commit_diff_artifact(
            "diff --git a/src/demo.py b/src/demo.py\n",
            artifacts_dir=artifacts_dir,
        )
        assert diff_path is not None

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(source_dir)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "fix: external"},
                diff_path,
                "def456",
                "external_spec",
            )

        results = json.loads(
            (artifacts_dir / "commit_results.json").read_text(encoding="utf-8")
        )
        assert results[0]["repo_name"] == repo_name
        assert results[0]["commit_diff_path"] == diff_path
        assert Path(diff_path).read_text(encoding="utf-8").startswith("diff --git")
        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted["commit_diff_path"] == "/tmp/primary.diff"
        assert persisted["commit_changespec_name"] == "primary_spec"

    def test_persists_patch_without_diff_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            payload = {"message": "fix: bug"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    None,
                    "abc123",
                    "proj_feat_1",
                    entry_id="7",
                )

            meta = json.loads(meta_path.read_text())
            assert meta == {
                "name": "agent-alpha",
                "commit_patch_name": "proj_feat_1",
                "commit_changespec_name": "proj_feat_1",
            }
            update_index.assert_called_once_with(tmpdir)

    def test_primary_commit_metadata_skips_noop_rewrite(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        meta = {
            "workspace_dir": str(primary),
            "commit_diff_path": "/tmp/primary.diff",
            "commit_patch_name": "primary_spec",
            "commit_changespec_name": "primary_spec",
        }
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(primary)),
            patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index,
        ):
            write_result_marker(
                "create_commit",
                {"message": "fix: primary"},
                "/tmp/primary.diff",
                "abc123",
                "primary_spec",
            )

        assert json.loads(meta_path.read_text(encoding="utf-8")) == meta
        update_index.assert_not_called()

    def test_does_not_update_agent_meta_without_commit_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    {"message": "fix: bug"},
                    None,
                    "abc123",
                    None,
                )

            assert json.loads(meta_path.read_text()) == {"name": "agent-alpha"}
            update_index.assert_not_called()
