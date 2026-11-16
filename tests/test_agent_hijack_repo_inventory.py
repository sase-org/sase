"""Shared repository inventory: dict-shaped launcher metadata plus markers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest


def _init_git_repo(root: Path, *, dirty_name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init"],
        ["config", "user.name", "Repo Inventory Test"],
        ["config", "user.email", "repo-inventory@example.invalid"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "base"],
        check=True,
        capture_output=True,
    )
    (root / dirty_name).write_text("dirty\n", encoding="utf-8")
    return root


def _linked_dict(name: str, repo: Path, workspace_num: int = 3) -> dict[str, Any]:
    """Build one entry through the real launcher serializer."""

    from sase._linked_repo_env import LinkedRepoResolution, ResolvedLinkedRepo

    resolution = LinkedRepoResolution(
        repos=(
            ResolvedLinkedRepo(
                name=name,
                env_name=name.upper().replace("-", "_"),
                primary_dir=str(repo),
                workspace_dir=str(repo),
                workspace_num=workspace_num,
            ),
        )
    )
    (entry,) = resolution.to_jsonable()
    assert isinstance(entry, dict)
    return dict(entry)


def _sidecar_dict(name: str, repo: Path, workspace_num: int = 3) -> dict[str, Any]:
    from sase._linked_repo_env import LinkedRepoResolution, ResolvedLinkedRepo

    resolution = LinkedRepoResolution(
        repos=(
            ResolvedLinkedRepo(
                name=name,
                env_name=name.upper().replace("-", "_"),
                primary_dir=str(repo),
                workspace_dir=str(repo),
                workspace_num=workspace_num,
                kind="sidecar",
            ),
        )
    )
    (entry,) = resolution.to_jsonable()
    assert isinstance(entry, dict)
    return dict(entry)


class TestRepoDirFromEntry:
    def test_bare_string(self) -> None:
        from sase.linked_repos import repo_dir_from_entry

        assert repo_dir_from_entry("/repo") == "/repo"
        assert repo_dir_from_entry("  ") is None

    def test_launcher_dict_prefers_workspace_dir(self) -> None:
        from sase.linked_repos import repo_dir_from_entry

        entry = _linked_dict("sase-core", Path("/linked"))
        entry["primary_dir"] = "/primary"
        assert repo_dir_from_entry(entry) == "/linked"

    def test_dict_falls_back_to_primary_dir(self) -> None:
        from sase.linked_repos import repo_dir_from_entry

        assert repo_dir_from_entry({"primary_dir": "/primary"}) == "/primary"

    def test_legacy_static_record_is_skipped(self) -> None:
        from sase.linked_repos import repo_dir_from_entry

        assert (
            repo_dir_from_entry(
                {"workspace_dir": "/linked", "workspace_strategy": "none"}
            )
            is None
        )

    def test_garbage_is_none(self) -> None:
        from sase.linked_repos import repo_dir_from_entry

        assert repo_dir_from_entry(None) is None
        assert repo_dir_from_entry(42) is None
        assert repo_dir_from_entry({"name": "no-dirs"}) is None


class TestRepoDirsFromMeta:
    def test_merges_dict_and_string_lists(self) -> None:
        from sase.linked_repos import repo_dirs_from_meta

        linked = _linked_dict("sase-core", Path("/linked"))
        dirs = repo_dirs_from_meta(
            {
                "linked_repos": [linked],
                "sibling_repos": [linked],
                "sidecar_repos": ["/sidecar"],
                "opened_repos": [],
            }
        )
        assert dirs == ["/linked", "/sidecar"]

    def test_non_mapping_meta_is_empty(self) -> None:
        from sase.linked_repos import repo_dirs_from_meta

        assert repo_dirs_from_meta(None) == []
        assert repo_dirs_from_meta({}) == []


class TestOpenedMarkerDirs:
    def test_reads_real_launcher_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase._linked_repo_markers import record_opened_linked_repo
        from sase.linked_repos import inventory_repo_dirs

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        record_opened_linked_repo("opened-sib", "/sib-ws", reason="test")
        assert inventory_repo_dirs(artifacts_dir=artifacts) == ["/sib-ws"]
        assert inventory_repo_dirs() == []


class TestInventoryRepoDirs:
    def test_combines_meta_and_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase._linked_repo_markers import record_opened_linked_repo
        from sase.linked_repos import inventory_repo_dirs

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        record_opened_linked_repo("opened-sib", "/sib-ws", reason="test")
        linked = _linked_dict("sase-core", Path("/linked"))
        assert inventory_repo_dirs(
            meta={"linked_repos": [linked]}, artifacts_dir=artifacts
        ) == ["/linked", "/sib-ws"]


class TestHijackReleaseSeesAllRepos:
    def test_meta_repo_roots_covers_dicts_and_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase._linked_repo_markers import record_opened_linked_repo
        from sase.agent.hijack._release_snapshot import (
            _meta_repo_roots,
            _release_repo_roots,
        )

        primary = _init_git_repo(tmp_path / "primary", dirty_name="p.txt")
        linked = _init_git_repo(tmp_path / "linked", dirty_name="l.txt")
        sibling = _init_git_repo(tmp_path / "sibling", dirty_name="s.txt")
        sidecar = _init_git_repo(tmp_path / "sidecar", dirty_name="c.txt")

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        record_opened_linked_repo(
            "opened-sib", str(sibling), reason="agent shelled into sibling"
        )
        meta = {
            "linked_repos": [_linked_dict("linked-repo", linked)],
            "sibling_repos": [_linked_dict("linked-repo", linked)],
            "sidecar_repos": [_sidecar_dict("sidecar", sidecar)],
        }
        (artifacts / "agent_meta.json").write_text(
            json.dumps(meta) + "\n", encoding="utf-8"
        )
        record = {
            "hijack_id": "h-inventory",
            "agent_name": "agent--0",
            "artifacts_dir": str(artifacts),
            "workspace_dir": str(primary),
            "workspace_num": 3,
            "snapshots": [],
        }
        assert set(_meta_repo_roots(record)) == {
            str(linked),
            str(sibling),
            str(sidecar),
        }
        assert set(_release_repo_roots(record)) == {
            str(primary),
            str(linked),
            str(sibling),
            str(sidecar),
        }

    def test_ensure_recovery_snapshot_covers_every_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase._linked_repo_markers import record_opened_linked_repo
        from sase.agent.hijack._release_snapshot import ensure_recovery_snapshot

        primary = _init_git_repo(tmp_path / "primary", dirty_name="p.txt")
        linked = _init_git_repo(tmp_path / "linked", dirty_name="l.txt")
        sibling = _init_git_repo(tmp_path / "sibling", dirty_name="s.txt")
        sidecar = _init_git_repo(tmp_path / "sidecar", dirty_name="c.txt")

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        record_opened_linked_repo(
            "opened-sib", str(sibling), reason="agent shelled into sibling"
        )
        meta = {
            "linked_repos": [_linked_dict("linked-repo", linked)],
            "sibling_repos": [_linked_dict("linked-repo", linked)],
            "sidecar_repos": [_sidecar_dict("sidecar", sidecar)],
        }
        (artifacts / "agent_meta.json").write_text(
            json.dumps(meta) + "\n", encoding="utf-8"
        )
        record = {
            "hijack_id": "h-inventory",
            "agent_name": "agent--0",
            "artifacts_dir": str(artifacts),
            "workspace_dir": str(primary),
            "workspace_num": 3,
            "snapshots": [],
        }
        snapshots = ensure_recovery_snapshot(
            record, merge_fn=lambda _hid, _fields: None
        )
        assert {item["repo"] for item in snapshots} == {
            str(primary),
            str(linked),
            str(sibling),
            str(sidecar),
        }
        for item in snapshots:
            assert item["reference"]
            assert item["fingerprint"]

    def test_stop_evidence_roots_cover_dicts_and_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase._linked_repo_markers import record_opened_linked_repo
        from sase.agent.hijack._stop_evidence import _evidence_repo_roots
        from sase.agent.hijack._stop_models import HijackTarget

        primary = _init_git_repo(tmp_path / "primary", dirty_name="p.txt")
        linked = _init_git_repo(tmp_path / "linked", dirty_name="l.txt")
        sibling = _init_git_repo(tmp_path / "sibling", dirty_name="s.txt")

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        record_opened_linked_repo(
            "opened-sib", str(sibling), reason="agent shelled into sibling"
        )
        meta = {"linked_repos": [_linked_dict("linked-repo", linked)]}
        (artifacts / "agent_meta.json").write_text(
            json.dumps(meta) + "\n", encoding="utf-8"
        )
        target = HijackTarget(
            name="agent--0",
            artifacts_dir=str(artifacts),
            project_name="proj",
            project_file="proj.sase.yml",
            artifacts_timestamp="20261106_120000",
            is_home=False,
            pid=None,
            claim_pid=None,
            claim_pinned=False,
            cl_name=None,
            workflow=None,
            workspace_num=3,
            workspace_dir=str(primary),
            status="RUNNING",
            lifecycle_phase=None,
            is_monitor_turn=False,
            is_gate_turn=False,
            gate_state=None,
            agent_session=None,
            capabilities=[],
            model_alias=None,
            model_alias_trail=[],
            model_origin=None,
            provider=None,
            model=None,
            effort=None,
            run_started_at=None,
            done_outcome=None,
            done_recovery=None,
        )
        assert set(_evidence_repo_roots(target)) == {
            str(primary),
            str(linked),
            str(sibling),
        }
