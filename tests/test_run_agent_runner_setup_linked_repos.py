import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_setup import (
    prepare_linked_repo_workspaces_if_needed,
    refresh_linked_repos_for_workspace,
)
from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    LinkedRepoResolution,
    SIBLING_REPOS_JSON_ENV,
    _ResolvedLinkedRepo,
    resolve_linked_repos_for_project,
)


def _resolution(
    *,
    name: str = "core",
    primary_dir: str = "/repos/sase-core",
    workspace_dir: str = "/repos/sase-core_7",
    workspace_num: int = 7,
    auto_clone: bool = True,
    kind: str = "linked",
    remote_url: str | None = None,
) -> LinkedRepoResolution:
    return LinkedRepoResolution(
        repos=(
            _ResolvedLinkedRepo(
                name=name,
                env_name=name.upper().replace("-", "_"),
                primary_dir=primary_dir,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                auto_clone=auto_clone,
                kind=kind,
                remote_url=remote_url,
            ),
        )
    )


def test_refresh_linked_repos_for_workspace_updates_env_meta_without_prompt_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "sase"
    sibling = tmp_path / "sase-core"
    workspace = tmp_path / "sase_7"
    primary.mkdir()
    sibling.mkdir()
    workspace.mkdir()
    project_file = tmp_path / "project.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\nNAME: main\n")
    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(workspace),
        workspace_num=7,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )
    monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "stale")
    meta = {"pid": 123, "workspace_dir": "/placeholder"}

    with (
        patch(
            "sase.linked_repos.resolve_linked_repos_for_project",
            return_value=resolution,
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
        ),
    ):
        refreshed = refresh_linked_repos_for_workspace(
            project_file=str(project_file),
            workspace_dir=str(workspace),
            workspace_num=7,
            artifacts_dir=str(tmp_path),
            agent_meta=meta,
        )

    assert refreshed == resolution
    assert meta["workspace_dir"] == str(workspace)
    # Canonical key plus the deprecated alias both land in agent_meta.
    assert meta["linked_repos"] == resolution.to_jsonable()
    assert meta["sibling_repos"] == resolution.to_jsonable()
    written = json.loads((tmp_path / "agent_meta.json").read_text(encoding="utf-8"))
    assert written["linked_repos"][0]["workspace_dir"] == str(
        workspace / "sase" / "repos" / "linked" / "core"
    )
    assert written["sibling_repos"][0]["workspace_dir"] == str(
        workspace / "sase" / "repos" / "linked" / "core"
    )
    assert json.loads(os.environ[LINKED_REPOS_JSON_ENV])[0]["name"] == "core"
    assert json.loads(os.environ[SIBLING_REPOS_JSON_ENV])[0]["name"] == "core"


def test_refresh_linked_repos_for_workspace_preserves_meta_on_empty_resolution(
    tmp_path: Path,
) -> None:
    meta = {
        "pid": 123,
        "workspace_dir": "/placeholder",
        "linked_repos": [{"name": "core", "workspace_dir": "/tmp/sase-core_7"}],
        "sibling_repos": [{"name": "core", "workspace_dir": "/tmp/sase-core_7"}],
    }

    with (
        patch(
            "sase.linked_repos.resolve_linked_repos_for_project",
            return_value=LinkedRepoResolution(repos=()),
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
        ),
    ):
        refresh_linked_repos_for_workspace(
            project_file=str(tmp_path / "project.sase"),
            workspace_dir=str(tmp_path / "sase_7"),
            workspace_num=7,
            artifacts_dir=str(tmp_path),
            agent_meta=meta,
        )

    assert meta["workspace_dir"] == str(tmp_path / "sase_7")
    assert meta["linked_repos"] == [
        {"name": "core", "workspace_dir": "/tmp/sase-core_7"}
    ]
    assert meta["sibling_repos"] == [
        {"name": "core", "workspace_dir": "/tmp/sase-core_7"}
    ]
    written = json.loads((tmp_path / "agent_meta.json").read_text(encoding="utf-8"))
    assert written["linked_repos"] == meta["linked_repos"]
    assert written["sibling_repos"] == meta["sibling_repos"]


def test_empty_fresh_linked_repo_resolution_does_not_prepare_stale_meta(
    tmp_path: Path,
) -> None:
    meta = {
        "pid": 123,
        "workspace_dir": "/placeholder",
        "linked_repos": [
            {
                "name": "core",
                "primary_dir": "/tmp/sase-core",
                "workspace_dir": "/tmp/stale-sase-core_7",
                "workspace_strategy": "suffix",
            }
        ],
        "sibling_repos": [
            {
                "name": "core",
                "primary_dir": "/tmp/sase-core",
                "workspace_dir": "/tmp/stale-sase-core_7",
                "workspace_strategy": "suffix",
            }
        ],
    }
    empty_resolution = LinkedRepoResolution(repos=())

    with (
        patch(
            "sase.linked_repos.resolve_linked_repos_for_project",
            return_value=empty_resolution,
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
    ):
        refreshed = refresh_linked_repos_for_workspace(
            project_file=str(tmp_path / "project.sase"),
            workspace_dir=str(tmp_path / "sase_7"),
            workspace_num=7,
            artifacts_dir=str(tmp_path),
            agent_meta=meta,
        )
        prepare_linked_repo_workspaces_if_needed(
            resolution=refreshed,
            cl_name="feature",
        )

    assert refreshed == empty_resolution
    assert meta["linked_repos"][0]["workspace_dir"] == "/tmp/stale-sase-core_7"
    prepare.assert_not_called()


def test_prepare_linked_repo_workspaces_uses_default_revision_sentinel() -> None:
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    with (
        patch(
            "sase.linked_repos.materialize_linked_repo_workspace",
            return_value="/repos/sase-core_7",
        ),
        patch(
            "sase.axe.run_agent_runner_setup.prepare_workspace",
            side_effect=lambda *args, **kwargs: calls.append((args, kwargs)) or True,
        ),
    ):
        prepare_linked_repo_workspaces_if_needed(
            resolution=_resolution(),
            cl_name="feature",
        )

    assert calls == [
        (
            ("/repos/sase-core_7", "feature", VCS_DEFAULT_REVISION),
            {"backup_suffix": "linked-core"},
        )
    ]


def test_prepare_linked_repo_workspaces_reuses_fresh_launch_sidecar(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "workspace" / "sase" / "repos" / "plans"
    (plans / ".git").mkdir(parents=True)
    resolution = _resolution(
        name="plans",
        primary_dir=str(tmp_path / "primary" / "sase" / "repos" / "plans"),
        workspace_dir=str(plans),
        kind="sidecar",
        remote_url="git@example.test:owner/project--plans.git",
    )

    with (
        patch(
            "sase.linked_repos.materialize_linked_repo_workspace",
            side_effect=AssertionError("fresh plans sidecar was cloned again"),
        ),
        patch(
            "sase.axe.run_agent_runner_setup.prepare_workspace",
            side_effect=AssertionError("fresh plans sidecar was prepared again"),
        ),
        patch("sase.linked_repos.apply_linked_repo_env") as apply_env,
    ):
        prepare_linked_repo_workspaces_if_needed(
            resolution=resolution,
            cl_name="feature",
            fresh_sidecar_paths=frozenset({str(plans.resolve())}),
        )

    apply_env.assert_called_once_with(os.environ, resolution)


def test_prepare_linked_repo_workspaces_skips_prep_for_new_sidecar(
    tmp_path: Path,
) -> None:
    research = tmp_path / "workspace" / "sase" / "repos" / "research"
    resolution = _resolution(
        name="research",
        primary_dir=str(tmp_path / "primary" / "sase" / "repos" / "research"),
        workspace_dir=str(research),
        kind="sidecar",
        remote_url="git@example.test:owner/project--research.git",
    )

    def materialize(**_kwargs: object) -> str:
        (research / ".git").mkdir(parents=True)
        return str(research)

    with (
        patch(
            "sase.linked_repos.materialize_linked_repo_workspace",
            side_effect=materialize,
        ) as materialize_sidecar,
        patch(
            "sase.axe.run_agent_runner_setup.prepare_workspace",
            side_effect=AssertionError("new research sidecar was prepared again"),
        ),
        patch("sase.linked_repos.apply_linked_repo_env"),
    ):
        prepare_linked_repo_workspaces_if_needed(
            resolution=resolution,
            cl_name="feature",
        )

    materialize_sidecar.assert_called_once()


def test_prepare_linked_repo_workspaces_prepares_retained_sidecar(
    tmp_path: Path,
) -> None:
    research = tmp_path / "workspace" / "sase" / "repos" / "research"
    (research / ".git").mkdir(parents=True)
    resolution = _resolution(
        name="research",
        primary_dir=str(tmp_path / "primary" / "sase" / "repos" / "research"),
        workspace_dir=str(research),
        kind="sidecar",
        remote_url="git@example.test:owner/project--research.git",
    )

    with (
        patch(
            "sase.linked_repos.materialize_linked_repo_workspace",
            return_value=str(research),
        ),
        patch(
            "sase.axe.run_agent_runner_setup.prepare_workspace",
            return_value=True,
        ) as prepare,
        patch("sase.linked_repos.apply_linked_repo_env"),
    ):
        prepare_linked_repo_workspaces_if_needed(
            resolution=resolution,
            cl_name="feature",
        )

    prepare.assert_called_once()


def test_prepare_linked_repo_workspaces_skips_lazy_entries() -> None:
    with (
        patch("sase.linked_repos.materialize_linked_repo_workspace") as materialize,
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
    ):
        prepare_linked_repo_workspaces_if_needed(
            resolution=_resolution(auto_clone=False),
            cl_name="feature",
        )

    materialize.assert_not_called()
    prepare.assert_not_called()


def test_prepare_linked_repo_workspaces_skips_primary_paths() -> None:
    resolution = LinkedRepoResolution(
        repos=(
            _ResolvedLinkedRepo(
                name="static-core",
                env_name="STATIC_CORE",
                primary_dir="/repos/sase-core",
                workspace_dir="/repos/sase-core",
                workspace_num=7,
            ),
            _ResolvedLinkedRepo(
                name="first-workspace",
                env_name="FIRST_WORKSPACE",
                primary_dir="/repos/plugin",
                workspace_dir="/repos/plugin",
                workspace_num=1,
            ),
        )
    )

    with patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare:
        prepare_linked_repo_workspaces_if_needed(
            resolution=resolution,
            cl_name="feature",
        )

    prepare.assert_not_called()


def test_prepare_linked_repo_workspaces_failure_names_workspace() -> None:
    with (
        patch(
            "sase.linked_repos.materialize_linked_repo_workspace",
            return_value="/repos/sase-core_7",
        ),
        patch("sase.axe.run_agent_runner_setup.prepare_workspace", return_value=False),
        pytest.raises(RuntimeError) as exc_info,
    ):
        prepare_linked_repo_workspaces_if_needed(
            resolution=_resolution(),
            cl_name="feature",
        )

    assert "Failed to prepare linked repo 'core' workspace: /repos/sase-core_7" in str(
        exc_info.value
    )
