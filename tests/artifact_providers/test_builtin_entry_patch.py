from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_ref_models import ArtifactRef, ArtifactRefContext, ArtifactRefPayload
from sase.artifact_providers.builtin_entry_patch import resolve_patch_entry
from sase.artifact_ref_prompt_context import PromptRefContext, PromptRefProject


def _patch_ref(name: str) -> ArtifactRef:
    return ArtifactRef(
        schema_version=5,
        kind="patch",
        kind_type="patch",
        payload=ArtifactRefPayload(type="patch", name=name),
        fragment=None,
        rendered=f"patch:{name}",
    )


_SPEC_TEMPLATE = """\
NAME: {name}
DESCRIPTION: A test patch.
PARENT:
PR:
STATUS: Draft
STITCHES:
HOOKS:
COMMENTS:
MENTORS:
"""


def _write_spec(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_SPEC_TEMPLATE.format(name=name) for name in names))


def _empty_context() -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(),
        chats_root=Path("/tmp/chats"),
        artifact_index_path=Path("/tmp/idx.jsonl"),
        repositories=(),
        projects=(),
    )


def _project(tmp_path: Path, key: str = "gh_sase-org__sase") -> PromptRefProject:
    return PromptRefProject(
        key=key,
        display_name="sase",
        active_spec=tmp_path / f"{key}.sase",
        archive_spec=tmp_path / f"{key}-archive.sase",
    )


def test_resolves_from_active_spec(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_spec(project.active_spec, ["my-patch"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    outcome = resolve_patch_entry(
        _patch_ref("my-patch"), context=_empty_context(), ref_context=ref_context
    )

    assert outcome.status == "exact"
    assert outcome.locator == "sase/my-patch"
    assert outcome.entry is not None
    assert outcome.entry.properties["project"] == "sase"


def test_active_wins_when_both_active_and_archive_match(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_spec(project.active_spec, ["shared-name"])
    _write_spec(project.archive_spec, ["shared-name"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    outcome = resolve_patch_entry(
        _patch_ref("shared-name"), context=_empty_context(), ref_context=ref_context
    )

    assert outcome.status == "exact"


def test_resolves_from_archive_when_not_in_active(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_spec(project.active_spec, ["something-else"])
    _write_spec(project.archive_spec, ["archived-patch"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    outcome = resolve_patch_entry(
        _patch_ref("archived-patch"), context=_empty_context(), ref_context=ref_context
    )

    assert outcome.status == "exact"
    assert outcome.locator == "sase/archived-patch"


def test_missing_from_project_lists_both_spec_candidates(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_spec(project.active_spec, ["something-else"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    outcome = resolve_patch_entry(
        _patch_ref("nope"), context=_empty_context(), ref_context=ref_context
    )

    assert outcome.status == "missing"
    assert set(outcome.candidates) == {
        str(project.active_spec),
        str(project.archive_spec),
    }


def test_prompt_expansion_uses_centralized_patch_wording(tmp_path: Path) -> None:
    from sase.artifact_refs import process_artifact_references

    project = _project(tmp_path)
    _write_spec(project.active_spec, ["my-patch"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    expanded = process_artifact_references(
        "Look at @patch:my-patch.",
        ref_contexts=(ref_context,),
    )

    assert expanded == "Look at the my-patch Patch in the sase project."


def _no_project_ref_context() -> PromptRefContext:
    return PromptRefContext(
        artifact_context=_empty_context(),
        project=None,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="none",
        vcs_ref=None,
    )


def _fake_patch(name: str, project_display_name: str) -> object:
    from sase.ace.patch.models import Patch

    return Patch(
        name=name,
        description="",
        parent=None,
        pr_url=None,
        pr_origin="unknown",
        status="Draft",
        file_path="/tmp/fake.sase",
        line_number=1,
        project_display_name=project_display_name,
    )


def test_no_project_context_unique_name_resolves_across_all_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda include_states=("enabled",): [_fake_patch("unique-name", "alpha")],
    )

    outcome = resolve_patch_entry(
        _patch_ref("unique-name"),
        context=_empty_context(),
        ref_context=_no_project_ref_context(),
    )

    assert outcome.status == "exact"
    assert outcome.locator == "alpha/unique-name"


def test_no_project_context_duplicate_name_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda include_states=("enabled",): [
            _fake_patch("dup-name", "alpha"),
            _fake_patch("dup-name", "beta"),
        ],
    )

    outcome = resolve_patch_entry(
        _patch_ref("dup-name"),
        context=_empty_context(),
        ref_context=_no_project_ref_context(),
    )

    assert outcome.status == "ambiguous"
    assert set(outcome.candidates) == {"alpha: dup-name", "beta: dup-name"}
    assert outcome.diagnostic is not None
    assert "add a #git/#gh workflow" in outcome.diagnostic


def test_no_project_context_zero_matches_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda include_states=("enabled",): [],
    )

    outcome = resolve_patch_entry(
        _patch_ref("nope"),
        context=_empty_context(),
        ref_context=_no_project_ref_context(),
    )

    assert outcome.status == "missing"


def test_quoted_patch_name_resolves(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_spec(project.active_spec, ["My Patch Name"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    outcome = resolve_patch_entry(
        _patch_ref("My Patch Name"), context=_empty_context(), ref_context=ref_context
    )

    assert outcome.status == "exact"
    assert outcome.entry is not None
    assert outcome.entry.display_label == "My Patch Name"


def test_quoted_patch_name_expands_through_centralized_wording(tmp_path: Path) -> None:
    from sase.artifact_refs import process_artifact_references

    project = _project(tmp_path)
    _write_spec(project.active_spec, ["My Patch Name"])
    ref_context = PromptRefContext(
        artifact_context=_empty_context(),
        project=project,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="vcs_workflow",
        vcs_ref="sase",
    )

    expanded = process_artifact_references(
        '@patch:"My Patch Name"',
        ref_contexts=(ref_context,),
    )

    assert expanded == "the My Patch Name Patch in the sase project"
