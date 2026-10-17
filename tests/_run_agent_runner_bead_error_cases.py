"""Runner bead claim cases for mutation and persistence failures."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from tests._run_agent_runner_bead_helpers import seed_store


def case_claim_helper_wraps_bead_mutation_errors(
    tmp_path: Path,
    failure: str,
) -> None:
    bead_id = seed_store(tmp_path)
    if failure == "missing":
        bead_id = "missing-1"
    else:
        with BeadProject(tmp_path) as project:
            project.close([bead_id])
    store = SddStore(
        storage="in_tree",
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path / "sdd",
    )

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        pytest.raises(RuntimeError, match=rf"{bead_id}.*worker"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )


def case_claim_helper_wraps_store_and_commit_failures(tmp_path: Path) -> None:
    with (
        patch("sase.sdd.store.resolve_sdd_store", side_effect=OSError("no store")),
        pytest.raises(RuntimeError, match="sase-8f.2.*worker.*no store"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-8f.2",
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = seed_store(sdd_dir, beads_dirname="beads")
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", return_value=False),
        pytest.raises(RuntimeError, match=rf"{bead_id}.*worker.*no local SDD commit"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )
