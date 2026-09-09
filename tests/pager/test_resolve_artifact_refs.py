"""Tests for artifact and ownership-aware pager link resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_ref_models import (
    ArtifactRefDocumentOwner,
    ArtifactRefTargetResolution,
)
from sase.pager.document import PagerOrigin
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import resolve_link, resolve_ref

from ._resolve_helpers import _owned_resolution, _write


def test_resolve_ref_walks_typed_ref_anchors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "doc.md")
    attempted: list[tuple[Path, int]] = []

    def fake_artifact_ref_context(directory: Path, num: int) -> tuple[Path, int]:
        attempted.append((directory, num))
        return (directory, num)

    def fake_resolve_cli_reference(ref: str, **kwargs: object) -> SimpleNamespace:
        assert ref == "plan:202608/doc.md"
        context = kwargs["context"]
        if context == (second, 1):
            return SimpleNamespace(
                resolution=SimpleNamespace(status="exact", resolved_path=live),
                parsed=SimpleNamespace(kind_type="file", fragment=None, kind="file"),
                canonical_reference=ref,
                file=None,
            )
        return SimpleNamespace(
            resolution=SimpleNamespace(status="missing", resolved_path=None),
            parsed=SimpleNamespace(kind_type="file", fragment=None, kind="file"),
            canonical_reference=ref,
            file=None,
        )

    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.artifact_ref_context",
        fake_artifact_ref_context,
    )
    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.resolve_cli_reference",
        fake_resolve_cli_reference,
    )

    target = resolve_ref(
        "plan:202608/doc.md",
        context=LinkResolutionContext(
            anchors=(
                LinkAnchor(directory=first, workspace_num=11),
                LinkAnchor(directory=second, workspace_num=1),
            )
        ),
    )

    assert target is not None
    assert target.edit_path == live
    assert attempted == [(first, 11), (second, 1)]


def test_resolve_ref_typed_ref_none_context_keeps_legacy_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_resolve_cli_reference(ref: str, **kwargs: object) -> None:
        assert ref == "plan:202608/demo.md"
        calls.append(kwargs)
        raise ValueError("stop")

    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.resolve_cli_reference",
        fake_resolve_cli_reference,
    )

    assert resolve_ref("plan:202608/demo.md") is None
    assert calls == [{}]


def test_resolve_ref_typed_ref_empty_context_keeps_legacy_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_resolve_cli_reference(ref: str, **kwargs: object) -> None:
        calls.append(kwargs)
        raise ValueError("stop")

    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.resolve_cli_reference",
        fake_resolve_cli_reference,
    )

    assert resolve_ref("plan:202608/demo.md", context=LinkResolutionContext()) is None
    assert calls == [{}]


def test_resolve_ref_uses_owned_lookup_instead_of_unrelated_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    live = tmp_path / "capture" / "Sources" / "Router.swift"
    decoy = cwd / "Sources" / "Router.swift"
    live.parent.mkdir(parents=True)
    decoy.parent.mkdir(parents=True)
    live.write_text("live\n", encoding="utf-8")
    decoy.write_text("decoy\n", encoding="utf-8")
    monkeypatch.chdir(cwd)

    def fake_lookup(
        path_text: str, *, context: LinkResolutionContext | None
    ) -> ArtifactRefTargetResolution:
        assert path_text == "Sources/Router.swift"
        assert context is not None and context.owner is not None
        return _owned_resolution(resolved_path=live)

    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path", fake_lookup
    )

    target = resolve_ref(
        "Sources/Router.swift",
        context=LinkResolutionContext(
            anchors=(LinkAnchor(directory=cwd),),
            owner=ArtifactRefDocumentOwner(project_key="bob-cli"),
        ),
    )

    assert target is not None
    assert target.edit_path == live
    assert target.document is not None
    assert target.document.sections[0].plain_text == "live\n"


def test_owned_missing_checkout_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path",
        lambda _path, **_kwargs: _owned_resolution(
            status="missing_checkout",
            failure_category="missing_checkout",
            retryable=True,
            diagnostic="Sources/Router.swift checkout is unavailable",
        ),
    )

    resolution = resolve_link(
        "Sources/Router.swift",
        context=LinkResolutionContext(
            anchors=(LinkAnchor(directory=workspace),),
            owner=ArtifactRefDocumentOwner(project_key="bob-cli"),
        ),
    )

    assert resolution.target is None
    assert resolution.retryable is True
    assert resolution.unresolved_message is not None
    assert "unavailable" in resolution.unresolved_message


def test_owned_failure_does_not_probe_owner_candidate_decoys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    decoy = _write(checkout / "src" / "secret.py", "decoy\n")

    def fake_lookup(
        path_text: str, *, context: LinkResolutionContext | None
    ) -> ArtifactRefTargetResolution:
        assert path_text == "src/secret.py"
        assert context is not None and context.owner is not None
        return _owned_resolution(
            status="missing",
            failure_category="proven_missing",
            diagnostic="core-owned lookup says missing",
        )

    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path", fake_lookup
    )

    resolution = resolve_link(
        "src/secret.py",
        context=LinkResolutionContext(
            anchors=(LinkAnchor(directory=tmp_path),),
            owner=ArtifactRefDocumentOwner(
                source_reference="plan:demo.md",
                repository="checkout",
                source_directory=str(checkout),
                checkout_candidates=(checkout,),
            ),
        ),
    )

    assert decoy.is_file()
    assert resolution.target is None
    assert resolution.unresolved_message == "core-owned lookup says missing"


def test_commit_link_shows_identifiable_details() -> None:
    from sase.pager.landings import commit_link_target

    result = SimpleNamespace(
        canonical_reference="stitch:sase@deadbee1dead",
        parsed=SimpleNamespace(
            kind="stitch",
            kind_type="stitch",
            payload=SimpleNamespace(sha="deadbee1"),
        ),
        resolution=SimpleNamespace(
            status="exact",
            locator="sase@deadbee1dead",
            resolved_path=None,
        ),
        entry=SimpleNamespace(
            properties={
                "subject": "Fix pager landing",
                "author": "Ada",
                "repo": "sase",
                "sha": "deadbee1dead",
            }
        ),
        file=None,
    )

    target = commit_link_target(result)  # type: ignore[arg-type]

    assert target.document is not None
    body = target.document.sections[0].plain_text
    assert "subject: Fix pager landing" in body
    assert "sha: deadbee1dead" in body
    assert target.document.origin is PagerOrigin.DIFF
