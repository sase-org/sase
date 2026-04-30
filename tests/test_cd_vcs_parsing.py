"""Parsing tests for the built-in cd workspace workflow."""

from __future__ import annotations

from sase.workspace_provider._hookspec import WorkflowMetadata


def _metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="cd",
            ref_pattern=r"(?:^|(?<=\s))#cd(?:[_:]([^\s()]+)|\(([^)]*)\))",
            display_name="Directory",
            pre_allocated_env_prefix="SASE_CD",
        ),
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
        ),
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git",
            pre_allocated_env_prefix="SASE_GIT",
        ),
        WorkflowMetadata(
            workflow_type="hg",
            ref_pattern=r"(?:^|(?<=\s))#hg(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Google",
            pre_allocated_env_prefix="SASE_HG",
        ),
    )


def _patch_metadata(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sase.workspace_provider._registry as registry
    import sase.xprompt._parsing as parsing

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _metadata)
    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_REPLACE_PATTERN = None
    parsing._VCS_UNDERSCORE_NORMALIZER = None


def test_get_vcs_tag_pattern_matches_cd_paths(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_metadata(monkeypatch)

    from sase.workspace_provider import get_vcs_tag_pattern

    pattern = get_vcs_tag_pattern()
    assert pattern.match("#cd:~ do it") is not None
    assert pattern.match("#cd:/tmp/work do it") is not None
    assert pattern.match("#cd:../sibling do it") is not None
    assert pattern.match("#cd(.) do it") is not None
    assert pattern.match("#git:repo do it") is not None
    assert pattern.match("#gh:sase do it") is not None
    assert pattern.match("#hg:change do it") is not None


def test_extract_vcs_workflow_tag_handles_cd(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_metadata(monkeypatch)

    from sase.xprompt._parsing import extract_vcs_workflow_tag

    assert extract_vcs_workflow_tag("#cd:~/src Fix it") == "#cd:~/src "
    assert extract_vcs_workflow_tag("%n:a #cd:/tmp/work Fix it") == "#cd:/tmp/work "
    assert extract_vcs_workflow_tag("#git:repo Fix it") == "#git:repo "


def test_strip_all_vcs_refs_handles_cd(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_metadata(monkeypatch)

    from sase.ace.tui.actions.agent_workflow._ref_resolution import strip_all_vcs_refs

    assert strip_all_vcs_refs("#cd:~/src Fix it") == "Fix it"
    assert strip_all_vcs_refs("#cd(.) Fix it") == "Fix it"
    assert strip_all_vcs_refs("#gh:sase Fix it") == "Fix it"


def test_replace_vcs_workflow_tags_handles_cd(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_metadata(monkeypatch)

    from sase.xprompt._parsing import replace_vcs_workflow_tags

    prompt = "#cd:/tmp/a Fix A\n---\n#git:repo Fix B"
    assert (
        replace_vcs_workflow_tags(prompt, "#cd:/tmp/b")
        == "#cd:/tmp/b Fix A\n---\n#cd:/tmp/b Fix B"
    )
