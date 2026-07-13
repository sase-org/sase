"""External repository reference and clone-layout domain coverage."""

from pathlib import Path

import pytest

from sase.external_repos import (
    ExternalRepoRefError,
    canonicalize_external_repo_ref,
    external_repo_clone_parts_from_name,
    external_repo_name_from_clone_parts,
    parse_external_repo_ref,
)
from sase.linked_repos import external_repo_clone_dir


@pytest.mark.parametrize(
    ("value", "canonical", "clone_parts"),
    [
        ("gh:pallets/click", "gh:pallets/click", ("gh", "pallets", "click")),
        ("pallets/click", "gh:pallets/click", ("gh", "pallets", "click")),
        ("GH:Acme/Widget", "gh:Acme/Widget", ("gh", "Acme", "Widget")),
    ],
)
def test_external_provider_refs_canonicalize_and_round_trip(
    value: str,
    canonical: str,
    clone_parts: tuple[str, ...],
) -> None:
    parsed = parse_external_repo_ref(value)

    assert parsed.canonical_name == canonical
    assert parsed.clone_parts == clone_parts
    assert canonicalize_external_repo_ref(value) == canonical
    assert external_repo_name_from_clone_parts(clone_parts) == canonical


def test_external_project_names_round_trip_through_projects_namespace() -> None:
    assert external_repo_clone_parts_from_name("dotdrop") == ("projects", "dotdrop")
    assert external_repo_name_from_clone_parts(("projects", "dotdrop")) == "dotdrop"


@pytest.mark.parametrize(
    "value",
    ["", "gh:", "gh:owner", "gh:owner/repo/extra", "owner", "gh:../repo"],
)
def test_external_provider_ref_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ExternalRepoRefError):
        parse_external_repo_ref(value)


def test_external_repo_clone_dir_uses_workspace_local_layout(tmp_path: Path) -> None:
    assert external_repo_clone_dir(tmp_path, "gh", "pallets", "click") == str(
        (
            tmp_path / "sase" / "repos" / "external" / "gh" / "pallets" / "click"
        ).resolve()
    )

    with pytest.raises(ValueError):
        external_repo_clone_dir(tmp_path, "projects", "..")
