"""Tests for ``resolve_ref``: the pager's single press-resolution seam."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.pager.document import PagerOrigin, PagerTargetSpan, target_resolution_ref
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import (
    LinkTargetKind,
    _capture_bounded_process_output,
    _git_ls_files,
    copy_text_for_target,
    resolve_link,
    resolve_ref,
)


def _context(
    *directories: Path, workspace_num: int | None = None
) -> LinkResolutionContext:
    return LinkResolutionContext(
        anchors=tuple(
            LinkAnchor(directory=directory, workspace_num=workspace_num)
            for directory in directories
        )
    )


def _write(path: Path, body: str = "ok\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


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


def test_copy_text_for_target_falls_back_to_cwd_join_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    copied = copy_text_for_target("sub/file.py", LinkSpanKind.FILE_PATH.value)

    assert copied == str((tmp_path / "sub" / "file.py").resolve())


def test_copy_text_for_target_returns_the_existing_resolution(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "src" / "file.py")

    copied = copy_text_for_target(
        "src/file.py",
        LinkSpanKind.FILE_PATH.value,
        context=_context(first, second),
    )

    assert copied == str(live.resolve())


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


def test_resolve_ref_finds_a_relative_path_in_a_later_anchor(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "src" / "foo.py")

    target = resolve_ref("src/foo.py", context=_context(first, second))

    assert target is not None
    assert target.edit_path == live.resolve()
    assert target.document is not None
    assert target.document.sections[0].plain_text == "ok\n"


def test_followed_file_document_inherits_landed_parent_context(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "src" / "foo.py")

    target = resolve_ref("src/foo.py", context=_context(first, second))

    assert target is not None
    assert target.document is not None
    assert target.document.link_context is not None
    assert target.document.link_context.base_dirs == (
        live.parent.resolve(),
        first.resolve(),
        second.resolve(),
    )


def test_resolve_ref_reroots_a_stale_numbered_clone_path(tmp_path: Path) -> None:
    stale = tmp_path / "sase_9" / "src" / "foo.py"
    live = _write(tmp_path / "primary" / "src" / "foo.py")

    target = resolve_ref(str(stale), context=_context(tmp_path / "primary"))

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_ref_parses_a_line_suffix_into_scroll_and_edit_line(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "notes.py", "a\nb\nc\n")

    target = resolve_ref(f"{path}:2")

    assert target is not None
    assert target.scroll_line == 2
    assert target.edit_line == 2
    assert target.edit_path == path


def test_resolve_ref_parses_a_line_column_suffix(tmp_path: Path) -> None:
    path = _write(tmp_path / "notes.py")

    target = resolve_ref(f"{path}:8:3")

    assert target is not None
    assert target.scroll_line == 8
    assert target.edit_line == 8


def test_resolve_ref_strips_a_trailing_dot_candidate(tmp_path: Path) -> None:
    path = _write(tmp_path / "notes.py")

    target = resolve_ref(f"{path}.")

    assert target is not None
    assert target.edit_path == path


def test_resolve_ref_strips_a_git_diff_prefix(tmp_path: Path) -> None:
    live = _write(tmp_path / "src" / "foo.py")

    target = resolve_ref("a/src/foo.py", context=_context(tmp_path))

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_ref_uses_a_unique_git_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    live = _write(workspace / "lib" / "pkg" / "deep.py")
    git_calls: list[Path] = []

    def fake_git_ls_files(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ("lib/pkg/deep.py",)

    monkeypatch.setattr("sase.pager.resolve._git_ls_files", fake_git_ls_files)

    target = resolve_ref("pkg/deep.py", context=_context(workspace))

    assert target is not None
    assert target.edit_path == live.resolve()
    assert git_calls == [workspace.resolve()]


def test_resolve_ref_dead_ends_on_an_ambiguous_git_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.pager.resolve._git_ls_files",
        lambda _directory: ("lib/pkg/deep.py", "other/pkg/deep.py"),
    )

    assert resolve_ref("pkg/deep.py", context=_context(workspace)) is None


def test_resolve_ref_does_not_run_git_when_a_direct_probe_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _write(tmp_path / "src" / "foo.py")

    def fail_git(_directory: Path) -> tuple[str, ...] | None:
        raise AssertionError("git ls-files should not run after a direct hit")

    monkeypatch.setattr("sase.pager.resolve._git_ls_files", fail_git)

    target = resolve_ref("src/foo.py", context=_context(tmp_path))

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_ref_caches_git_ls_files_per_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    live = _write(workspace / "lib" / "pkg" / "deep.py")
    git_calls: list[Path] = []

    def fake_git_ls_files(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ("lib/pkg/deep.py",)

    monkeypatch.setattr("sase.pager.resolve._git_ls_files", fake_git_ls_files)

    target = resolve_ref("a/pkg/deep.py", context=_context(workspace))

    assert target is not None
    assert target.edit_path == live.resolve()
    assert git_calls == [workspace.resolve()]


def test_resolve_ref_none_context_still_resolves_cwd_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    live = _write(tmp_path / "src" / "foo.py")

    target = resolve_ref("src/foo.py")

    assert target is not None
    assert target.edit_path == live.resolve()


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
        "sase.pager.resolve.artifact_ref_context", fake_artifact_ref_context
    )
    monkeypatch.setattr(
        "sase.pager.resolve.resolve_cli_reference", fake_resolve_cli_reference
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
        assert ref == "bead:sase-uk.5"
        calls.append(kwargs)
        raise ValueError("stop")

    monkeypatch.setattr(
        "sase.pager.resolve.resolve_cli_reference", fake_resolve_cli_reference
    )

    assert resolve_ref("bead:sase-uk.5") is None
    assert calls == [{}]


def test_resolve_ref_typed_ref_empty_context_keeps_legacy_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_resolve_cli_reference(ref: str, **kwargs: object) -> None:
        calls.append(kwargs)
        raise ValueError("stop")

    monkeypatch.setattr(
        "sase.pager.resolve.resolve_cli_reference", fake_resolve_cli_reference
    )

    assert resolve_ref("bead:sase-uk.5", context=LinkResolutionContext()) is None
    assert calls == [{}]


def test_resolve_link_returns_dead_end_diagnostics_from_one_search(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    context = _context(first, second)

    resolution = resolve_link("src/x.py", context=context)

    assert resolution.target is None
    assert resolution.unresolved_message == "src/x.py not found (searched 2 locations)"
    assert resolve_ref("src/x.py", context=context) is None


def test_missing_path_runs_git_once_per_anchor_across_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    git_calls: list[Path] = []

    def fake_git_ls_files(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ()

    monkeypatch.setattr("sase.pager.resolve._git_ls_files", fake_git_ls_files)

    resolution = resolve_link("a/pkg/deep.py", context=_context(workspace))

    assert resolution.target is None
    assert git_calls == [workspace.resolve()]
    assert resolution.unresolved_message is not None
    assert "searched" in resolution.unresolved_message


def _python_stdout_proc(script: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def test_capture_accepts_output_at_the_byte_limit() -> None:
    payload = b"src/a.py\0lib/b.py\0"
    proc = _python_stdout_proc(
        "import sys; sys.stdout.buffer.write(" + repr(payload) + ")"
    )

    captured = _capture_bounded_process_output(
        proc, max_bytes=len(payload), timeout_seconds=2.0
    )

    assert captured == payload
    assert proc.poll() is not None


def test_capture_rejects_output_over_the_byte_limit_without_keeping_it() -> None:
    payload = b"x" * 32
    proc = _python_stdout_proc(
        "import sys; sys.stdout.buffer.write(" + repr(payload) + ")"
    )

    captured = _capture_bounded_process_output(proc, max_bytes=16, timeout_seconds=2.0)

    assert captured is None
    assert proc.poll() is not None


def test_capture_times_out_and_reaps_the_child() -> None:
    proc = _python_stdout_proc("import time; time.sleep(30)")

    captured = _capture_bounded_process_output(
        proc, max_bytes=1024, timeout_seconds=0.2
    )

    assert captured is None
    assert proc.poll() is not None


def test_git_ls_files_sets_prompt_free_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    real_popen = subprocess.Popen

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        seen["env"] = kwargs.get("env")
        return real_popen(
            [sys.executable, "-c", ""],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )

    monkeypatch.setattr("sase.pager.resolve.subprocess.Popen", spy)
    _git_ls_files(tmp_path)
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_git_ls_files_accepts_output_at_the_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"src/a.py\0"
    monkeypatch.setattr("sase.pager.resolve._GIT_LS_FILES_MAX_BYTES", len(payload))
    real_popen = subprocess.Popen
    held: list[subprocess.Popen[bytes]] = []

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        proc = real_popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(" + repr(payload) + ")",
            ],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )
        held.append(proc)
        return proc

    monkeypatch.setattr("sase.pager.resolve.subprocess.Popen", spy)
    files = _git_ls_files(tmp_path)
    assert files == ("src/a.py",)
    assert held[0].poll() is not None


def test_git_ls_files_rejects_overflow_and_reaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"src/a.py\0extra\0"
    monkeypatch.setattr("sase.pager.resolve._GIT_LS_FILES_MAX_BYTES", 8)
    real_popen = subprocess.Popen
    held: list[subprocess.Popen[bytes]] = []

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        proc = real_popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(" + repr(payload) + ")",
            ],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )
        held.append(proc)
        return proc

    monkeypatch.setattr("sase.pager.resolve.subprocess.Popen", spy)
    assert _git_ls_files(tmp_path) is None
    assert held[0].poll() is not None


def test_git_ls_files_timeout_reaps_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.pager.resolve._GIT_LS_FILES_TIMEOUT_SECONDS", 0.2)
    real_popen = subprocess.Popen
    held: list[subprocess.Popen[bytes]] = []

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        proc = real_popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )
        held.append(proc)
        return proc

    monkeypatch.setattr("sase.pager.resolve.subprocess.Popen", spy)
    assert _git_ls_files(tmp_path) is None
    assert held[0].poll() is not None
