"""Tests for external bug cross-links to epics and Patches."""

from sase.ace.patch.models import Patch
from sase.bead.model import Issue, IssueType
from sase.bug_links import (
    find_external_ref_links,
    normalize_external_ref,
)


def _patch(name: str, bug: str | None, *, project: str = "sase") -> Patch:
    return Patch(
        name=name,
        description="",
        parent=None,
        status="WIP",
        file_path=f"/tmp/sase/projects/{project}/{project}.sase",
        bug=bug,
    )


def _task(
    issue_id: str, *, external_ref: str = "", refs: list[str] | None = None
) -> Issue:
    return Issue(
        id=issue_id,
        title=issue_id,
        issue_type=IssueType.TASK,
        external_ref=external_ref,
        refs=[] if refs is None else refs,
    )


def test_normalize_external_ref_accepts_aliases_urls_and_shorthand(monkeypatch) -> None:
    alias_map = {
        "sase-display": "gh_sase-org__sase",
        "sase": "gh_sase-org__sase",
        "linked-github": "sase-github",
    }
    monkeypatch.setattr(
        "sase.project_aliases.resolve_project_alias_ref",
        lambda ref: alias_map.get(ref, ref),
    )

    assert normalize_external_ref(42, project="sase-display") == (
        "bug:gh_sase-org__sase#42"
    )
    assert normalize_external_ref("#42", project="sase") == ("bug:gh_sase-org__sase#42")
    assert normalize_external_ref("bug:linked-github#42", project="sase") == (
        "bug:sase-github#42"
    )
    assert (
        normalize_external_ref(
            "https://github.com/sase-org/sase/issues/42?view=1",
            project="linked-github",
        )
        == "bug:gh_sase-org__sase#42"
    )


def test_normalize_external_ref_rejects_blank_and_malformed_inputs() -> None:
    assert normalize_external_ref("", project="sase") == ""
    assert normalize_external_ref("42", project="") == ""
    assert normalize_external_ref("bug:sase#", project="sase") == ""
    assert normalize_external_ref("bug:sase org#42", project="sase") == ""
    assert normalize_external_ref("sase#not/a/number", project="sase") == ""


def test_find_external_ref_links_is_project_qualified_and_matches_tasks_refs_patches(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.resolve_project_alias_ref",
        lambda ref: {"display-sase": "sase"}.get(ref, ref),
    )
    task_by_field = _task("sase-1", external_ref="bug:display-sase#42")
    task_by_ref = _task("sase-2", refs=["artifact:a", "bug:sase#42"])
    other_project_task = _task("sase-3", external_ref="bug:sase-github#42")
    unrelated_task = _task("sase-4", refs=["bug:sase#99"])
    matching_patch = _patch("feature", "42", project="sase")
    explicit_project_patch = _patch("other", "bug:sase-github#42", project="sase")

    links = find_external_ref_links(
        "#42",
        [task_by_field, task_by_ref, other_project_task, unrelated_task],
        [matching_patch, explicit_project_patch],
        project="display-sase",
    )

    assert links.external_ref == "bug:sase#42"
    assert links.beads == (task_by_field, task_by_ref)
    assert links.patches == (matching_patch,)
    assert links.prs == links.patches
    assert links.changespecs == links.patches  # legacy compatibility alias
