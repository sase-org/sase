import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import _write_done_marker_and_update_index
from sase.axe.run_agent_exec_markers import (
    clear_workflow_pdf_activity,
    update_workflow_pdf_status,
)
from sase.axe.run_agent_exec_plan_artifacts import write_plan_path_artifact
from sase.axe.run_agent_runner_setup import (
    capture_sdd_base_sha,
    enter_agent_workspace,
    prepare_linked_repo_workspaces_if_needed,
    prepare_workspace_if_needed,
    preprocess_prompt_xprompts,
    refresh_linked_repos_for_workspace,
    setup_artifacts_directory,
    write_submitted_xprompt_artifact,
)
from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    LinkedRepoResolution,
    SIBLING_REPOS_JSON_ENV,
    _ResolvedLinkedRepo,
    resolve_linked_repos_for_project,
)
from sase.sdd.store import SddStore


def _resolution(
    *,
    name: str = "core",
    primary_dir: str = "/repos/sase-core",
    workspace_dir: str = "/repos/sase-core_7",
    workspace_num: int = 7,
    auto_clone: bool = True,
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
            ),
        )
    )


def test_enter_agent_workspace_installs_runtime_ignore_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.chdir(tmp_path)
    with (
        patch("sase.sdd.env.set_sdd_dir_env"),
        patch(
            "sase.workspace_provider.git_exclude.ensure_git_info_exclude_entry",
            side_effect=lambda workspace, pattern: calls.append((workspace, pattern)),
        ),
    ):
        enter_agent_workspace(str(tmp_path), 10)

    assert calls == [
        (str(tmp_path), ".sase/"),
        (str(tmp_path), "/sase/repos/"),
    ]


def test_write_submitted_xprompt_artifact_preserves_exact_prompt(
    tmp_path: Path,
) -> None:
    prompt = "  #alias\n\nbody\n  "

    path = write_submitted_xprompt_artifact(str(tmp_path), prompt)

    assert Path(path).name == "submitted_xprompt.md"
    assert Path(path).read_text(encoding="utf-8") == prompt


def test_submitted_xprompt_artifact_does_not_change_raw_xprompt_behavior(
    tmp_path: Path,
) -> None:
    submitted = "#alias original"
    resolved = "#real original"

    write_submitted_xprompt_artifact(str(tmp_path), submitted)
    with (
        patch("sase.xprompt.resolve_xprompt_aliases", return_value=resolved),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references", return_value="expanded"
        ),
    ):
        preprocess_prompt_xprompts(submitted, str(tmp_path))

    assert (tmp_path / "submitted_xprompt.md").read_text(encoding="utf-8") == submitted
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == resolved


def test_preprocess_prompt_xprompts_captures_launch_boundary_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner writes xprompts.json (e.g. #plan) before expansion erases it."""
    import sase.xprompt.used_xprompts as used_xprompts
    from sase.xprompt.models import XPrompt

    monkeypatch.setattr(
        used_xprompts,
        "get_all_xprompts",
        lambda: {"plan": XPrompt(name="plan", content="plan body")},
    )
    monkeypatch.setattr(used_xprompts, "get_all_workflows", lambda: {})
    monkeypatch.setattr(used_xprompts, "resolve_xprompt_aliases", lambda prompt: prompt)
    monkeypatch.setattr(
        used_xprompts, "normalize_vcs_underscore_refs", lambda prompt: prompt
    )

    with (
        patch(
            "sase.xprompt.resolve_xprompt_aliases", side_effect=lambda prompt: prompt
        ),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=lambda prompt: "expanded",
        ),
    ):
        expanded, _, _ = preprocess_prompt_xprompts("Make a #plan now", str(tmp_path))

    # Expansion still runs and returns the expanded text.
    assert expanded == "expanded"
    # The pre-expansion #plan reference is captured into the shared file that
    # the root (non-step) agent row reads.
    data = json.loads((tmp_path / "xprompts.json").read_text(encoding="utf-8"))
    assert [(r["name"], r["kind"]) for r in data] == [("plan", "part")]
    # raw_xprompt.md and the captured metadata derive from the same text.
    assert (tmp_path / "raw_xprompt.md").read_text(
        encoding="utf-8"
    ) == "Make a #plan now"


def test_runner_setup_artifacts_keep_project_alias_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )
    prompt = "#gh:bob-cli do it"

    write_submitted_xprompt_artifact(str(tmp_path), prompt)
    with (
        patch("sase.config.load_merged_config", return_value={"xprompt_aliases": {}}),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=lambda text: text,
        ),
    ):
        preprocess_prompt_xprompts(prompt, str(tmp_path))

    submitted = (tmp_path / "submitted_xprompt.md").read_text(encoding="utf-8")
    raw = (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8")
    assert submitted == "#gh:bob-cli do it"
    assert raw == "#gh:bob-cli do it"
    assert "#gh:bob " not in submitted
    assert "#gh:bob " not in raw


def test_setup_artifacts_directory_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with (
        patch(
            "sase.axe.run_agent_runner_setup.create_artifacts_directory",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.axe.run_agent_runner_setup.convert_timestamp_to_artifacts_format",
            return_value="20260520220000",
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        setup_artifacts_directory(
            timestamp="260520_220000",
            project_file="/tmp/project/project.gp",
            cl_name="feature",
            is_home_mode=False,
        )

    assert calls == [str(tmp_path)]
    assert (tmp_path / "workflow_state.json").is_file()


def test_prepare_workspace_if_needed_invokes_sdd_clone_after_prepare() -> None:
    calls: list[tuple[str, object]] = []

    def prepare_workspace(*args: object, **kwargs: object) -> bool:
        calls.append(("prepare", args))
        return True

    def ensure_workspace_sdd_clone(workspace_dir: str, workspace_num: int) -> None:
        calls.append(("clone", (workspace_dir, workspace_num)))

    def clear_linked_repo_clones(workspace_dir: str) -> None:
        calls.append(("clear", (workspace_dir,)))

    with (
        patch(
            "sase.axe.run_agent_runner_setup.prepare_workspace",
            side_effect=prepare_workspace,
        ),
        patch(
            "sase.sdd.store.ensure_workspace_sdd_clone",
            side_effect=ensure_workspace_sdd_clone,
        ),
        patch(
            "sase.linked_repos.clear_linked_repo_clones",
            side_effect=clear_linked_repo_clones,
        ),
    ):
        prepare_workspace_if_needed(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_name="sase",
            is_home_mode=False,
            retry_handoff=None,
        )

    assert calls == [
        ("prepare", ("/tmp/workspace", "feature", "main")),
        ("clear", ("/tmp/workspace",)),
        ("clone", ("/tmp/workspace", 7)),
    ]


def test_prepare_workspace_if_needed_skips_sdd_clone_for_home_mode() -> None:
    with (
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
        patch("sase.sdd.store.ensure_workspace_sdd_clone") as ensure_clone,
        patch("sase.linked_repos.clear_linked_repo_clones") as clear_linked,
    ):
        prepare_workspace_if_needed(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_name="sase",
            is_home_mode=True,
            retry_handoff=None,
        )

    prepare.assert_not_called()
    clear_linked.assert_not_called()
    ensure_clone.assert_not_called()


def test_prepare_workspace_if_needed_skips_sdd_clone_for_retry_handoff() -> None:
    with (
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
        patch("sase.sdd.store.ensure_workspace_sdd_clone") as ensure_clone,
        patch("sase.linked_repos.clear_linked_repo_clones") as clear_linked,
    ):
        prepare_workspace_if_needed(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_name="sase",
            is_home_mode=False,
            retry_handoff=object(),
        )

    prepare.assert_not_called()
    clear_linked.assert_not_called()
    ensure_clone.assert_not_called()


def test_capture_sdd_base_sha_for_companion_repo(tmp_path: Path) -> None:
    sdd_repo = tmp_path / "workspace" / ".sase" / "sdd"
    sdd_repo.mkdir(parents=True)
    _git(sdd_repo, "git", "init")
    _git(sdd_repo, "git", "config", "user.email", "test@example.com")
    _git(sdd_repo, "git", "config", "user.name", "Test User")
    (sdd_repo / "README.md").write_text("# SDD\n")
    _git(sdd_repo, "git", "add", ".")
    _git(sdd_repo, "git", "commit", "-m", "base")
    expected = _git(sdd_repo, "git", "rev-parse", "HEAD")

    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore("separate_repo", sdd_repo, sdd_repo),
    ):
        assert capture_sdd_base_sha(str(tmp_path / "workspace"), 1) == expected


def test_capture_sdd_base_sha_skips_in_tree_and_missing_clone(
    tmp_path: Path,
) -> None:
    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore("in_tree", tmp_path / "sdd", tmp_path),
    ):
        assert capture_sdd_base_sha(str(tmp_path), 1) is None

    missing = tmp_path / ".sase" / "sdd"
    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore("local", missing, missing),
    ):
        assert capture_sdd_base_sha(str(tmp_path), 1) is None


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


def test_done_marker_write_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        done_path = _write_done_marker_and_update_index(
            str(tmp_path),
            {"outcome": "completed"},
        )

    assert Path(done_path) == tmp_path / "done.json"
    assert calls == [str(tmp_path)]
    assert '"outcome": "completed"' in Path(done_path).read_text(encoding="utf-8")


def test_plan_path_artifact_write_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_plan_artifacts."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        write_plan_path_artifact(str(tmp_path), "/tmp/plan.md")

    assert calls == [str(tmp_path)]
    assert (tmp_path / "plan_path.json").read_text(encoding="utf-8") == (
        '{"plan_path": "/tmp/plan.md"}'
    )


def test_workflow_pdf_status_updates_artifact_index(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text('{"status": "running"}', encoding="utf-8")
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        update_workflow_pdf_status(
            str(tmp_path),
            {"stage": "source_started", "index": 1, "total": 2, "source_path": "a.md"},
        )
        clear_workflow_pdf_activity(str(tmp_path))

    assert calls == [str(tmp_path), str(tmp_path)]
    data = state_path.read_text(encoding="utf-8")
    assert '"pdf_status"' in data
    assert '"activity"' not in data


def _git(cwd: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()
