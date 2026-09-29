"""Catalog, caching, and accent tests for the project-tag backend.

Split from ``tests.test_project_tags``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.project_accents import PROJECT_ACCENTS, project_accent_index
from sase.project_tags import (
    ProjectTagCatalog,
    is_project_tag_name,
    load_project_tag_catalog,
    peek_project_tag_catalog,
)
from sase.project_tags.catalog import _clear_project_tag_catalog_cache
from tests._project_tags_helpers import (
    make_project_record,
    patched_catalog,  # noqa: F401 (registers the autouse fixture)
    project_tag_catalog,  # noqa: F401 (registers the tag_catalog fixture)
)

__all__ = [
    "test_accent_index_matches_accent",
    "test_build_catalog_keeps_a_real_home_spec",
    "test_catalog_known_tags_are_sorted",
    "test_catalog_peek_never_builds",
    "test_catalog_targets_carry_d2_fields",
    "test_catalog_wire_targets_match_core_shape",
    "test_home_target_is_synthetic_before_its_spec_exists",
    "test_tag_name_grammar",
]


# --- Catalog ---------------------------------------------------------------


def test_catalog_targets_carry_d2_fields(tag_catalog: ProjectTagCatalog) -> None:
    by_key = {target.key: target for target in tag_catalog.targets}
    sase = by_key["sase"]
    assert (sase.name, sase.tag, sase.workflow_type) == ("sase", "+sase", "gh")
    assert sase.vcs_ref == "#gh:sase"
    assert sase.provider_display == "GitHub"
    assert sase.state == "enabled"
    assert sase.accent is not None and sase.accent_index is not None
    widgets = by_key["gh_acme__widgets"]
    assert (widgets.name, widgets.tag) == ("widgets", "+widgets")
    beta = by_key["beta"]
    assert beta.state == "disabled"
    assert beta.accent is None and beta.accent_index is None
    home = by_key["home"]
    assert home.state == "system"
    assert home.accent is None and home.accent_index is None


def test_catalog_wire_targets_match_core_shape(
    tag_catalog: ProjectTagCatalog,
) -> None:
    assert tag_catalog.wire_targets()[0] == {
        "key": "beta",
        "name": "beta",
        "aliases": [],
        "workflow_type": "git",
        "state": "disabled",
        "workspace_dir": "/tmp/workspaces/beta",
    }


def test_catalog_known_tags_are_sorted(tag_catalog: ProjectTagCatalog) -> None:
    assert tag_catalog.known_tags() == [
        "+beta",
        "+bob",
        "+home",
        "+sase",
        "+widgets",
    ]


def test_tag_name_grammar() -> None:
    assert is_project_tag_name("sase")
    assert is_project_tag_name("bob-cli")
    assert is_project_tag_name("a")
    assert not is_project_tag_name("1abc")
    assert not is_project_tag_name("sase,")
    assert not is_project_tag_name("trailing.")
    assert not is_project_tag_name("trailing-")


# --- Caching -----------------------------------------------------------------


def test_catalog_peek_never_builds(tmp_path: Path) -> None:
    _clear_project_tag_catalog_cache()
    try:
        assert peek_project_tag_catalog() is None
        first = load_project_tag_catalog(tmp_path)
        assert peek_project_tag_catalog() is first
        second = load_project_tag_catalog(tmp_path, use_cache=False)
        assert second is not first
        # An uncached load leaves the shared cache alone ...
        assert peek_project_tag_catalog() is first
        # ... and still carries the synthetic system home target.
        assert [t.key for t in second.targets] == ["home"]
        home = second.targets[0]
        assert (home.tag, home.state, home.workflow_type) == (
            "+home",
            "system",
            "git",
        )
        assert home.vcs_ref == "#git:home"
        assert home.accent is None and home.accent_index is None
    finally:
        _clear_project_tag_catalog_cache()


def test_build_catalog_keeps_a_real_home_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present ``home`` spec is never doubled by the synthetic target."""
    from sase.project_tags.catalog import _build_catalog

    home_record = make_project_record("home", system_managed=True)
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *args, **kwargs: [home_record],
    )
    catalog = _build_catalog(tmp_path)
    assert [t.key for t in catalog.targets] == ["home"]


def test_home_target_is_synthetic_before_its_spec_exists(tmp_path: Path) -> None:
    """An empty projects dir still yields the system ``home`` target."""
    from sase.project_tags.catalog import _build_catalog

    catalog = _build_catalog(tmp_path)
    assert catalog.known_tags() == ["+home"]
    (home,) = catalog.targets
    assert (home.key, home.name, home.tag) == ("home", "home", "+home")
    assert (home.workflow_type, home.state) == ("git", "system")
    assert home.vcs_ref == "#git:home"
    assert home.accent is None and home.accent_index is None
    assert home.to_wire() == {
        "key": "home",
        "name": "home",
        "aliases": [],
        "workflow_type": "git",
        "state": "system",
        "workspace_dir": None,
    }


def test_accent_index_matches_accent() -> None:
    among = ("bob", "sase")
    for key in among:
        from sase.project_accents import project_accent

        assert PROJECT_ACCENTS[project_accent_index(key, among=among)] == (
            project_accent(key, among=among)
        )
