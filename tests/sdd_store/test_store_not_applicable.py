"""Coverage for the definitively-unmanaged SDD store predicate."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._store_records import sdd_store_record_path
from sase.sdd.store import sdd_store_not_applicable, write_sdd_store_record
from tests.main.repo_init_handler_helpers import _git_init, _mark_managed_project


def test_missing_sase_yml_is_not_applicable(tmp_path: Path) -> None:
    _git_init(tmp_path)

    assert sdd_store_not_applicable(tmp_path) is True


def test_unmanaged_marker_is_not_applicable(tmp_path: Path) -> None:
    _mark_managed_project(tmp_path, config="is_sase_managed: false\n")

    assert sdd_store_not_applicable(tmp_path) is True


def test_managed_marker_is_applicable(tmp_path: Path) -> None:
    _mark_managed_project(tmp_path)

    assert sdd_store_not_applicable(tmp_path) is False


def test_invalid_yaml_is_applicable(tmp_path: Path) -> None:
    _mark_managed_project(tmp_path, config="is_sase_managed: [unclosed\n")

    assert sdd_store_not_applicable(tmp_path) is False


def test_non_bool_marker_is_applicable(tmp_path: Path) -> None:
    _mark_managed_project(tmp_path, config="is_sase_managed: 'true'\n")

    assert sdd_store_not_applicable(tmp_path) is False


def test_materialized_record_is_applicable_even_when_unmanaged(
    tmp_path: Path,
) -> None:
    _mark_managed_project(tmp_path, config="is_sase_managed: false\n")
    write_sdd_store_record(
        tmp_path,
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": "https://example.test/widget--plans.git",
            "discovery": "found",
        },
    )

    assert sdd_store_not_applicable(tmp_path) is False


def test_unreadable_store_record_is_applicable(tmp_path: Path) -> None:
    _mark_managed_project(tmp_path, config="is_sase_managed: false\n")
    record_path = sdd_store_record_path(tmp_path)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text("not json", encoding="utf-8")

    assert sdd_store_not_applicable(tmp_path) is False
