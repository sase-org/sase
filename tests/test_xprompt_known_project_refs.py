"""Tests for xprompt._parsing known-project VCS refs."""

from unittest.mock import patch

from sase.xprompt._parsing import (
    extract_known_project_vcs_ref,
    resolve_known_project_ref,
    strip_known_project_vcs_refs,
)


def test_resolve_known_project_ref_accepts_bare_name() -> None:
    known = {"sase": object(), "sase-core": object()}
    assert resolve_known_project_ref("sase", known) == "sase"
    assert resolve_known_project_ref("sase-core", known) == "sase-core"


def test_resolve_known_project_ref_normalizes_owner_repo_form() -> None:
    """``owner/repo`` keeps a legacy single-project basename fallback."""
    known = {"sase": object()}
    assert resolve_known_project_ref("sase-org/sase", known) == "sase"


def test_resolve_known_project_ref_matches_owner_repo_workspace(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    known = {
        "gh_foo_org__foo": tmp_path / "projects" / "github" / "foo-org" / "foo",
        "gh_bar_org__foo": tmp_path / "projects" / "github" / "bar-org" / "foo",
    }

    assert resolve_known_project_ref("foo-org/foo", known) == "gh_foo_org__foo"
    assert resolve_known_project_ref("bar-org/foo", known) == "gh_bar_org__foo"


def test_resolve_known_project_ref_skips_ambiguous_basename_fallback(
    tmp_path,
) -> None:
    known = {
        "gh_foo_org__foo": tmp_path / "elsewhere" / "foo",
        "gh_bar_org__foo": tmp_path / "another" / "foo",
    }

    assert resolve_known_project_ref("baz-org/foo", known) is None


def test_resolve_known_project_ref_returns_none_for_unknown() -> None:
    known = {"sase": object()}
    assert resolve_known_project_ref("other-org/other", known) is None
    assert resolve_known_project_ref("unknown", known) is None


def test_extract_known_project_vcs_ref_matches_owner_repo_form() -> None:
    """``#gh:sase-org/sase`` is recognized when ``sase`` is a known project."""
    with patch(
        "sase.xprompt.loader.get_known_project_workspaces",
        return_value={"sase": object()},
    ):
        result = extract_known_project_vcs_ref("#gh:sase-org/sase #!sase/nightly_docs")
    assert result == ("gh", "sase-org/sase")


def test_extract_known_project_vcs_ref_matches_duplicate_owner_repo_workspace(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    known = {
        "gh_foo_org__foo": tmp_path / "projects" / "github" / "foo-org" / "foo",
        "gh_bar_org__foo": tmp_path / "projects" / "github" / "bar-org" / "foo",
    }
    with patch(
        "sase.xprompt.loader.get_known_project_workspaces",
        return_value=known,
    ):
        result = extract_known_project_vcs_ref("#gh:bar-org/foo fix")

    assert result == ("gh", "bar-org/foo")


def test_extract_known_project_vcs_ref_ignores_ambiguous_basename_fallback(
    tmp_path,
) -> None:
    known = {
        "gh_foo_org__foo": tmp_path / "elsewhere" / "foo",
        "gh_bar_org__foo": tmp_path / "another" / "foo",
    }
    with patch(
        "sase.xprompt.loader.get_known_project_workspaces",
        return_value=known,
    ):
        result = extract_known_project_vcs_ref("#gh:baz-org/foo fix")

    assert result is None


def test_strip_known_project_vcs_refs_handles_owner_repo_form() -> None:
    """Stripping known-project refs removes ``owner/repo`` forms too."""
    with patch(
        "sase.xprompt.loader.get_known_project_workspaces",
        return_value={"sase": object()},
    ):
        result = strip_known_project_vcs_refs("#gh:sase-org/sase #!sase/nightly_docs")
    assert result == "#!sase/nightly_docs"
