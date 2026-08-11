from __future__ import annotations

from pathlib import Path

import pytest

import sase.core.bead_read_facade as bead_read_facade
from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefPayload,
)
from sase.artifact_providers.builtin_entry_bead import resolve_bead_entry
from sase.artifact_ref_prompt_context import PromptRefContext, PromptRefProject
from sase.bead.model import Issue, IssueType, Status


def _bead_ref(bead_id: str) -> ArtifactRef:
    return ArtifactRef(
        schema_version=5,
        kind="bead",
        kind_type="bead",
        payload=ArtifactRefPayload(type="bead", id=bead_id),
        fragment=None,
        rendered=f"bead:{bead_id}",
    )


def _store(project: str, prefix: str, tmp_path: Path) -> ArtifactRefBeadStore:
    return ArtifactRefBeadStore(project=project, prefix=prefix, root=tmp_path / prefix)


def _ref_context(context: ArtifactRefContext, project: str | None) -> PromptRefContext:
    return PromptRefContext(
        artifact_context=context,
        project=(
            None
            if project is None
            else PromptRefProject(
                key=project,
                display_name=project,
                active_spec=Path("/tmp/x.sase"),
                archive_spec=Path("/tmp/x-archive.sase"),
            )
        ),
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="explicit",
        vcs_ref=None,
    )


def _issue(full_id: str) -> Issue:
    return Issue(
        id=full_id,
        title="A test bead",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PHASE,
    )


def test_full_id_defers_to_rust_resolver(tmp_path: Path) -> None:
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "c",
        artifact_index_path=tmp_path / "i",
        repositories=(),
        projects=(),
        bead_stores=(_store("sase", "sase", tmp_path),),
    )

    outcome = resolve_bead_entry(
        _bead_ref("sase-js.4"),
        context=context,
        ref_context=_ref_context(context, "sase"),
    )

    assert outcome is None


def test_short_id_resolves_against_in_context_store_first(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_a = _store("sase", "sase", tmp_path)
    store_b = _store("other", "other", tmp_path)
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "c",
        artifact_index_path=tmp_path / "i",
        repositories=(),
        projects=(),
        bead_stores=(store_b, store_a),
    )
    # "sase-js.4" has a lineage root of "sase-js" (the part before the last
    # dot); its page lives at pages/sase-js/sase-js.4.md, not a directory
    # named after the full id (see bead_page_path in sase-core).
    page = store_a.root / "pages" / "sase-js" / "sase-js.4.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Bead\n")

    def resolve_id(beads_dir: Path, issue_id: str) -> str:
        if str(beads_dir) == str(store_a.root):
            return "sase-js.4"
        raise KeyError(f"Issue not found: {issue_id}")

    monkeypatch.setattr(bead_read_facade, "resolve_id", resolve_id)
    monkeypatch.setattr(bead_read_facade, "show", lambda _dir, full_id: _issue(full_id))

    outcome = resolve_bead_entry(
        _bead_ref("js.4"), context=context, ref_context=_ref_context(context, "sase")
    )

    assert outcome is not None
    assert outcome.status == "exact"
    assert outcome.resolved_path == page
    assert outcome.canonical_reference == "bead:sase-js.4"
    assert outcome.entry is not None
    assert outcome.entry.stable_id == "bead:sase-js.4"
    assert outcome.entry.properties["title"] == "A test bead"


def test_short_id_resolvable_in_two_stores_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_a = _store("alpha", "alpha", tmp_path)
    store_b = _store("beta", "beta", tmp_path)
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "c",
        artifact_index_path=tmp_path / "i",
        repositories=(),
        projects=(),
        bead_stores=(store_a, store_b),
    )

    def resolve_id(beads_dir: Path, issue_id: str) -> str:
        if str(beads_dir) == str(store_a.root):
            return "alpha-9z"
        return "beta-9z"

    monkeypatch.setattr(bead_read_facade, "resolve_id", resolve_id)

    outcome = resolve_bead_entry(
        _bead_ref("9z"), context=context, ref_context=_ref_context(context, None)
    )

    assert outcome is not None
    assert outcome.status == "ambiguous"
    assert set(outcome.candidates) == {"alpha: alpha-9z", "beta: beta-9z"}


def test_ambiguous_prefix_within_one_store_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store("sase", "sase", tmp_path)
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "c",
        artifact_index_path=tmp_path / "i",
        repositories=(),
        projects=(),
        bead_stores=(store,),
    )

    def resolve_id(_beads_dir: Path, issue_id: str) -> str:
        raise ValueError(
            f'ambiguous: ambiguous bead ID shorthand "{issue_id}": sase-a1, sase-a2'
        )

    monkeypatch.setattr(bead_read_facade, "resolve_id", resolve_id)

    outcome = resolve_bead_entry(
        _bead_ref("a1"), context=context, ref_context=_ref_context(context, "sase")
    )

    assert outcome is not None
    assert outcome.status == "ambiguous"
    assert outcome.diagnostic is not None
    assert "sase-a1" in outcome.diagnostic


def test_no_store_resolves_short_id_defers_to_rust(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store("sase", "sase", tmp_path)
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "c",
        artifact_index_path=tmp_path / "i",
        repositories=(),
        projects=(),
        bead_stores=(store,),
    )

    def resolve_id(_beads_dir: Path, issue_id: str) -> str:
        raise KeyError(f"Issue not found: {issue_id}")

    monkeypatch.setattr(bead_read_facade, "resolve_id", resolve_id)

    outcome = resolve_bead_entry(
        _bead_ref("zz"), context=context, ref_context=_ref_context(context, "sase")
    )

    assert outcome is None
