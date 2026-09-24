"""Cache-invalidation tests for ``+`` VCS project completion."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sase.xprompt import vcs_project_completion as vpc
from sase.xprompt.vcs_project_completion import build_vcs_project_completion_entries
from tests._xprompt_vcs_project_completion_helpers import (
    _REAL_MRU_CATALOG_RANK,
    _patch,
    _patch_catalog,
    _record,
    clear_vcs_project_completion_cache as clear_vcs_project_completion_cache,
)


def test_builder_caches_on_unchanged_directory(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p as list_mock, detect_p, display_p:
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert first == second
    assert list_mock.call_count == 1


def test_clear_cache_forces_rebuild(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p as list_mock, detect_p, display_p:
        build_vcs_project_completion_entries(projects_dir=tmp_path)
        vpc._clear_vcs_project_completion_cache()
        build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert list_mock.call_count == 2


def test_use_cache_false_always_rebuilds(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p as list_mock, detect_p, display_p:
        build_vcs_project_completion_entries(projects_dir=tmp_path, use_cache=False)
        build_vcs_project_completion_entries(projects_dir=tmp_path, use_cache=False)

    assert list_mock.call_count == 2


def test_returned_list_is_isolated_from_cache(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p, detect_p, display_p:
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        first.clear()
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert [e.name for e in second] == ["sase"]


def test_cache_invalidates_when_project_spec_mtime_changes(tmp_path) -> None:
    spec_file = tmp_path / "sase" / "sase.sase"
    spec_file.parent.mkdir()
    spec_file.write_text("NAME: first\nSTATUS: WIP\n", encoding="utf-8")
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    patch_versions = [
        [_patch("first", "sase", "WIP")],
        [_patch("second", "sase", "Ready")],
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p as list_mock,
        detect_p,
        display_p,
        patch.object(vpc, "iter_patch_project_files", return_value=[spec_file]),
        patch.object(
            vpc, "_iter_enabled_project_patches", side_effect=patch_versions
        ) as patch_mock,
    ):
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)
        stat = spec_file.stat()
        os.utime(
            spec_file,
            ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
        )
        third = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert [entry.name for entry in first if entry.kind == "patch"] == ["first"]
    assert second == first
    assert [entry.name for entry in third if entry.kind == "patch"] == ["second"]
    assert list_mock.call_count == 2
    assert patch_mock.call_count == 2


def test_cache_invalidates_when_mru_store_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``current`` badge and MRU order follow ``set-current`` (D7).

    ``sase project set-current`` writes only the MRU, so the entries cache
    keys on the MRU store alongside the spec signature.
    """
    import sase.history.vcs_xprompt_mru as mru_module

    records = [_record("sase"), _record("bob")]
    workflow_types = {"sase": "gh", "bob": "git"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)
    mru_file = tmp_path / "vcs_xprompt_mru.json"
    mru_file.write_text('{"entries": ["#gh:sase"]}', encoding="utf-8")
    monkeypatch.setattr(mru_module, "_MRU_FILE", mru_file)
    # Keep every MRU entry: with no resolvability snapshot the prune guards
    # keep entries rather than risk nuking the store, so the rank below is
    # computed from the real store contents.
    monkeypatch.setattr(mru_module, "_resolvable_vcs_ref_index", lambda: None)

    with (
        list_p as list_mock,
        detect_p,
        display_p,
        # Exercise the real recency rank; the module fixture stubs it.
        patch.object(vpc, "_mru_catalog_rank", _REAL_MRU_CATALOG_RANK),
    ):
        # The current key tracks the MRU head the way `set-current` writes
        # it; resolution itself is covered by the current-project tests.
        with patch.object(vpc, "_current_catalog_key", return_value="sase"):
            first = build_vcs_project_completion_entries(projects_dir=tmp_path)
            second = build_vcs_project_completion_entries(projects_dir=tmp_path)
        assert second == first
        assert list_mock.call_count == 1
        assert [entry.name for entry in first] == ["sase", "bob"]
        assert [entry.current for entry in first] == [True, False]
        # Rewrite the store the way `sase project set-current` does.
        mru_file.write_text(
            '{"entries": ["#git:bob", "#gh:sase", "#git:bob-extra"]}',
            encoding="utf-8",
        )
        stat = mru_file.stat()
        os.utime(
            mru_file,
            ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
        )
        with patch.object(vpc, "_current_catalog_key", return_value="bob"):
            third = build_vcs_project_completion_entries(projects_dir=tmp_path)
        assert [entry.name for entry in third] == ["bob", "sase"]
        assert [entry.current for entry in third] == [True, False]
        assert list_mock.call_count == 2
