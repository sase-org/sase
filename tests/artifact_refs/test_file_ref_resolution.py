from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_refs import (
    ArtifactRefContext,
    ArtifactRefFileRoot,
    resolve_artifact_ref,
)

from .helpers import context as make_context


def _context(
    tmp_path: Path,
    root: Path,
    *,
    path_globs: tuple[str, ...] | None = None,
    home_dir: Path | None = None,
    max_bytes: int | None = None,
) -> ArtifactRefContext:
    base = make_context(tmp_path)
    return ArtifactRefContext(
        document_roots=base.document_roots,
        chats_root=base.chats_root,
        artifact_index_path=base.artifact_index_path,
        repositories=base.repositories,
        projects=base.projects,
        file_roots=(ArtifactRefFileRoot("bob", root, path_globs),),
        home_dir=home_dir or tmp_path,
        file_capture_max_bytes=max_bytes,
    )


def test_file_ref_resolves_absolute_and_home_to_logical_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bob = home / "bob"
    bob.mkdir(parents=True)
    note = bob / "gtd.md"
    note.write_text("tasks", encoding="utf-8")
    context = _context(tmp_path, bob, home_dir=home)

    absolute = resolve_artifact_ref(f"file:{note}", context=context)
    home_ref = resolve_artifact_ref("file:~/bob/gtd.md", context=context)

    assert absolute.status == "exact"
    assert home_ref.status == "exact"
    assert absolute.locator == home_ref.locator == "bob:gtd.md"
    assert absolute.resolved_path == home_ref.resolved_path == note.resolve()


def test_file_ref_rejects_outside_roots_glob_miss_and_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    image = root / "image.png"
    image.write_text("png", encoding="utf-8")
    context = _context(tmp_path, root, path_globs=("**/*.md",))

    outside_resolution = resolve_artifact_ref(f"file:{secret}", context=context)
    glob_miss = resolve_artifact_ref(f"file:{image}", context=context)
    missing = resolve_artifact_ref(f"file:{root / 'missing.md'}", context=context)

    assert outside_resolution.status == "filtered"
    assert glob_miss.status == "filtered"
    assert "image.png" in (glob_miss.diagnostic or "")
    assert str(root) not in (glob_miss.diagnostic or "")
    assert missing.status == "missing"


def test_file_ref_denies_directories_and_size_overages(tmp_path: Path) -> None:
    root = tmp_path / "root"
    directory = root / "dir"
    directory.mkdir(parents=True)
    file = root / "large.bin"
    file.write_text("abcdef", encoding="utf-8")
    context = _context(tmp_path, root, max_bytes=3)

    directory_resolution = resolve_artifact_ref(f"file:{directory}", context=context)
    too_large = resolve_artifact_ref(f"file:{file}", context=context)

    assert directory_resolution.status == "denied"
    assert "directory" in (directory_resolution.diagnostic or "")
    assert too_large.status == "denied"
    assert "6 bytes > 3 bytes" in (too_large.diagnostic or "")


def test_file_ref_digest_payloads_still_resolve_as_before(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    resolution = resolve_artifact_ref(
        "file:default:52895d68931185056fd0e49f",
        context=context,
    )

    assert resolution.status in {"missing", "exact", "vcs_backed", "ambiguous"}


@pytest.mark.parametrize("payload", ["relative.md", ""])
def test_file_ref_relative_payload_is_not_resolved_from_cwd(
    tmp_path: Path,
    payload: str,
) -> None:
    context = _context(tmp_path, tmp_path)

    if payload:
        resolution = resolve_artifact_ref(f"file:{payload}", context=context)
        assert resolution.status == "denied"
    else:
        with pytest.raises(ValueError):
            resolve_artifact_ref("file:", context=context)
