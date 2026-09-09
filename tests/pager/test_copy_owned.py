"""Owner-scoped copy must not fall through to generic path search."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_ref_models import (
    ArtifactRefDocumentOwner,
    ArtifactRefTargetCandidate,
    ArtifactRefTargetResolution,
)
from sase.pager.landings import (
    ambiguous_source_resolution,
    binary_card_document,
    commit_link_target,
)
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import copy_text_for_target, resolve_ref


def _write(path: Path, body: str = "ok\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _owned_resolution(**overrides: object) -> ArtifactRefTargetResolution:
    values: dict[str, object] = {
        "schema_version": 1,
        "status": "exact",
        "resolved_path": None,
        "repository": "capture",
        "revision": None,
        "candidates": (),
        "failure_category": None,
        "retryable": False,
    }
    values.update(overrides)
    return ArtifactRefTargetResolution(**values)  # type: ignore[arg-type]


def _owned_context(directory: Path) -> LinkResolutionContext:
    return LinkResolutionContext(
        anchors=(LinkAnchor(directory=directory),),
        owner=ArtifactRefDocumentOwner(project_key="demo"),
    )


def _forbid_generic_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.search_existing_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic search must not run after an owned lookup")
        ),
    )


def _plant_decoy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cwd = tmp_path / "cwd"
    decoy = _write(cwd / "src" / "secret.py", "decoy\n")
    monkeypatch.chdir(cwd)
    return decoy


@pytest.mark.parametrize(
    ("status", "failure_category", "retryable"),
    [
        ("missing", "proven_missing", False),
        ("missing", "denied_filtered", False),
        ("ambiguous", "ambiguous", False),
        ("missing_checkout", "missing_checkout", True),
        ("unavailable_revision", "unavailable_revision", True),
        ("temporary_error", "temporary_error", True),
    ],
)
def test_copy_keeps_logical_token_for_owned_outcomes_with_decoy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    failure_category: str,
    retryable: bool,
) -> None:
    decoy = _plant_decoy(tmp_path, monkeypatch)
    _forbid_generic_search(monkeypatch)

    def fake_lookup(
        path_text: str, *, context: LinkResolutionContext | None
    ) -> ArtifactRefTargetResolution:
        assert path_text == "src/secret.py"
        assert context is not None and context.owner is not None
        return _owned_resolution(
            status=status,
            failure_category=failure_category,
            retryable=retryable,
            diagnostic=f"{path_text} {failure_category}",
        )

    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path", fake_lookup
    )

    copied = copy_text_for_target(
        "src/secret.py",
        LinkSpanKind.FILE_PATH.value,
        context=_owned_context(tmp_path / "cwd"),
    )

    assert decoy.is_file()
    assert copied == "src/secret.py"


def test_copy_uses_owned_file_and_skips_decoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = _plant_decoy(tmp_path, monkeypatch)
    live = _write(tmp_path / "capture" / "src" / "secret.py", "live\n")
    _forbid_generic_search(monkeypatch)

    def fake_lookup(
        path_text: str, *, context: LinkResolutionContext | None
    ) -> ArtifactRefTargetResolution:
        assert path_text == "src/secret.py"
        return _owned_resolution(resolved_path=live)

    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path", fake_lookup
    )

    copied = copy_text_for_target(
        "src/secret.py",
        LinkSpanKind.FILE_PATH.value,
        context=_owned_context(tmp_path / "cwd"),
    )

    assert decoy.is_file()
    assert copied == str(live)


def test_copy_uses_owned_directory_and_skips_decoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = _plant_decoy(tmp_path, monkeypatch)
    live = tmp_path / "capture" / "src"
    live.mkdir(parents=True)
    _forbid_generic_search(monkeypatch)

    def fake_lookup(
        path_text: str, *, context: LinkResolutionContext | None
    ) -> ArtifactRefTargetResolution:
        assert path_text == "src"
        return _owned_resolution(resolved_path=live)

    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path", fake_lookup
    )

    copied = copy_text_for_target(
        "src",
        LinkSpanKind.FILE_PATH.value,
        context=_owned_context(tmp_path / "cwd"),
    )

    assert decoy.is_file()
    assert copied == str(live)


def test_copy_falls_through_when_owned_lookup_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = _plant_decoy(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.pager._resolve_file_paths.lookup_owned_source_path",
        lambda *_args, **_kwargs: None,
    )

    copied = copy_text_for_target(
        "src/secret.py",
        LinkSpanKind.FILE_PATH.value,
        context=_owned_context(tmp_path / "cwd"),
    )

    assert copied == str(decoy.resolve())


def test_commit_and_card_landings_freeze_context_known_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.pager.landings.known_kinds_from_link_context",
        lambda _context: ("designs",),
    )
    result = SimpleNamespace(
        canonical_reference="stitch:sase@deadbee1",
        parsed=SimpleNamespace(kind="stitch", payload=SimpleNamespace(sha="deadbee1")),
        resolution=SimpleNamespace(
            status="exact",
            locator="sase@deadbee1",
            resolved_path=None,
        ),
        entry=None,
    )

    commit = commit_link_target(result)  # type: ignore[arg-type]
    card = binary_card_document("plan:demo.md", path=None, mime=None)

    assert commit.document is not None
    assert "designs" in commit.document.sections[0].known_kinds
    assert "designs" in card.sections[0].known_kinds


def test_ambiguous_landing_freezes_context_known_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _write(tmp_path / "one" / "src" / "file.py")
    second = _write(tmp_path / "two" / "src" / "file.py")
    monkeypatch.setattr(
        "sase.pager.landings.known_kinds_from_link_context",
        lambda _context: ("designs",),
    )
    resolution = _owned_resolution(
        status="ambiguous",
        failure_category="ambiguous",
        candidates=(
            ArtifactRefTargetCandidate(
                path=str(first), evidence="suffix", repository="one"
            ),
            ArtifactRefTargetCandidate(
                path=str(second), evidence="suffix", repository="two"
            ),
        ),
    )
    context = _owned_context(tmp_path)
    owned = ambiguous_source_resolution("src/file.py", resolution, context)

    assert owned.target is not None
    assert owned.target.document is not None
    assert "designs" in owned.target.document.sections[0].known_kinds


def test_directory_listing_freezes_context_known_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.pager._resolve_common.known_kinds_from_link_context",
        lambda _context: ("designs",),
    )

    target = resolve_ref(str(tmp_path))

    assert target is not None
    assert target.document is not None
    assert "designs" in target.document.sections[0].known_kinds
