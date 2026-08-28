"""Tests for ``resolve_ref``: the pager's single press-resolution seam."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.pager.document import PagerOrigin, PagerTargetSpan, target_resolution_ref
from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import LinkTargetKind, copy_text_for_target, resolve_ref


def test_resolve_ref_opens_a_text_file_as_a_document(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("hello world\n", encoding="utf-8")

    target = resolve_ref(str(path))

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    assert target.document.sections[0].plain_text == "hello world\n"
    assert target.edit_path == path


def test_resolve_ref_returns_none_for_a_missing_path(tmp_path: Path) -> None:
    assert resolve_ref(str(tmp_path / "does-not-exist.txt")) is None


def test_resolve_ref_opens_a_directory_as_a_sorted_listing(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    target = resolve_ref(str(tmp_path))

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    body = target.document.sections[0].plain_text
    assert body.index(str(tmp_path / "a.txt")) < body.index(str(tmp_path / "b.txt"))


def test_resolve_ref_returns_a_media_target_for_an_image_path(tmp_path: Path) -> None:
    path = tmp_path / "screenshot.png"
    path.write_bytes(b"\x89PNG\r\n")

    target = resolve_ref(str(path))

    assert target is not None
    assert target.kind is LinkTargetKind.MEDIA
    assert target.media_specs[0].path == path
    assert target.media_specs[0].kind == "image"
    assert target.edit_path == path


def test_resolve_ref_returns_a_binary_card_for_an_unrecognized_binary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(bytes(range(256)))

    target = resolve_ref(str(path))

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    body = target.document.sections[0].plain_text
    assert f"path: {path}" in body
    assert target.edit_path == path


@pytest.mark.parametrize("ref", ["", "   "])
def test_resolve_ref_rejects_blank_input(ref: str) -> None:
    assert resolve_ref(ref) is None


def test_copy_text_for_target_resolves_a_relative_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    copied = copy_text_for_target("sub/file.py", LinkSpanKind.FILE_PATH.value)

    assert copied == str((tmp_path / "sub" / "file.py").resolve())


def test_copy_text_for_target_returns_artifact_refs_unchanged() -> None:
    assert (
        copy_text_for_target("bead:sase-uk.5", LinkSpanKind.ARTIFACT_REF.value)
        == "bead:sase-uk.5"
    )


def _span(kind: LinkSpanKind, text: str) -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=kind.value,
        target=text,
        start=0,
        end=len(text),
        text=text,
        source="scanned",
    )


def test_target_resolution_ref_prefixes_bare_bead_tokens_in_bead_origin() -> None:
    span = _span(LinkSpanKind.BARE_TOKEN, "sase-uk.5")
    assert target_resolution_ref(span, PagerOrigin.BEAD) == "bead:sase-uk.5"


def test_target_resolution_ref_ignores_bare_tokens_outside_bead_origin() -> None:
    span = _span(LinkSpanKind.BARE_TOKEN, "sase-uk.5")
    assert target_resolution_ref(span, PagerOrigin.FILE) is None


def test_target_resolution_ref_never_resolves_urls() -> None:
    span = _span(LinkSpanKind.URL, "https://example.test")
    assert target_resolution_ref(span, PagerOrigin.FILE) is None


def test_target_resolution_ref_passes_through_artifact_refs_and_paths() -> None:
    ref_span = _span(LinkSpanKind.ARTIFACT_REF, "bead:sase-uk.5")
    path_span = _span(LinkSpanKind.FILE_PATH, "src/sase/pager/app.py")
    assert target_resolution_ref(ref_span, PagerOrigin.FILE) == "bead:sase-uk.5"
    assert target_resolution_ref(path_span, PagerOrigin.FILE) == "src/sase/pager/app.py"


def test_bead_link_target_enriches_the_link_neighborhood_without_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A followed `bead:` link must carry the LINKS block `bead show` renders.

    `resolve_show_batch` leaves `IssueDetail.artifact_links` empty unless a
    `detail_enricher` fills it, and the CLI's own enricher calls `sys.exit` on
    failure, which a keypress handler cannot survive.
    """
    from contextlib import contextmanager

    from sase.bead import cli_common, cli_show_batch
    from sase.pager.resolve import _bead_link_target

    seen: list[object] = []

    @contextmanager
    def fake_read_view() -> Iterator[object]:
        yield object()

    def spy(*_args: object, **kwargs: object) -> object:
        seen.append(kwargs.get("detail_enricher"))
        raise LookupError("stop after recording the enricher")

    monkeypatch.setattr(cli_common, "get_read_view", fake_read_view)
    monkeypatch.setattr(cli_show_batch, "resolve_show_batch", spy)

    assert _bead_link_target("bead:sase-uk") is None
    assert seen == [cli_show_batch.enrich_with_artifact_link_neighborhood]


def test_bead_link_target_resolves_foreign_bead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from sase.bead import cli_common, cross_project
    from sase.bead.cross_project import BeadStoreOrigin
    from sase.bead.model import Issue, IssueType
    from sase.pager.resolve import _bead_link_target

    class _View:
        def __init__(self, issues: dict[str, Issue]) -> None:
            self.issues = issues

        def __enter__(self) -> _View:
            return self

        def __exit__(self, *exc_info: object) -> None:
            del exc_info

        def show(self, issue_id: str) -> Issue:
            if issue_id in self.issues:
                return self.issues[issue_id]
            raise KeyError(issue_id)

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return list(self.issues.values())

    @contextmanager
    def fake_read_view() -> Iterator[_View]:
        yield _View({})

    foreign = _View(
        {
            "bob-cli-1": Issue(
                id="bob-cli-1",
                title="Foreign",
                issue_type=IssueType.TASK,
            )
        }
    )
    origin = BeadStoreOrigin(
        project_key="gh_acme__bob-cli",
        project_label="bob-cli",
        primary_workspace=tmp_path / "bob-cli",
        beads_dir=tmp_path / "bob-cli" / "sdd" / "beads",
    )
    monkeypatch.setattr(cli_common, "get_read_view", fake_read_view)
    monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: origin)
    monkeypatch.setattr(
        "sase.bead.cli_show_router.open_bead_project_for_beads_dir",
        lambda _path: foreign,
    )

    target = _bead_link_target("bead:bob-cli-1")

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    assert "bob-cli-1 · Foreign" in target.document.sections[0].plain_text
    assert "Project: bob-cli" in target.document.sections[0].plain_text
