"""Tests for display-only project name resolution."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase import project_display_names as pdn


def _record(project_name: str, display_name: str | None = None) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def test_project_display_name_for_resolves_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets"), _record("plain")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert pdn.project_display_name_for("plain", root) == "plain"
    assert pdn.project_display_name_for("missing", root) == "missing"


def test_humanize_cl_name_rewrites_exact_key_and_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_cl_name("gh_acme__widgets", root) == "widgets"
    assert (
        pdn.humanize_cl_name("gh_acme__widgets_fix_button_1", root)
        == "widgets_fix_button_1"
    )


def test_humanize_cl_name_prefers_longest_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__widgets_extra", "widgets_extra"),
    ]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_cl_name("gh_acme__widgets_extra_fix_button", root)
        == "widgets_extra_fix_button"
    )


def test_humanize_cl_name_unknown_and_empty_map_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: [])
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_cl_name("gh_acme__widgets_fix_button", root) == (
        "gh_acme__widgets_fix_button"
    )

    records = [_record("gh_acme__widgets", "widgets")]
    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_cl_name("other_fix_button", root) == "other_fix_button"


def test_humanize_cl_names_in_text_rewrites_tokens_but_not_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    text = (
        "Sync done for gh_acme__widgets_fix_button_1: "
        "/tmp/gh_acme__widgets/gh_acme__widgets_fix_button_1"
    )

    assert pdn.humanize_cl_names_in_text(text, root) == (
        "Sync done for widgets_fix_button_1: "
        "/tmp/gh_acme__widgets/gh_acme__widgets_fix_button_1"
    )


def test_humanize_safe_stem_rewrites_exact_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_safe_stem("gh_acme__widgets", root) == "widgets"


def test_humanize_safe_stem_rewrites_joined_prefixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_acme__widgets-ace_run-260707", root)
        == "widgets-ace_run-260707"
    )
    assert (
        pdn.humanize_safe_stem("gh_acme__widgets_fix_button-260707", root)
        == "widgets_fix_button-260707"
    )


def test_humanize_safe_stem_matches_sanitized_hyphenated_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_sase-org__sase", "sase")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_sase_org__sase-ace_run-260707_011513", root)
        == "sase-ace_run-260707_011513"
    )


def test_humanize_safe_stem_unknown_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_other__widgets-ace_run-260707", root)
        == "gh_other__widgets-ace_run-260707"
    )


def test_humanize_safe_stem_prefers_longest_safe_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__widgets_extra", "widgets_extra"),
    ]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_acme__widgets_extra_fix_button-260707", root)
        == "widgets_extra_fix_button-260707"
    )


def test_project_display_name_cache_invalidates_on_projects_dir_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    calls = 0
    display_name = "widgets"

    def fake_list_project_records(
        *_args: object, **_kwargs: object
    ) -> list[ProjectRecordWire]:
        nonlocal calls
        calls += 1
        return [_record("gh_acme__widgets", display_name)]

    monkeypatch.setattr(pdn, "list_project_records", fake_list_project_records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    display_name = "gadgets"
    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert calls == 1

    stat = root.stat()
    os.utime(
        root, ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000)
    )

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "gadgets"
    assert calls == 2


def test_attach_project_display_names_duck_types_and_clears_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__plain", "gh_acme__plain"),
    ]
    widgets = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name=None,
    )
    equal = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__plain/gh_acme__plain.sase",
        project_display_name="stale",
    )
    missing = SimpleNamespace(
        project_file="/tmp/projects/missing/missing.sase",
        project_display_name="stale",
    )
    ignored = SimpleNamespace(project_file="/tmp/projects/ignored/ignored.sase")

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    pdn.attach_project_display_names([widgets, equal, missing, ignored], root)

    assert widgets.project_display_name == "widgets"
    assert equal.project_display_name is None
    assert missing.project_display_name is None
    assert not hasattr(ignored, "project_display_name")
