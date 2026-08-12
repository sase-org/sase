from __future__ import annotations

import pathlib
from unittest import mock

import pytest

import sase.project_display_names as project_display_names
from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefDocumentRoot
from sase.artifact_ref_prompt_context import (
    PromptRefContext,
    empty_prompt_ref_context,
    explicit_prompt_ref_context,
    prompt_ref_context_for_vcs_ref,
    prompt_ref_context_from_launch_identity,
    prompt_ref_contexts_for_prompt,
    refresh_prompt_ref_context,
)
from sase.project_display_names import ProjectDisplaySnapshot, ProjectRefDisplaySnapshot


# Only the "git" VCS workflow is guaranteed registered in this dev sandbox
# (a plain bare_git install); "gh" requires the sase-github plugin, which
# isn't always present. "#git:<ref>" exercises the identical code path.

_FAKE_SNAPSHOT = ProjectRefDisplaySnapshot(
    display_snapshot=ProjectDisplaySnapshot(
        {"gh_sase-org__sase": "sase", "home": "home"}
    ),
    aliases={},
)


@pytest.fixture(autouse=True)
def _fake_project_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate project-key lookups from the real (sandboxed-empty) registry."""

    monkeypatch.setattr(
        project_display_names,
        "load_project_ref_display_snapshot",
        lambda *_a, **_k: _FAKE_SNAPSHOT,
    )
    # Deterministic workspace_num regardless of the agent's own environment.
    for name in (
        "SASE_AGENT_WORKSPACE_NUM",
        "SASE_GIT_WORKSPACE_NUM",
        "SASE_GH_WORKSPACE_NUM",
        "SASE_AGENT_PROJECT_FILE",
        "SASE_ACTIVE_PROJECT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_vcs_ref_builds_context_from_project_registry() -> None:
    context = prompt_ref_context_for_vcs_ref("#git:sase ", is_home_mode=False)

    assert context.origin == "vcs_workflow"
    assert context.vcs_ref == "sase"
    assert context.project_ref == "gh_sase-org__sase"
    assert context.project is not None
    assert context.project.key == "gh_sase-org__sase"


def test_vcs_ref_ignores_peek_ref_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider

    monkeypatch.setattr(workspace_provider, "peek_ref", lambda *_a, **_k: None)
    context_none = prompt_ref_context_for_vcs_ref("#git:sase ", is_home_mode=False)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("peek_ref exploded")

    monkeypatch.setattr(workspace_provider, "peek_ref", boom)
    context_raise = prompt_ref_context_for_vcs_ref("#git:sase ", is_home_mode=False)

    # Both degrade gracefully; project identity still comes from the
    # plugin-independent project registry, not from peek_ref.
    for context in (context_none, context_raise):
        assert context.project is not None
        assert context.project.key == "gh_sase-org__sase"


def test_two_segments_naming_different_projects_get_different_contexts() -> None:
    pairs = prompt_ref_contexts_for_prompt(
        "#git:sase first segment\n---\n#git:home second segment",
        is_home_mode=False,
    )

    assert len(pairs) == 2
    (_span_a, context_a), (_span_b, context_b) = pairs
    assert context_a.vcs_ref == "sase"
    assert context_a.project_ref == "gh_sase-org__sase"
    assert context_a.project is not None
    assert context_a.project.key == "gh_sase-org__sase"
    assert context_b.vcs_ref == "home"
    assert context_b.project_ref == "home"
    # "home" is the system-managed hidden project: no PromptRefProject.
    assert context_b.project is None


def test_segment_without_a_tag_falls_back_to_launch_identity() -> None:
    pairs = prompt_ref_contexts_for_prompt(
        "no tag here\n---\n#git:sase tagged segment",
        is_home_mode=False,
    )

    assert len(pairs) == 2
    (_span_a, context_a), (_span_b, context_b) = pairs
    assert context_a.origin == "launch_identity"
    assert context_a.project_ref == "home"
    assert context_b.origin == "vcs_workflow"


def test_home_mode_and_unresolvable_ref_produce_no_project_context() -> None:
    empty = empty_prompt_ref_context(is_home_mode=True)
    assert empty.project is None
    assert empty.project_ref is None
    assert empty.origin == "none"
    assert empty.workspace_num == 0

    unresolvable = prompt_ref_context_for_vcs_ref(
        "#git:totally-unregistered-project-xyz ", is_home_mode=False
    )
    assert unresolvable.origin == "vcs_workflow"
    assert unresolvable.project_ref == "totally-unregistered-project-xyz"
    assert unresolvable.project is None

    explicit = explicit_prompt_ref_context(_minimal_context(pathlib.Path("/tmp/ref")))
    assert explicit.project_ref is None


def test_launch_identity_records_project_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SASE_AGENT_PROJECT_FILE",
        "/tmp/sase-projects/gh_sase-org__sase/gh_sase-org__sase.sase",
    )

    context = prompt_ref_context_from_launch_identity(is_home_mode=False)

    assert context.origin == "launch_identity"
    assert context.project_ref == "gh_sase-org__sase"


def test_refresh_prompt_ref_context_rebuilds_workspace_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    before = _minimal_context(tmp_path / "before")
    after = _minimal_context(tmp_path / "after")
    workspace = tmp_path / "repo_2"
    calls: list[tuple[pathlib.Path, int, str]] = []

    def rebuild(
        workspace_dir: pathlib.Path,
        workspace_num: int,
        *,
        project: str,
    ) -> ArtifactRefContext:
        calls.append((workspace_dir, workspace_num, project))
        return after

    monkeypatch.setattr(
        "sase.artifact_ref_prompt_context._safe_artifact_ref_context",
        rebuild,
    )
    context = PromptRefContext(
        artifact_context=before,
        project=None,
        primary_repo=None,
        workspace_dir=workspace,
        workspace_num=2,
        origin="vcs_workflow",
        project_ref="gh_sase-org__sase",
    )

    refreshed = refresh_prompt_ref_context(context)

    assert refreshed.artifact_context is after
    assert refreshed.project_ref == "gh_sase-org__sase"
    assert calls == [(workspace, 2, "gh_sase-org__sase")]
    no_workspace = empty_prompt_ref_context(is_home_mode=False)
    assert refresh_prompt_ref_context(no_workspace) is no_workspace


def test_prompt_ref_context_path_never_touches_cwd_or_marker_discovery() -> None:
    import sase.workspace_provider as workspace_provider

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("cwd/marker discovery must not be used")

    with (
        mock.patch.object(pathlib.Path, "cwd", side_effect=boom),
        mock.patch.object(workspace_provider, "find_marker_from_cwd", side_effect=boom),
    ):
        empty_prompt_ref_context(is_home_mode=True)
        prompt_ref_context_for_vcs_ref("#git:sase ", is_home_mode=False)
        prompt_ref_context_from_launch_identity(is_home_mode=False)
        prompt_ref_contexts_for_prompt("hi\n---\n#git:sase there", is_home_mode=False)
        prompt_ref_context_for_vcs_ref(
            "#git:totally-unregistered-xyz ", is_home_mode=False
        )


def _minimal_context(root: pathlib.Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("research", root),),
        chats_root=root / "chats",
        artifact_index_path=root / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
    )
