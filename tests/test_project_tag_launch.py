"""Backend step-8 launch tests for project tags (D3/D4/D7).

Covers what the parent plan's backend step 8 requires: ``launch_query``
ordering (validation and expansion run only after the local-dispatch
decision, and before force-reuse, typed dispatch, MRU, and spawn), remote
dispatch forwarding ``+tags`` verbatim, MRU recording the canonical
``#<workflow>:<key>`` form, the post-fan-out unit guard rejecting two
workspace targets, ambiguous tags, provider-less tags, and disabled tags
before any spawn, ``%{+sase | +bob-cli}`` alt fan-out and swarm expansion, tag
errors in the LaunchApproval preview, and refusal of a ``#git:Sase`` init
with a ``+sase`` hint.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_accents import PROJECT_ACCENTS
from sase.project_tags import ProjectTagCatalog, ProjectTagError, build_targets
from sase.workspace_provider import reset_workflow_metadata_caches
from sase.workspace_provider._hookspec import WorkflowMetadata
from tests._workspace_provider_helpers import (
    _restore_xprompt_vcs_caches_on_teardown,
    git_metadata,
)


def _record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    display_name: str | None = None,
    state: str = "enabled",
    system_managed: bool = False,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=True,
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
        is_project=True,
    )


def _catalog_for(
    records: list[ProjectRecordWire],
    extra_workflows: dict[str, str] | None = None,
) -> ProjectTagCatalog:
    workflow_types = {"sase": "gh", "bob": "git", "home": "git", "beta": "git"}
    if extra_workflows:
        workflow_types.update(extra_workflows)
    display_names = {"gh": "GitHub", "git": "Git (bare)"}

    def _detect(project_file: str) -> str:
        for record in records:
            if record.project_file == project_file:
                prefix = workflow_types.get(record.project_name)
                if prefix is None:
                    raise ValueError(f"no plugin for {project_file}")
                return prefix
        raise ValueError(f"unknown project file {project_file}")

    return ProjectTagCatalog(
        targets=tuple(
            build_targets(
                records,
                detect_workflow_type=_detect,
                get_display_name=display_names.get,
            )
        ),
        accent_palette=tuple(PROJECT_ACCENTS),
    )


@pytest.fixture()
def tag_catalog() -> ProjectTagCatalog:
    """Fake catalog: sase, bob, disabled beta, and system home."""
    return _catalog_for(
        [
            _record("sase"),
            _record("bob", aliases=["bobby"]),
            _record("beta", state="disabled"),
            _record("home", system_managed=True),
        ]
    )


def _patch_tag_catalog(monkeypatch: pytest.MonkeyPatch, catalog: ProjectTagCatalog):
    monkeypatch.setattr(
        "sase.project_tags.catalog.load_project_tag_catalog",
        lambda *args, **kwargs: catalog,
    )


def _git_and_gh_metadata() -> tuple[WorkflowMetadata, ...]:
    return git_metadata() + (
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
        ),
    )


def _patch_git_and_gh_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _git_and_gh_metadata)
    monkeypatch.setattr(
        workspace_provider, "get_all_workflow_metadata", _git_and_gh_metadata
    )
    reset_workflow_metadata_caches()
    _restore_xprompt_vcs_caches_on_teardown(monkeypatch)


def _launch_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _base_launch_patches() -> ExitStack:
    """Patch the launch-query seams that never touch the network or disk."""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "sase.agent.prompt_inputs.missing_required_input_names",
            return_value=[],
        )
    )
    stack.enter_context(
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=(),
        )
    )
    return stack


# --- launch_query ordering -------------------------------------------------


def test_launch_query_runs_tags_after_dispatch_before_reuse_spawn_and_mru(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    """Validation/expansion sit between dispatch and force-reuse/spawn/MRU."""
    from sase.main.query_handler._launch import launch_query
    import sase.project_tags as project_tags_pkg

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    _patch_tag_catalog(monkeypatch, tag_catalog)
    monkeypatch.setattr(
        "sase.ops.cli.load_request",
        lambda _name: SimpleNamespace(
            payload={"prompt": "+sase do work", "allow_force_reuse": True}
        ),
    )
    calls: list[str] = []
    real_validate = project_tags_pkg.validate_project_tags_for_launch
    real_expand = project_tags_pkg.expand_project_tags

    def _validate(query: str) -> None:
        calls.append("validate")
        real_validate(query)

    def _expand(query: str) -> str:
        calls.append("expand")
        return real_expand(query)

    monkeypatch.setattr("sase.project_tags.validate_project_tags_for_launch", _validate)
    monkeypatch.setattr("sase.project_tags.expand_project_tags", _expand)

    def _dispatch(query: str, **kwargs: Any) -> None:
        calls.append("dispatch")
        return None

    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", _dispatch)

    def _plan_force_reuse(query: str) -> None:
        calls.append("force_reuse")
        assert query == "#gh:sase do work"
        return None

    monkeypatch.setattr(
        "sase.agent.force_reuse_launch.plan_force_reuse_launch", _plan_force_reuse
    )

    def _spawn(query: str, **kwargs: Any) -> list[AgentLaunchResult]:
        calls.append("spawn")
        assert query == "#gh:sase do work"
        return [_launch_result()]

    monkeypatch.setattr(
        "sase.main.query_handler._launch.launch_agents_from_cwd", _spawn
    )

    def _record_mru(prefix: str) -> None:
        calls.append("mru")
        assert prefix == "#gh:sase"

    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage", _record_mru
    )
    monkeypatch.setattr(
        "sase.ops.commands.run.emit_run_launch_result", lambda **kwargs: None
    )

    with _base_launch_patches():
        with pytest.raises(SystemExit) as exc_info:
            launch_query("+sase do work")

    assert exc_info.value.code == 0
    assert calls == ["dispatch", "validate", "expand", "force_reuse", "spawn", "mru"]


def test_launch_query_tag_failure_blocks_spawn(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    """An unknown tag fails the launch before any spawn or MRU write."""
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    _patch_tag_catalog(monkeypatch, tag_catalog)
    spawn = MagicMock(return_value=[_launch_result()])
    monkeypatch.setattr("sase.main.query_handler._launch.launch_agents_from_cwd", spawn)
    record_mru = MagicMock()
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage", record_mru
    )
    failed: list[str] = []
    monkeypatch.setattr(
        "sase.history.prompt.record_failed_launch_prompt", failed.append
    )
    monkeypatch.setattr(
        "sase.ops.commands.run.emit_run_launch_result", lambda **kwargs: None
    )

    with _base_launch_patches():
        with pytest.raises(SystemExit) as exc_info:
            launch_query("+ssae do work")

    assert exc_info.value.code == 1
    spawn.assert_not_called()
    record_mru.assert_not_called()
    assert failed == ["+ssae do work"]


def test_launch_query_remote_dispatch_forwards_tags_verbatim(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    """Remote dispatch sees the raw ``+tag`` prompt; no local validation."""
    from sase.dispatch.launch import _RemoteDispatchLaunchResult
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    _patch_tag_catalog(monkeypatch, tag_catalog)
    seen: list[str] = []

    def _dispatch(query: str, **kwargs: Any) -> _RemoteDispatchLaunchResult:
        seen.append(query)
        return _RemoteDispatchLaunchResult(
            target="worker",
            prompt=query,
            message="dispatched",
            payload={},
        )

    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", _dispatch)
    validate = MagicMock()
    monkeypatch.setattr("sase.project_tags.validate_project_tags_for_launch", validate)
    emitted: dict[str, Any] = {}
    monkeypatch.setattr(
        "sase.ops.commands.run.emit_run_launch_result",
        lambda **kwargs: emitted.update(kwargs),
    )

    with _base_launch_patches():
        with pytest.raises(SystemExit) as exc_info:
            launch_query("+sase do work")

    assert exc_info.value.code == 0
    assert seen == ["+sase do work"]
    validate.assert_not_called()
    assert emitted.get("success") is True


def test_launch_query_expands_home_on_empty_projects_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``+home`` launches on a fresh machine with no ProjectSpec files."""
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    spawned: list[str] = []

    def _spawn(query: str, **kwargs: Any) -> list[AgentLaunchResult]:
        spawned.append(query)
        return [_launch_result()]

    monkeypatch.setattr(
        "sase.main.query_handler._launch.launch_agents_from_cwd", _spawn
    )
    monkeypatch.setattr(
        "sase.ops.commands.run.emit_run_launch_result", lambda **kwargs: None
    )

    with _base_launch_patches():
        with patch(
            "sase.project_tags.catalog.sase_projects_dir", return_value=tmp_path
        ):
            with pytest.raises(SystemExit) as exc_info:
                launch_query("+home do work")

    assert exc_info.value.code == 0
    assert spawned == ["#git:home do work"]


# --- post-fan-out unit guard -------------------------------------------------


def _guard(
    segments: list[str], submitted: str = "submitted"
) -> tuple[MagicMock, BaseException | None]:
    """Run the unit guard, returning the failed-prompt mock and the error."""
    from sase.agent.launch_cwd_guards import guard_project_tags_for_launch_units

    record_failed = MagicMock()
    try:
        guard_project_tags_for_launch_units(
            submitted,
            expanded_segments=segments,
            record_failed_launch_prompt=record_failed,
        )
    except ProjectTagError as exc:
        return record_failed, exc
    return record_failed, None


def test_unit_guard_skips_segments_without_tags(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    _patch_tag_catalog(monkeypatch, tag_catalog)
    validate = MagicMock()
    monkeypatch.setattr("sase.project_tags.validate_project_tags_for_launch", validate)

    record_failed, error = _guard(["do work", "plain #gh:sase ref"])

    assert error is None
    validate.assert_not_called()
    record_failed.assert_not_called()


def test_unit_guard_rejects_two_workspace_targets(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    _patch_tag_catalog(monkeypatch, tag_catalog)

    record_failed, error = _guard(["+sase +bob do x"], submitted="+sase +bob do x")

    assert isinstance(error, ProjectTagError)
    assert "Only one workspace target" in str(error)
    record_failed.assert_called_once_with("+sase +bob do x")


def test_unit_guard_rejects_disabled_tag(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    _patch_tag_catalog(monkeypatch, tag_catalog)

    _, error = _guard(["+beta do x"])

    assert isinstance(error, ProjectTagError)
    assert "disabled" in str(error)


def test_unit_guard_rejects_unknown_anchored_tag(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    _patch_tag_catalog(monkeypatch, tag_catalog)

    _, error = _guard(["+ssae do x"])

    assert isinstance(error, ProjectTagError)
    assert "Unknown project tag +ssae" in str(error)


def test_unit_guard_rejects_ambiguous_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog_for(
        [
            _record("sase"),
            _record("gh_x__sase", display_name="sase"),
        ]
    )
    _patch_tag_catalog(monkeypatch, catalog)

    _, error = _guard(["+sase do x"])

    assert isinstance(error, ProjectTagError)
    assert "ambiguous" in str(error)


def test_unit_guard_rejects_provider_less_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog_for([_record("sase"), _record("loner")])
    _patch_tag_catalog(monkeypatch, catalog)

    _, error = _guard(["+loner do x"])

    assert isinstance(error, ProjectTagError)
    assert "no VCS provider" in str(error)


def test_unit_guard_accepts_alt_branches_as_separate_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog_for(
        [_record("sase"), _record("bob-cli")],
        extra_workflows={"bob-cli": "git"},
    )
    _patch_tag_catalog(monkeypatch, catalog)

    record_failed, error = _guard(["%{+sase | +bob-cli} audit the README"])

    assert error is None
    record_failed.assert_not_called()


def test_unit_guard_rejects_crowded_alt_branch(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    _patch_tag_catalog(monkeypatch, tag_catalog)

    _, error = _guard(["%{+sase +bob | +sase} audit the README"])

    assert isinstance(error, ProjectTagError)
    assert "Only one workspace target" in str(error)


def test_unit_guard_covers_swarm_expanded_segments(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    """Each post-swarm segment enforces the one-target rule on its own."""
    from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
    from tests._xprompt_swarm_helpers import patch_catalog, xp

    _patch_tag_catalog(monkeypatch, tag_catalog)
    swarm = {"crew": xp("crew", "+sase do A\n---\n+bob do B")}
    with patch_catalog(swarm):
        segments = [
            record.prompt for record in expand_xprompt_swarms_with_metadata(["#crew"])
        ]
    assert segments == ["+sase do A", "+bob do B"]

    from sase.agent.launch_cwd_guards import guard_project_tags_for_launch_units

    record_failed = MagicMock()
    guard_project_tags_for_launch_units(
        "#crew",
        expanded_segments=segments,
        record_failed_launch_prompt=record_failed,
    )
    record_failed.assert_not_called()

    bad_swarm = {"crew": xp("crew", "+sase +bob do A\n---\n+bob do B")}
    with patch_catalog(bad_swarm):
        bad_segments = [
            record.prompt for record in expand_xprompt_swarms_with_metadata(["#crew"])
        ]
    with pytest.raises(ProjectTagError, match="Only one workspace target"):
        guard_project_tags_for_launch_units(
            "#crew",
            expanded_segments=bad_segments,
            record_failed_launch_prompt=record_failed,
        )


# --- LaunchApproval preview --------------------------------------------------


def test_preview_plan_surfaces_tag_errors(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    from sase.agent.launch_request_planning import build_preview_plan
    from sase.agent.launch_request_types import LaunchRequestError

    _patch_tag_catalog(monkeypatch, tag_catalog)

    with pytest.raises(LaunchRequestError, match=r"Unknown project tag \+ssae"):
        build_preview_plan("+ssae do work")


def test_preview_plan_accepts_resolved_tags(
    monkeypatch: pytest.MonkeyPatch, tag_catalog: ProjectTagCatalog
) -> None:
    from sase.agent.launch_request_planning import build_preview_plan

    _patch_tag_catalog(monkeypatch, tag_catalog)

    preview, _plan = build_preview_plan("+sase do work")

    assert "+sase" not in preview
    assert "#gh:sase" in preview


# --- #git:Sase init refusal ----------------------------------------------------


def test_git_sase_case_variant_init_is_refused_with_tag_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``#git:Sase`` never auto-inits a shadowing project; it hints ``+sase``."""
    import subprocess

    from sase.workspace_provider.plugins.bare_git_ref import resolve_git_ref
    from sase.workspace_provider.utils import ProjectProviderMismatchError

    checkout = tmp_path / "github" / "sase"
    checkout.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/sase.git"],
        cwd=checkout,
        check=True,
    )
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "gh_org__sase"
    project_dir.mkdir(parents=True)
    (project_dir / "gh_org__sase.sase").write_text(
        f"WORKSPACE_DIR: {checkout}/\nPROJECT_NAME: sase\nNAME: c\n",
        encoding="utf-8",
    )
    tag_catalog = _catalog_for(
        [_record("gh_org__sase", display_name="sase")],
        extra_workflows={"gh_org__sase": "gh"},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.plugins.bare_git_ref.sase_projects_dir",
        lambda: projects_root,
    )
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    _patch_tag_catalog(monkeypatch, tag_catalog)
    monkeypatch.setattr(
        "sase.workspace_provider.plugins.bare_git_ref.find_all_patches",
        lambda: [],
    )
    mock_init = MagicMock()
    monkeypatch.setattr(
        "sase.workspace_provider.plugins.bare_git_init.init_bare_git_project",
        mock_init,
    )

    with pytest.raises(ProjectProviderMismatchError, match=r"Use \+sase instead"):
        resolve_git_ref("Sase")

    mock_init.assert_not_called()
    assert not (projects_root / "Sase").exists()
