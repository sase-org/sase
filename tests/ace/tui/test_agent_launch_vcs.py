"""Tests that ``_run_agent_launch_body`` resolves VCS refs correctly.

Covers ``#cd`` directory targeting, default git-home fallback when no
ref is present, known-project ref resolution without a provider, and
the launchable/non-launchable branching for saving the resolved ref as
the "last custom agent selection".

The non-blocking event-loop guarantees live in
``test_agent_launch_non_blocking.py``; the dispatch routing paths live
in ``test_agent_launch_dispatch.py``.
"""

from __future__ import annotations

import os
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef
from tests.ace.tui._agent_launch_helpers import (
    _FakeApp,
    _LaunchBodyApp,
    _cd_git_metadata,
    _cd_metadata,
    _fake_context,
    _run_launch_body_with_common_patches,
)


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers.

    Sibling tests patch workflow metadata to a reduced set (e.g. ``#cd`` only);
    if the global VCS tag pattern is (re)built during that window it sticks,
    dropping ``#git`` and breaking the tag-aware launch toast/guard. Reset it
    before and after each test so ``extract_vcs_workflow_tag`` reflects the
    actually-registered providers.
    """
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None


def test_run_agent_launch_body_cd_keeps_home_mode_and_uses_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_metadata)

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
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        app._run_agent_launch_body(f"#cd:{tmp_path} do work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["workspace_dir"] == str(tmp_path.resolve())
    assert launch["workspace_num"] == 0
    assert launch["is_home_mode"] is True
    assert launch["update_target"] == ""
    assert launch["vcs_ref"] == ("cd", str(tmp_path))


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

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_git_metadata)

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


def test_run_agent_launch_body_known_project_ref_without_provider_targets_project(
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
        app._run_agent_launch_body("#gh:sase #!sase/fix_just")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["prompt"] == "#gh:sase #!sase/fix_just"
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


def test_run_agent_launch_body_does_not_save_non_launchable_resolved_vcs_ref() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    previous_selection = object()
    app._last_custom_agent_selection = previous_selection  # type: ignore[assignment]
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.sase",
            "project",
            "/tmp/project_1",
            1,
            "project",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=False,
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
                return_value=("/tmp/project_101", None),
            )
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
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

        app._run_agent_launch_body("#gh:project fix stale replay")

    assert len(app.launched) == 1
    save.assert_not_called()
    record_mru.assert_not_called()
    assert app._last_custom_agent_selection is previous_selection


def test_run_agent_launch_body_saves_launchable_resolved_vcs_ref() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/sase/sase.sase",
            "sase",
            "/tmp/sase_1",
            1,
            "fix_branch",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
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
                return_value=("/tmp/sase_101", None),
            )
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
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

        app._run_agent_launch_body("#gh:fix_branch implement")

    assert len(app.launched) == 1
    saved = app._last_custom_agent_selection
    assert saved is not None
    assert saved.item_type == "cl"
    assert saved.project_name == "sase"
    assert saved.cl_name == "fix_branch"
    save.assert_called_once_with(saved)
    record_mru.assert_called_once_with("#gh:fix_branch")


def test_run_agent_launch_body_records_home_multi_prompt_vcs_ref_mru() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/sase/sase.sase",
            "sase",
            "/tmp/sase",
            0,
            "fix_branch",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.agent.launch_projects.activate_known_project_vcs_refs_for_launch_prompt",
                return_value=(),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
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

        app._run_agent_launch_body("#gh:fix_branch first\n---\nsecond")

    assert app.launched == []
    multi_prompt_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_prompt_calls) == 1
    _, args = multi_prompt_calls[0]
    assert args[2] == ("gh", "fix_branch")
    record_mru.assert_called_once_with("#gh:fix_branch")


def test_run_agent_launch_body_skips_home_multi_prompt_non_launchable_vcs_ref_mru() -> (
    None
):
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.sase",
            "project",
            "/tmp/project",
            0,
            "project",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.agent.launch_projects.activate_known_project_vcs_refs_for_launch_prompt",
                return_value=(),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=False,
            )
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
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

        app._run_agent_launch_body("#gh:project first\n---\nsecond")

    multi_prompt_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_prompt_calls) == 1
    record_mru.assert_not_called()


def test_run_agent_launch_body_records_non_home_detected_vcs_ref_mru() -> None:
    app = _LaunchBodyApp()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/sase/sase.sase",
            "sase",
            "/tmp/sase",
            0,
            "fix_branch",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
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
                return_value=("/tmp/test_101", None),
            )
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
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

        app._run_agent_launch_body("#gh:fix_branch implement")

    assert len(app.launched) == 1
    assert app.launched[0]["vcs_ref"] == ("gh", "fix_branch")
    record_mru.assert_called_once_with("#gh:fix_branch")


def test_run_agent_launch_body_skips_non_home_non_launchable_vcs_ref_mru() -> None:
    app = _LaunchBodyApp()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.sase",
            "project",
            "/tmp/project",
            0,
            "project",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=False,
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
                return_value=("/tmp/test_101", None),
            )
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
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

        app._run_agent_launch_body("#gh:project implement")

    assert len(app.launched) == 1
    record_mru.assert_not_called()


def test_finish_agent_launch_toast_uses_cycled_vcs_ref_not_baked_name() -> None:
    """Defect A: the launch toast names the submitted ref, not the baked ctx.

    When the bar is opened for one ref (``ctx.display_name`` baked from the
    last selection) and ``<ctrl+p>`` cycles to another before submitting, the
    immediate "Launching agent for ..." toast must reflect the cycled-to ref.
    """
    app = _FakeApp()
    app._prompt_context = _fake_context()
    app._prompt_context.display_name = "sase"  # baked from a prior selection

    app._finish_agent_launch("#git:foo do work")

    launching = [m for m, _ in app.notifications if m.startswith("Launching agent")]
    assert launching == ["Launching agent for foo..."]


def test_finish_agent_launch_toast_falls_back_to_display_name_without_tag() -> None:
    """Defect A: a plain prompt (no VCS tag) still labels off the baked name."""
    app = _FakeApp()
    app._prompt_context = _fake_context()
    app._prompt_context.display_name = "sase"

    app._finish_agent_launch("do work without a tag")

    launching = [m for m, _ in app.notifications if m.startswith("Launching agent")]
    assert launching == ["Launching agent for sase..."]


def test_run_agent_launch_body_aborts_unresolvable_home_mode_vcs_tag() -> None:
    """Defect B: a cycled-to VCS tag that resolves to nothing aborts loudly.

    It must NOT fall through to a home-mode launch under the baked identity
    (wrong workspace) nor silently skip the replay/MRU updates.
    """
    app = _LaunchBodyApp()
    ctx = _fake_context()  # is_home_mode=True
    ctx.display_name = "sase"
    ctx.project_name = "sase"
    app._prompt_context = ctx
    previous_selection = object()
    app._last_custom_agent_selection = previous_selection  # type: ignore[assignment]

    # Resolution fails for the cycled ref.
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: None
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"git"})
        )
        stack.enter_context(
            patch(
                "sase.agent.launcher.resolve_known_project_vcs_launch_ref",
                return_value=None,
            )
        )
        record_failed = stack.enter_context(
            patch("sase.history.prompt.record_failed_launch_prompt")
        )
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )

        outcome = app._run_agent_launch_body("#git:stale do work")

    # Nothing launched; context cleared; replay selection + MRU untouched.
    assert app.launched == []
    assert app._prompt_context is None
    assert app._last_custom_agent_selection is previous_selection
    save.assert_not_called()
    record_mru.assert_not_called()

    record_failed.assert_called_once_with("#git:stale do work")

    # The error outcome names the cycled ref, not the baked project.
    assert outcome.message == "Cannot resolve #git:stale; not launching"
    assert outcome.severity == "error"


def test_run_agent_launch_body_records_short_unresolvable_home_mode_vcs_tag() -> None:
    """A single-token unresolved VCS tag is saved as failed cancelled history."""
    app = _LaunchBodyApp()
    ctx = _fake_context()  # is_home_mode=True
    ctx.display_name = "sase"
    ctx.project_name = "sase"
    app._prompt_context = ctx
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: None
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"git"})
        )
        stack.enter_context(
            patch(
                "sase.agent.launcher.resolve_known_project_vcs_launch_ref",
                return_value=None,
            )
        )
        record_failed = stack.enter_context(
            patch("sase.history.prompt.record_failed_launch_prompt")
        )

        outcome = app._run_agent_launch_body("#git:stale")

    assert app.launched == []
    record_failed.assert_called_once_with("#git:stale")
    assert outcome.message == "Cannot resolve #git:stale; not launching"
    assert outcome.severity == "error"
