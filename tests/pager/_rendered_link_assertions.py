"""Assertion and monkeypatch helpers shared by the rendered-link contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefDocumentOwner
from sase.pager.document import (
    PagerDocument,
    PagerTargetSpan,
    section_target_spans,
    target_resolution_ref,
)

from tests.pager._rendered_link_expected import ExpectedOccurrence
from tests.pager._rendered_link_tree import RenderedLinkCorpus


def rendered_spans(document: PagerDocument) -> tuple[PagerTargetSpan, ...]:
    """Return merged scanned/attached spans in document order."""
    spans: list[PagerTargetSpan] = []
    for section in document.sections:
        spans.extend(section_target_spans(section, document.origin))
    return tuple(spans)


def assert_expected_rendered(
    document: PagerDocument,
    expected: tuple[ExpectedOccurrence, ...],
) -> None:
    """Fail if the scanner omitted any independently declared occurrence."""
    actual = [
        (span.kind, span.text, target_resolution_ref(span, document.origin))
        for span in rendered_spans(document)
    ]
    actual_keys = {(kind, text) for kind, text, _ref in actual}
    missing = [
        occurrence
        for occurrence in expected
        if (occurrence.kind, occurrence.display) not in actual_keys
    ]
    assert missing == [], f"scanner omitted {missing!r}; actual={actual!r}"
    by_display = {(kind, text): ref for kind, text, ref in actual}
    for occurrence in expected:
        assert by_display[(occurrence.kind, occurrence.display)] == (
            occurrence.resolution_ref
        )


def owner_for_checkout(
    checkout: Path, *, source_reference: str
) -> ArtifactRefDocumentOwner:
    """Build an owner that prefers *checkout* as an attached candidate."""
    return ArtifactRefDocumentOwner(
        source_reference=source_reference,
        source_directory=str(checkout),
        checkout_candidates=(checkout,),
        repository=checkout.name,
    )


def install_inventory(
    monkeypatch: pytest.MonkeyPatch, corpus: RenderedLinkCorpus
) -> None:
    """Replace inventory/store assembly with the corpus context."""

    def fake_context(
        workspace_dir: str | Path,
        workspace_num: int = 1,
        project: str | None = None,
    ) -> ArtifactRefContext:
        del workspace_num, project
        return corpus.context_for(Path(workspace_dir))

    monkeypatch.setattr("sase.artifact_ref_context.artifact_ref_context", fake_context)
    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.artifact_ref_context", fake_context
    )
    monkeypatch.chdir(corpus.cwd)


@contextmanager
def forbid_checkout_allocation(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail if a label press clones, resets, or allocates a workspace."""

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("label press must not allocate or clean a checkout")

    monkeypatch.setattr(
        "sase.running_field._workspace.get_workspace_directory_for_num",
        boom,
    )
    yield
