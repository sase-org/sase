from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase import artifact_refs
from sase.artifact_refs import ArtifactRefDocumentOwner, ArtifactRefRepository

from .helpers import context as make_context


def test_resolves_an_unqualified_source_path_in_its_owning_repository(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    checkout = context.repositories[0].checkout_paths[0]
    source = checkout / "src" / "thing.py"
    source.parent.mkdir(parents=True)
    source.write_text("thing", encoding="utf-8")

    resolution = artifact_refs.resolve_document_source_target(
        "src/thing.py",
        context=context,
    )

    assert resolution.status == "exact"
    assert resolution.repository == "sase"
    assert resolution.resolved_path == source
    assert resolution.failure_category is None
    assert not resolution.retryable


def test_two_linked_repositories_with_the_same_path_are_ambiguous(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    other_checkout = tmp_path / "other-repo"
    for checkout in (context.repositories[0].checkout_paths[0], other_checkout):
        source = checkout / "src" / "shared.py"
        source.parent.mkdir(parents=True)
        source.write_text("shared", encoding="utf-8")
    context = replace(
        context,
        repositories=(
            *context.repositories,
            ArtifactRefRepository("other", checkout_paths=(other_checkout,)),
        ),
    )

    resolution = artifact_refs.resolve_document_source_target(
        "src/shared.py",
        context=context,
    )

    assert resolution.status == "ambiguous"
    assert resolution.failure_category == "ambiguous"
    assert not resolution.retryable
    assert {candidate.repository for candidate in resolution.candidates} == {
        "sase",
        "other",
    }


def test_absent_checkout_is_a_retryable_missing_checkout(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    resolution = artifact_refs.resolve_document_source_target(
        "src/thing.py",
        context=context,
    )

    assert resolution.status == "missing_checkout"
    assert resolution.failure_category == "missing_checkout"
    assert resolution.retryable


def test_explicit_owner_repository_excludes_unrelated_repositories(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    other_checkout = tmp_path / "other-repo"
    source = other_checkout / "src" / "shared.py"
    source.parent.mkdir(parents=True)
    source.write_text("shared", encoding="utf-8")
    context = replace(
        context,
        repositories=(
            *context.repositories,
            ArtifactRefRepository("other", checkout_paths=(other_checkout,)),
        ),
    )

    resolution = artifact_refs.resolve_document_source_target(
        "src/shared.py",
        owner=ArtifactRefDocumentOwner(repository="sase"),
        context=context,
    )

    assert resolution.status == "missing_checkout"
    assert all(candidate.repository != "other" for candidate in resolution.candidates)
