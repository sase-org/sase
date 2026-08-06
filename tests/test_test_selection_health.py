"""Unit tests for the selection-health store: where it lives and what it holds.

Everything here runs against a synthetic store under ``tmp_path``. This module
pins the first half of the measurement — what gets written and read back — while
its siblings pin what the correlator concludes from it
(``test_test_selection_health_correlation.py``), how that reads as a report
(``test_test_selection_health_report.py``), and the full-lane recorder plugin
(``test_test_selection_health_plugin.py``).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from tests._selection_health_case_helpers import (
    NOW,
    WORKSPACE,
    git_init,
    manifest,
    write_full_run,
    write_selection,
)
from tests._test_selection_health_records import load_records
from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    PROJECT_KEY_ENV,
    SASE_HOME_ENV,
    STORE_ENV,
    allocate_record_path,
    project_key,
    prune_store,
    record_selection,
    store_directory,
    workspace_identity,
)


# --------------------------------------------------------------------------
# Store location
# --------------------------------------------------------------------------


def test_project_key_matches_the_projectspec_key_for_a_github_remote(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sase_11"
    root.mkdir()
    git_init(root, remote="https://github.com/sase-org/sase.git")

    assert project_key(root, {}) == "gh_sase-org__sase"


def test_project_key_falls_back_to_the_workspace_stripped_directory_name(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sase_11"
    root.mkdir()
    git_init(root, remote=None)

    assert project_key(root, {}) == "sase"


def test_project_key_environment_override_wins(tmp_path: Path) -> None:
    assert project_key(tmp_path, {PROJECT_KEY_ENV: "custom"}) == "custom"


def test_store_directory_lives_under_sase_home_by_project(tmp_path: Path) -> None:
    root = tmp_path / "sase_3"
    root.mkdir()
    git_init(root, remote="git@github.com:sase-org/sase.git")
    home = tmp_path / "home"

    store = store_directory(root, {SASE_HOME_ENV: str(home)})

    assert store == home / "test-selection" / "gh_sase-org__sase"


def test_workspace_identity_is_the_resolved_root(tmp_path: Path) -> None:
    root = tmp_path / "sase_11"
    root.mkdir()
    link = tmp_path / "current"
    link.symlink_to(root)

    assert workspace_identity(link) == str(root.resolve())


def test_store_directory_environment_override_wins(tmp_path: Path) -> None:
    override = tmp_path / "elsewhere"

    assert store_directory(tmp_path, {STORE_ENV: str(override)}) == override


# --------------------------------------------------------------------------
# Writing, pruning, loading
# --------------------------------------------------------------------------


def test_recording_a_selection_writes_a_timestamped_record(tmp_path: Path) -> None:
    path = write_selection(tmp_path / "store", manifest(head="a" * 40))

    assert path.name == f"20260805T120000Z-{'a' * 12}-1000.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "selection"
    assert payload["manifest"]["selected_count"] == 0


def test_pruning_drops_records_past_retention_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    old = write_selection(store, manifest(head="a" * 40), minute=0)
    recent = record_selection(
        store,
        manifest(head="b" * 40),
        workspace=WORKSPACE,
        pid=7,
        now=NOW + timedelta(days=29),
    )
    unfamiliar = store / "notes.txt"
    unfamiliar.write_text("hand-written", encoding="utf-8")

    removed = prune_store(store, now=NOW + timedelta(days=31))

    assert removed == [old]
    assert not old.exists()
    assert recent.exists()
    assert unfamiliar.exists()


def test_allocating_a_record_path_prunes_the_store(tmp_path: Path) -> None:
    store = tmp_path / "store"
    stale = write_selection(store, manifest(head="a" * 40))

    allocate_record_path(
        store, KIND_FULL_RUN, head="b" * 40, pid=9, now=NOW + timedelta(days=45)
    )

    assert not stale.exists()


def test_loading_records_separates_kinds_and_ignores_junk(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="a" * 40))
    write_full_run(store, head="b" * 40, failures=("tests/test_x.py::test_y",))
    (store / "20260805T120000Z-cccccccccccc-3.json").write_text(
        "not json", encoding="utf-8"
    )

    records = load_records(store)

    assert len(records.selections) == 1
    assert len(records.full_runs) == 1
    assert records.full_runs[0].failures == ("tests/test_x.py::test_y",)


def test_loading_an_absent_store_is_empty_not_an_error(tmp_path: Path) -> None:
    records = load_records(tmp_path / "missing")

    assert records.selections == ()
    assert records.full_runs == ()
