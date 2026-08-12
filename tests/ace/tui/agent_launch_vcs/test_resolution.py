"""VCS ref resolution paths for agent launches."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata
from tests._workspace_provider_helpers import git_metadata
from tests.ace.tui._agent_launch_helpers import (
    _LaunchBodyApp,
    _fake_context,
    _run_launch_body_with_common_patches,
)


def _gh_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
        ),
    )


def test_run_agent_launch_body_uses_canonical_ref_for_first_use_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    primary_workspace = tmp_path / "widgets"
    allocated_workspace = tmp_path / "widgets_101"
    project_file = str(tmp_path / ".sase" / "projects" / "proj_key" / "proj_key.sase")

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _gh_metadata)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.resolve_ref",
                return_value=ResolvedRef(
                    project_file=project_file,
                    project_name="proj_key",
                    primary_workspace_dir=str(primary_workspace),
                    checkout_target="main",
                    canonical_ref="proj_key",
                ),
            )
        )
        stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(allocated_workspace), None),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )

        app._run_agent_launch_body("#gh:alice/widgets implement")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["project_name"] == "proj_key"
    assert launch["project_file"] == project_file
    assert launch["cl_name"] == "proj_key"
    assert launch["history_sort_key"] == "proj_key"
    assert launch["vcs_ref"] == ("gh", "proj_key")

    saved = app._last_custom_agent_selection
    assert saved is not None
    assert saved.item_type == "project"
    assert saved.project_name == "proj_key"
    assert saved.cl_name is None
    assert saved.display_name == "[P] proj_key"
    save.assert_called_once_with(saved)
    record_mru.assert_called_once_with("#gh:proj_key")


def test_resolve_ref_from_prompt_propagates_provider_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-mismatched ``#git:`` ref must surface, not vanish as None.

    Regression test for bare_git_project_clobber: swallowing this alongside
    ordinary unresolved refs would silently drop the launch's VCS
    resolution instead of telling the user why it failed.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )
    from sase.workspace_provider.utils import ProjectProviderMismatchError

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", git_metadata)
    monkeypatch.setattr(
        "sase.project_aliases.canonicalize_project_aliases_in_prompt",
        lambda prompt: prompt,
    )

    def _raise_mismatch(ref: str, workflow_type: str):  # type: ignore[no-untyped-def]
        raise ProjectProviderMismatchError(
            "'sase' is not a bare-git project — #git:sase would convert it into one."
        )

    with patch("sase.workspace_provider.resolve_ref", side_effect=_raise_mismatch):
        with pytest.raises(ProjectProviderMismatchError):
            resolve_ref_from_prompt("#git:sase do work", "git")


def test_run_agent_launch_body_no_ref_defaults_home_mode_to_git_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.sase")

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", git_metadata)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.resolve_ref",
                return_value=ResolvedRef(
                    project_file=project_file,
                    project_name="home",
                    primary_workspace_dir=str(primary_workspace),
                    checkout_target="main",
                ),
            )
        )
        first_ws = stack.enter_context(
            patch("sase.running_field.get_first_available_axe_workspace")
        )
        provider_ws_dir = stack.enter_context(
            patch("sase.workspace_provider.get_workspace_directory")
        )
        claim_ws = stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        ws_dir = stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(allocated_workspace), None),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
        )
        stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        app._run_agent_launch_body("do work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["prompt"] == "#git:home do work"
    assert launch["project_name"] == "home"
    assert launch["project_file"] == project_file
    assert launch["workspace_dir"] == str(allocated_workspace)
    assert launch["workspace_num"] == 101
    assert launch["is_home_mode"] is False
    assert launch["update_target"] == ""
    assert launch["vcs_ref"] == ("git", "home")
    assert launch["retry_transfer_from_pid"] == os.getpid()
    first_ws.assert_not_called()
    provider_ws_dir.assert_not_called()
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "home")


def test_record_resolved_default_git_home_ref_is_not_persisted_as_mru(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare prompt normalized to the implicit ``#git:home`` default must not
    leave a cyclable VCS MRU entry behind on launch."""
    from tests.conftest import redirect_sase_home
    from sase.ace.tui.actions.agent_workflow._launch_history import (
        record_resolved_vcs_xprompt_usage,
    )
    from sase.history.vcs_xprompt_mru import _load_vcs_xprompt_mru

    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    mru_file = sase_home / "vcs_xprompt_mru.json"

    with patch(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        return_value=True,
    ):
        record_resolved_vcs_xprompt_usage(("git", "home"), "home")

    assert not mru_file.exists()
    assert _load_vcs_xprompt_mru() == []


def test_record_launched_vcs_xprompt_usage_records_resolved_canonical_ref() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_history import (
        record_launched_vcs_xprompt_usage,
    )

    def resolve_vcs_from_prompt(
        prompt: str,
        workflow_type: str,
        *,
        skip_workspace: bool = False,
    ) -> tuple[str, str, str, int, str] | None:
        assert prompt == "#gh:alice/widgets implement"
        assert workflow_type == "gh"
        assert skip_workspace is True
        return ("/tmp/proj/proj.sase", "proj_key", "/tmp/proj", 0, "proj_key")

    with (
        patch(
            "sase.ace.tui.modals.project_discovery.is_launchable_project",
            return_value=True,
        ),
        patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage") as record_mru,
    ):
        record_launched_vcs_xprompt_usage(
            ("gh", "alice/widgets"),
            prompt="#gh:alice/widgets implement",
            resolve_vcs_from_prompt=resolve_vcs_from_prompt,
        )

    record_mru.assert_called_once_with("#gh:proj_key")


def test_save_replayable_vcs_selection_skips_default_git_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The implicit ``#git:home`` default must not be saved as a Ctrl+Space
    replay target, even though git is a workspace (non-home-mode) workflow.

    This covers both a bare prompt normalized to ``#git:home`` and an explicit
    ``#git:home`` prompt, which both resolve to ``("git", "home")``.
    """
    from tests.conftest import redirect_sase_home
    from sase.ace.tui.actions.agent_workflow._launch_history import (
        save_replayable_vcs_selection,
    )

    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    selection_file = sase_home / "last_agent_selection.json"

    class _ReplayApp:
        _last_custom_agent_selection = "sentinel"

    app = _ReplayApp()
    ctx = _fake_context()
    ctx.project_name = "home"

    save_replayable_vcs_selection(app, ctx, ("git", "home"))  # type: ignore[arg-type]

    assert not selection_file.exists()
    assert app._last_custom_agent_selection == "sentinel"


def test_run_agent_launch_body_known_project_ref_without_project_provider_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    monkeypatch.setenv("HOME", str(tmp_path))
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(tmp_path / ".sase" / "projects" / "sase" / "sase.sase")

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_ref_patterns", return_value={})
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value=set())
        )
        stack.enter_context(
            patch(
                "sase.xprompt.loader.get_known_project_workspaces",
                return_value={"sase": workspace},
            )
        )
        first_ws = stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        ws_dir = stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(allocated_workspace), None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
        )
        app._run_agent_launch_body("#gh:sase #!sase/maintenance")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["prompt"] == "#gh:sase #!sase/maintenance"
    assert launch["project_name"] == "sase"
    assert launch["project_file"] == project_file
    assert launch["workspace_dir"] == str(allocated_workspace)
    assert launch["workspace_num"] == 101
    assert launch["is_home_mode"] is False
    assert launch["update_target"] == VCS_DEFAULT_REVISION
    assert launch["vcs_ref"] == ("gh", "sase")
    assert launch["retry_transfer_from_pid"] == os.getpid()
    first_ws.assert_called_once()
    assert first_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "sase")


def test_run_agent_launch_body_forwards_workspace_claim_transfer_pid() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(app, "do normal work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["retry_transfer_from_pid"] == os.getpid()
