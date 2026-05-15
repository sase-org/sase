"""Runtime integration tests for managed workspace roots (Phase 5 of sase-3p).

Phase 4 reserved workspace numbers ``1-9`` and shifted claim allocation to
``#10+``.  Phase 5 routes runtime workspace resolution through
``WorkspaceStore`` so callers can opt into managed roots (``xdg-state`` /
absolute) without rewriting call sites.

These tests pin the runtime behavior that Phase 5 promises:

- ``adjacent`` parity stays byte-for-byte compatible with the legacy
  ``primary_<num>`` layout;
- ``workspace.root: xdg-state`` materializes managed checkouts under the
  configured state root;
- legacy ``workspace_num == 1`` callers still receive the primary checkout
  in every policy;
- the spawn boundary scrubs stale ``SASE_*_WORKSPACE_DIR`` env vars from a
  parent agent before applying the resolved checkout path;
- file-panel / notification path lookup resolves the same checkout for an
  ``(project, workspace_num)`` pair across processes (restart-safe).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_spawn import (
    _overwrite_project_dir_env,
    _remove_inherited_workspace_preallocation_env,
)
from sase.running_field._workspace import (
    _normalize_legacy_primary,
    get_workspace_directory,
    get_workspace_directory_for_num,
)
from sase.workspace_provider.marker import find_marker_from_cwd
from sase.workspace_provider.registry import (
    load_or_init_registry,
    registry_path,
)
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import ensure_workspace_checkout


# ── compatibility: legacy #1 maps to primary ─────────────────────────


class TestLegacyPrimaryMapping:
    def test_normalize_translates_one_to_zero(self) -> None:
        assert _normalize_legacy_primary(1) == 0
        assert _normalize_legacy_primary(0) == 0
        assert _normalize_legacy_primary(10) == 10

    def test_get_workspace_directory_for_num_treats_zero_and_one_as_primary(
        self,
    ) -> None:
        with patch(
            "sase.running_field._workspace.get_workspace_directory",
            return_value="/path/to/primary",
        ):
            for num in (0, 1):
                ws_dir, suffix = get_workspace_directory_for_num(num, "proj")
                assert ws_dir == "/path/to/primary"
                assert suffix is None

    def test_get_workspace_directory_for_num_managed_returns_suffix(self) -> None:
        with patch(
            "sase.running_field._workspace.get_workspace_directory",
            return_value="/managed/proj_10/",
        ):
            ws_dir, suffix = get_workspace_directory_for_num(10, "proj", clean=False)
            assert ws_dir == "/managed/proj_10/"
            assert suffix == "proj_10"


# ── runtime falls back via WORKSPACE_DIR for unknown plugin ──────────


class TestRuntimeFallback:
    def test_legacy_num_one_returns_primary_under_xdg_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with xdg-state config, legacy ``#1`` still resolves primary.

        Generic fallback path (no plugin claims the project): the compat
        wrapper must map ``1 -> 0`` so the runtime returns the user's
        primary checkout instead of a managed ``proj_1/`` clone the store
        would otherwise compute.
        """
        primary = tmp_path / "checkout"
        primary.mkdir()
        project_file = tmp_path / "myproj.sase"
        project_file.write_text(
            f"WORKSPACE_DIR: {primary}\nNAME: my\n", encoding="utf-8"
        )

        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)

        with (
            patch(
                "sase.workflows.utils.get_project_file_path",
                return_value=str(project_file),
            ),
            patch(
                "sase.workspace_provider.detect_workflow_type",
                side_effect=ValueError("No workspace plugin detected"),
            ),
        ):
            assert get_workspace_directory("myproj", 1) == str(primary)


# ── managed-root materialization records registry + marker ──────────


class TestManagedRootMaterialization:
    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_xdg_state_materializes_under_managed_root(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)

        primary = tmp_path / "repo"
        primary.mkdir()
        config = {"workspace": {"root": "xdg-state", "project_key": "k"}}

        result = ensure_workspace_checkout(str(primary), 10, config=config)
        expected_root = tmp_path / "state" / "sase" / "workspaces" / "k"
        assert result.startswith(str(expected_root))
        assert result.endswith("repo_10/")

        # Registry tracks the managed workspace so a sibling process /
        # `sase workspace list` can later find it without a second clone.
        assert os.path.exists(registry_path(str(expected_root)))
        store = WorkspaceStore(str(primary), config=config, env=os.environ)
        registry = load_or_init_registry(store)
        assert "10" in registry.workspaces
        assert registry.workspaces["10"].checkout_dir == result

    def test_adjacent_does_not_create_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adjacent layout keeps its legacy behavior — no registry written."""
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
        primary = tmp_path / "repo"
        primary.mkdir()
        sibling = tmp_path / "repo_2"
        sibling.mkdir()
        # Pretend the sibling already exists as a healthy git clone so
        # ensure_git_clone_at short-circuits without subprocess.
        with patch(
            "sase.workspace_provider.utils.subprocess.run",
            return_value=MagicMock(returncode=0, stdout=""),
        ):
            result = ensure_workspace_checkout(
                str(primary) + "/",
                2,
                config={"workspace": {"root": "adjacent"}},
                env={},
            )
        assert result == str(sibling) + "/"
        # Parent of primary (adjacent root) should NOT have a registry.json.
        assert not (tmp_path / "registry.json").exists()


# ── file-panel / notification path lookup after restart ──────────────


class TestRestartSafeResolution:
    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_same_inputs_resolve_same_checkout_across_processes(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A second resolution returns the same path — TUI / file-panel
        can rebuild ``(project, workspace_num)`` -> ``checkout_dir`` after
        a process restart without consulting any extra state.
        """
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
        primary = tmp_path / "repo"
        primary.mkdir()
        config = {"workspace": {"root": "xdg-state", "project_key": "k"}}

        first = ensure_workspace_checkout(str(primary), 10, config=config)
        second = ensure_workspace_checkout(str(primary), 10, config=config)
        assert first == second

    def test_marker_records_project_context_for_managed_checkout(
        self, tmp_path: Path
    ) -> None:
        """A real on-disk managed checkout writes a marker that
        ``find_marker_from_cwd`` can read back — Phase 6's CWD inference
        relies on this contract.
        """
        primary = tmp_path / "repo"
        primary.mkdir()
        managed_root = tmp_path / "managed"
        config = {"workspace": {"root": str(managed_root), "project_key": "k"}}

        def fake_run(argv: list[str], **_: object) -> MagicMock:
            # Materialize the target dir on ``git clone`` so the marker
            # write sees an on-disk checkout.
            if len(argv) >= 4 and argv[0] == "git" and argv[1] == "clone":
                target = argv[3].rstrip("/")
                os.makedirs(target, exist_ok=True)
            return MagicMock(returncode=0, stdout="")

        with patch(
            "sase.workspace_provider.utils.subprocess.run", side_effect=fake_run
        ):
            checkout = ensure_workspace_checkout(
                str(primary), 10, config=config, env={}
            )

        assert os.path.isdir(checkout.rstrip("/"))
        found = find_marker_from_cwd(checkout)
        assert found is not None
        _, marker = found
        assert marker.workspace_num == 10
        assert marker.project_key == "k"
        assert marker.primary_workspace_dir == str(primary)


# ── spawn boundary scrubs stale SASE_*_WORKSPACE_DIR ─────────────────


class TestSpawnEnvScrub:
    def test_stale_workspace_dir_env_is_replaced(self) -> None:
        """Inherited ``SASE_*_WORKSPACE_DIR`` from a parent launch must not
        leak into the child; spawn rewrites it to the resolved checkout.
        """
        env = {
            "SASE_GIT_PRE_ALLOCATED": "1",
            "SASE_GIT_WORKSPACE_NUM": "10",
            "SASE_GIT_WORKSPACE_DIR": "/managed/old-parent_10/",
            "SASE_CD_WORKSPACE_DIR": "/managed/old-cd/",
            "SASE_ACTIVE_PROJECT_DIR": "/managed/old-parent_10/",
            "UNRELATED": "keep",
        }
        _remove_inherited_workspace_preallocation_env(env)
        assert "SASE_GIT_WORKSPACE_DIR" not in env
        assert "SASE_GIT_WORKSPACE_NUM" not in env
        assert "SASE_GIT_PRE_ALLOCATED" not in env
        assert "SASE_CD_WORKSPACE_DIR" not in env
        # Active project dir is rewritten separately so the spawn helper
        # always plants the freshly resolved checkout.
        _overwrite_project_dir_env(env, "/managed/new-child_42/")
        assert env["SASE_ACTIVE_PROJECT_DIR"] == "/managed/new-child_42/"
        assert env["UNRELATED"] == "keep"
