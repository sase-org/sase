from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefPayload,
    ArtifactRefRepository,
)
from sase.artifact_ref_operations import artifact_ref_expansion_validate
from sase.artifact_providers.builtin_entry_stitch import (
    _STITCH_EXPANSION_FORMAT,
    resolve_stitch_entry,
)

from .helpers import init_git_repo, ref_context_for, stitch_context


def _stitch_ref(sha: str | None, repo: str | None = None) -> ArtifactRef:
    rendered = "stitch:" + (f"{repo}@{sha}" if repo else sha or "")
    return ArtifactRef(
        schema_version=5,
        kind="stitch",
        kind_type="stitch",
        payload=ArtifactRefPayload(type="stitch", sha=sha, repo=repo),
        fragment=None,
        rendered=rendered,
    )


def test_short_form_resolves_against_primary_repo(tmp_path: Path) -> None:
    full_sha = init_git_repo(tmp_path / "repo")
    context = stitch_context(tmp_path / "repo")
    ref_context = ref_context_for(context, primary_repo="sase")

    outcome = resolve_stitch_entry(
        _stitch_ref(full_sha[:12]), context=context, ref_context=ref_context
    )

    assert outcome.status == "exact"
    assert outcome.entry is not None
    assert outcome.entry.captured_revision == full_sha
    assert outcome.entry.stable_id == f"stitch:sase@{full_sha}"
    assert outcome.locator == f"sase@{full_sha}"
    assert outcome.resolved_path == tmp_path / "repo"
    assert outcome.canonical_reference == f"stitch:sase@{full_sha}"
    assert (
        outcome.prompt_text
        == f"stitch {full_sha} in sase (checkout: {tmp_path / 'repo'})"
    )


def test_qualified_form_resolves_a_non_primary_repo(tmp_path: Path) -> None:
    full_sha = init_git_repo(tmp_path / "other")
    other_repo = ArtifactRefRepository(
        name="other", checkout_paths=(tmp_path / "other",), kind="linked"
    )
    context = stitch_context(tmp_path / "repo", repo_name="sase")
    from dataclasses import replace

    context = replace(context, repositories=(*context.repositories, other_repo))
    ref_context = ref_context_for(context, primary_repo="sase")

    outcome = resolve_stitch_entry(
        _stitch_ref(full_sha[:12], repo="other"),
        context=context,
        ref_context=ref_context,
    )

    assert outcome.status == "exact"
    assert outcome.resolved_path == tmp_path / "other"
    assert outcome.locator == f"other@{full_sha}"


def test_unknown_repo_lists_known_repositories(tmp_path: Path) -> None:
    context = stitch_context(tmp_path / "repo")
    ref_context = ref_context_for(context, primary_repo="sase")

    outcome = resolve_stitch_entry(
        _stitch_ref("abc1234", repo="nope"), context=context, ref_context=ref_context
    )

    assert outcome.status == "unknown_repo"
    assert outcome.diagnostic is not None
    assert "sase" in outcome.diagnostic


def test_unqualified_hash_with_no_project_context_is_actionable(tmp_path: Path) -> None:
    context = stitch_context(tmp_path / "repo")
    ref_context = ref_context_for(context, primary_repo=None)

    outcome = resolve_stitch_entry(
        _stitch_ref("abc1234"), context=context, ref_context=ref_context
    )

    assert outcome.status == "unknown_repo"
    assert outcome.diagnostic is not None
    assert "needs a project" in outcome.diagnostic


def test_unresolvable_hash_is_missing_with_ambiguity_aware_diagnostic(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path / "repo")
    context = stitch_context(tmp_path / "repo")
    ref_context = ref_context_for(context, primary_repo="sase")

    outcome = resolve_stitch_entry(
        _stitch_ref("0000000"), context=context, ref_context=ref_context
    )

    assert outcome.status == "missing"
    assert outcome.diagnostic is not None
    assert "longer prefix" in outcome.diagnostic


def test_commit_alias_expands_byte_identically_to_stitch(tmp_path: Path) -> None:
    from sase.artifact_refs import process_artifact_references

    full_sha = init_git_repo(tmp_path / "repo")
    context = stitch_context(tmp_path / "repo")

    stitch_result = process_artifact_references(
        f"@stitch:sase@{full_sha[:12]}", context=context
    )
    commit_result = process_artifact_references(
        f"@commit:sase@{full_sha[:12]}", context=context
    )

    assert stitch_result == commit_result
    assert stitch_result == f"stitch {full_sha} in sase (checkout: {tmp_path / 'repo'})"


def test_expansion_format_is_valid() -> None:
    placeholders = artifact_ref_expansion_validate(_STITCH_EXPANSION_FORMAT)
    assert placeholders == ("captured_revision", "repository", "checkout_path")


def test_sha_length_boundaries() -> None:
    from sase.artifact_ref_operations import scan_artifact_refs

    def well_formed(sha: str) -> bool:
        (candidate,) = scan_artifact_refs(f"@stitch:{sha}")
        return candidate.well_formed

    assert well_formed("a" * 7) is True
    assert well_formed("a" * 40) is True
    assert well_formed("a" * 6) is False
    assert well_formed("a" * 41) is False
