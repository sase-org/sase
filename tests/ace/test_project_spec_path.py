"""Tests for the project spec path helper contract."""

import os
import tempfile

from sase.ace.changespec.project_spec_path import (
    LEGACY_PROJECT_SPEC_EXTENSION,
    PROJECT_SPEC_ARCHIVE_SUFFIX,
    PROJECT_SPEC_EXTENSION,
    active_project_spec_filename,
    archive_project_spec_filename,
    is_archive_project_spec,
    legacy_active_project_spec_filename,
    legacy_archive_project_spec_filename,
    preferred_project_spec_path,
    project_spec_basename,
    to_active_project_spec_path,
    to_archive_project_spec_path,
)


def test_canonical_constants() -> None:
    assert PROJECT_SPEC_EXTENSION == ".sase"
    assert LEGACY_PROJECT_SPEC_EXTENSION == ".gp"
    assert PROJECT_SPEC_ARCHIVE_SUFFIX == "-archive"


def test_active_and_archive_filename_helpers() -> None:
    assert active_project_spec_filename("myproj") == "myproj.sase"
    assert archive_project_spec_filename("myproj") == "myproj-archive.sase"


def test_legacy_filename_helpers() -> None:
    assert legacy_active_project_spec_filename("myproj") == "myproj.gp"
    assert legacy_archive_project_spec_filename("myproj") == "myproj-archive.gp"


def test_project_spec_basename_strips_extension_and_archive_suffix() -> None:
    assert project_spec_basename("/tmp/myproj.sase") == "myproj"
    assert project_spec_basename("/tmp/myproj.gp") == "myproj"
    assert project_spec_basename("/tmp/myproj-archive.sase") == "myproj"
    assert project_spec_basename("/tmp/myproj-archive.gp") == "myproj"
    assert project_spec_basename("myproj.sase") == "myproj"
    assert project_spec_basename("foo.bar.sase") == "foo.bar"


def test_project_spec_basename_handles_no_extension() -> None:
    assert project_spec_basename("/tmp/no_ext") == "no_ext"


def test_is_archive_project_spec() -> None:
    assert is_archive_project_spec("/tmp/proj-archive.sase") is True
    assert is_archive_project_spec("/tmp/proj-archive.gp") is True
    assert is_archive_project_spec("/tmp/proj.sase") is False
    assert is_archive_project_spec("/tmp/proj.gp") is False
    assert is_archive_project_spec("/tmp/proj-archive.txt") is False
    assert is_archive_project_spec("/tmp/archive.sase") is False


def test_to_archive_project_spec_path_emits_canonical() -> None:
    assert to_archive_project_spec_path("/tmp/proj.sase") == "/tmp/proj-archive.sase"
    assert to_archive_project_spec_path("/tmp/proj.gp") == "/tmp/proj-archive.sase"
    assert (
        to_archive_project_spec_path("/tmp/proj-archive.sase")
        == "/tmp/proj-archive.sase"
    )
    assert (
        to_archive_project_spec_path("/tmp/proj-archive.gp") == "/tmp/proj-archive.sase"
    )


def test_to_active_project_spec_path_emits_canonical() -> None:
    assert to_active_project_spec_path("/tmp/proj-archive.sase") == "/tmp/proj.sase"
    assert to_active_project_spec_path("/tmp/proj-archive.gp") == "/tmp/proj.sase"
    assert to_active_project_spec_path("/tmp/proj.sase") == "/tmp/proj.sase"
    assert to_active_project_spec_path("/tmp/proj.gp") == "/tmp/proj.sase"


def test_to_archive_handles_relative_path() -> None:
    assert to_archive_project_spec_path("proj.sase") == "proj-archive.sase"
    assert to_active_project_spec_path("proj-archive.sase") == "proj.sase"


def test_preferred_project_spec_path_prefers_canonical_when_present() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        canonical = os.path.join(tmpdir, "myproj.sase")
        legacy = os.path.join(tmpdir, "myproj.gp")
        with open(canonical, "w"):
            pass
        with open(legacy, "w"):
            pass
        assert preferred_project_spec_path(tmpdir, "myproj") == canonical


def test_preferred_project_spec_path_falls_back_to_legacy() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        legacy = os.path.join(tmpdir, "myproj.gp")
        with open(legacy, "w"):
            pass
        assert preferred_project_spec_path(tmpdir, "myproj") == legacy


def test_preferred_project_spec_path_returns_canonical_when_neither_exists() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        expected = os.path.join(tmpdir, "myproj.sase")
        assert preferred_project_spec_path(tmpdir, "myproj") == expected


def test_preferred_project_spec_path_archive_variant() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        legacy_archive = os.path.join(tmpdir, "myproj-archive.gp")
        with open(legacy_archive, "w"):
            pass
        # Legacy archive file present, canonical archive not yet — falls back.
        assert (
            preferred_project_spec_path(tmpdir, "myproj", archive=True)
            == legacy_archive
        )

        canonical_archive = os.path.join(tmpdir, "myproj-archive.sase")
        with open(canonical_archive, "w"):
            pass
        # Canonical archive present — preferred.
        assert (
            preferred_project_spec_path(tmpdir, "myproj", archive=True)
            == canonical_archive
        )
