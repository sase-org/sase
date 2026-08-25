"""Tests for the Textual-free agent catalog row model (sase-tj.2)."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.dismissed_bundle_index import DismissedBundleSummary
from sase.agents.catalog import (
    AgentCatalogBuildError,
    AgentCatalogSnapshot,
    build_agent_catalog_snapshot,
)
from sase.agents.catalog import _build as catalog_build
from sase.agents.catalog._derive import (
    classify_kind,
    derive_patch,
    has_attention,
    is_dismissed,
    is_retrying,
    is_revivable,
)
from sase.agents.catalog._family import family_and_role
from sase.agents.catalog._sources import ArtifactIndexRecord


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entries: dict[str, dict[str, Any]],
    index: dict[str, ArtifactIndexRecord] | None = None,
    dismissed_top: list[DismissedBundleSummary] | None = None,
    dismissed_child: dict[str, DismissedBundleSummary] | None = None,
    project_keys: frozenset[str] = frozenset(),
) -> None:
    """Wire every _build.py collaborator to in-memory fixtures.

    _build.py imports its collaborators by name (``from ._sources import
    load_artifact_index_projection`` etc.), so the patch target must be
    _build's own module namespace — patching ._sources or ._derive
    directly would leave _build's already-bound reference untouched.
    """
    monkeypatch.setattr(
        catalog_build, "load_name_registry", lambda: {"entries": entries}
    )
    monkeypatch.setattr(
        catalog_build, "load_artifact_index_projection", lambda *a, **k: index or {}
    )
    monkeypatch.setattr(
        catalog_build, "load_dismissed_top_level", lambda: dismissed_top or []
    )
    monkeypatch.setattr(
        catalog_build,
        "load_dismissed_child_fallback",
        lambda _suffixes: dismissed_child or {},
    )
    monkeypatch.setattr(catalog_build, "known_project_keys", lambda: project_keys)


def _index_record(**overrides: Any) -> ArtifactIndexRecord:
    base: dict[str, Any] = {
        "artifact_dir": "/artifacts/x",
        "project_name": "gh_sase-org__sase",
        "workflow_name": None,
        "agent_type": "agent",
        "cl_name": None,
        "model": "claude-opus-5",
        "llm_provider": "claude",
        "status": "DONE",
        "workflow_status": None,
        "hidden": False,
        "started_at": "2026-08-01T00:00:00Z",
        "finished_at": 100.0,
        "retry_attempt": 0,
        "agent_clan": None,
        "clan_tribe": None,
        "parent_timestamp": None,
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
    }
    base.update(overrides)
    return ArtifactIndexRecord(**base)


def _summary(**overrides: Any) -> DismissedBundleSummary:
    base: dict[str, Any] = {
        "raw_suffix": "20260801000000",
        "bundle_path": "/dismissed/20260801000000.json",
        "shard": "202608",
        "filename": "20260801000000.json",
        "agent_type": "agent",
        "cl_name": "gh_sase-org__sase",
        "agent_name": "solo",
        "status": "DONE",
        "start_time": "2026-08-01T00:00:00",
        "stop_time": "2026-08-01T00:05:00",
        "project_file": "/projects/gh_sase-org__sase/gh_sase-org__sase.sase",
        "model": "claude-opus-5",
        "llm_provider": "claude",
        "vcs_provider": "github",
        "workflow": None,
        "is_workflow_child": False,
        "parent_timestamp": None,
        "step_index": None,
        "step_name": None,
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "retry_attempt": 0,
        "meta_changespec": None,
    }
    base.update(overrides)
    return DismissedBundleSummary(**base)


def _rows_by_name(snapshot: AgentCatalogSnapshot) -> dict[str, Any]:
    return {row.name: row for row in snapshot.rows}


def _leaf_entry(name: str, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "reservation_kind": "claimed",
        "state": "active",
        "project_name": "gh_sase-org__sase",
        "canonical_global_name": f"bbugyi200.athena.{name}",
    }
    entry.update(overrides)
    return entry


class TestSnapshotFixtures:
    """One fixture per row shape §10's catalog phase bullet names."""

    def test_solo_agent_enriched_by_artifact_index(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "solo": _leaf_entry(
                "solo", raw_suffix="20260801000000", artifacts_dir="/artifacts/solo"
            )
        }
        index = {"/artifacts/solo": _index_record(artifact_dir="/artifacts/solo")}
        _patch_sources(monkeypatch, entries=entries, index=index)

        row = _rows_by_name(build_agent_catalog_snapshot())["solo"]

        assert row.kind == ("agent",)
        assert row.from_artifact_index is True
        assert row.from_dismissed_archive is False
        assert row.model == "claude-opus-5"
        assert row.llm_provider == "claude"

    def test_family_container_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entries = {
            "fam1": {
                "name": "fam1",
                "container_kind": "family",
                "reservation_kind": "family",
                "state": "active",
                "project_name": "gh_sase-org__sase",
                "canonical_global_name": "bbugyi200.athena.fam1",
            }
        }
        _patch_sources(monkeypatch, entries=entries)

        row = _rows_by_name(build_agent_catalog_snapshot())["fam1"]

        assert row.kind == ("family",)
        assert row.from_artifact_index is False
        assert row.from_dismissed_archive is False

    def test_clan_container_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entries = {
            "myclan.gen": {
                "name": "myclan.gen",
                "container_kind": "clan",
                "reservation_kind": "clan",
                "state": "dismissed",
                "project_name": "gh_sase-org__sase",
                "canonical_global_name": "bbugyi200.athena.myclan.gen",
            }
        }
        _patch_sources(monkeypatch, entries=entries)

        row = _rows_by_name(build_agent_catalog_snapshot())["myclan.gen"]

        assert row.kind == ("clan",)
        assert row.clan == "myclan.gen"

    def test_family_member_row_carries_family_and_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "fam1--code": _leaf_entry(
                "fam1--code",
                state="done",
                raw_suffix="20260801000001",
                artifacts_dir="/artifacts/fam1code",
            )
        }
        _patch_sources(monkeypatch, entries=entries)

        row = _rows_by_name(build_agent_catalog_snapshot())["fam1--code"]

        assert row.kind == ("member",)
        assert row.family == "fam1"
        assert row.role == "code"

    def test_owner_qualified_name_keeps_bare_and_canonical_forms(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "imported-name": _leaf_entry(
                "imported-name",
                state="done",
                canonical_global_name="zeus.otheruser.imported-name",
            )
        }
        _patch_sources(monkeypatch, entries=entries)

        row = _rows_by_name(build_agent_catalog_snapshot())["imported-name"]

        assert row.name == "imported-name"
        assert row.canonical_global_name == "zeus.otheruser.imported-name"

    def test_collision_history_row_flags_has_collision_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "collided": _leaf_entry(
                "collided",
                state="dismissed",
                collision_owners=[{"name": "collided", "source": "artifact"}],
            )
        }
        _patch_sources(monkeypatch, entries=entries)

        row = _rows_by_name(build_agent_catalog_snapshot())["collided"]

        assert row.has_collision_history is True

    def test_workflow_child_only_suffix_matches_via_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "childrun": _leaf_entry(
                "childrun", state="dismissed", raw_suffix="20260801000099"
            )
        }
        child = {
            "20260801000099": _summary(
                raw_suffix="20260801000099",
                agent_name="childrun",
                is_workflow_child=True,
                bundle_path="/dismissed/20260801000099__c0.json",
            )
        }
        _patch_sources(monkeypatch, entries=entries, dismissed_child=child)

        row = _rows_by_name(build_agent_catalog_snapshot())["childrun"]

        assert "workflow-child" in row.kind
        assert row.from_dismissed_archive is True
        assert row.revivable is True

    def test_name_only_row_with_no_enrichment_still_renders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {"ghost": _leaf_entry("ghost", project_name=None)}
        _patch_sources(monkeypatch, entries=entries)

        row = _rows_by_name(build_agent_catalog_snapshot())["ghost"]

        assert row.kind == ("agent",)
        assert row.from_artifact_index is False
        assert row.from_dismissed_archive is False
        assert row.model is None
        assert row.project is None


class TestJoinInvariants:
    def test_ambiguous_top_level_join_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "a": _leaf_entry("a", state="dismissed", raw_suffix="dup-suffix"),
        }
        duplicated = [
            _summary(raw_suffix="dup-suffix"),
            _summary(raw_suffix="dup-suffix"),
        ]
        _patch_sources(monkeypatch, entries=entries, dismissed_top=duplicated)

        with pytest.raises(AgentCatalogBuildError):
            build_agent_catalog_snapshot()

    def test_never_selects_record_json_column(self) -> None:
        from sase.agents.catalog._sources import _ARTIFACT_INDEX_COLUMNS

        assert "record_json" not in _ARTIFACT_INDEX_COLUMNS


class TestSnapshotAggregates:
    def test_facets_collect_observed_values_across_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "one": _leaf_entry(
                "one", raw_suffix="20260801000010", artifacts_dir="/artifacts/one"
            ),
            "two": _leaf_entry(
                "two", raw_suffix="20260801000011", artifacts_dir="/artifacts/two"
            ),
        }
        index = {
            "/artifacts/one": _index_record(
                artifact_dir="/artifacts/one",
                model="claude-opus-5",
                llm_provider="claude",
            ),
            "/artifacts/two": _index_record(
                artifact_dir="/artifacts/two", model="codex-5", llm_provider="codex"
            ),
        }
        _patch_sources(monkeypatch, entries=entries, index=index)

        snapshot = build_agent_catalog_snapshot()

        assert snapshot.facets["model"] == ("claude-opus-5", "codex-5")
        assert snapshot.facets["llm_provider"] == ("claude", "codex")

    def test_counts_reflect_enrichment_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = {
            "enriched": _leaf_entry(
                "enriched",
                raw_suffix="20260801000020",
                artifacts_dir="/artifacts/enriched",
            ),
            "thin": _leaf_entry("thin"),
        }
        index = {
            "/artifacts/enriched": _index_record(artifact_dir="/artifacts/enriched")
        }
        _patch_sources(monkeypatch, entries=entries, index=index)

        snapshot = build_agent_catalog_snapshot()

        assert snapshot.registry_entry_count == 2
        assert snapshot.enriched_count == 1
        assert snapshot.thin_count == 1


class TestFamilyAndRole:
    @pytest.mark.parametrize(
        ("name", "expected_family", "expected_role"),
        [
            ("000--mon", "000", "mon"),
            ("001--2", "001", None),
            ("0b4--0", "0b4", None),
            ("0a6--1--code", "0a6--1", "code"),
            ("fam--mon-0", "fam", "mon"),
            ("plainname", None, None),
        ],
    )
    def test_family_and_role(
        self, name: str, expected_family: str | None, expected_role: str | None
    ) -> None:
        assert family_and_role(name) == (expected_family, expected_role)


class TestDeriveHelpers:
    def test_derive_patch_excludes_known_project_keys(self) -> None:
        known = frozenset({"gh_sase-org__sase"})
        assert (
            derive_patch(cl_name="gh_sase-org__sase", meta_patch=None, known_keys=known)
            is None
        )
        assert (
            derive_patch(
                cl_name="gh_sase-org__sase", meta_patch="my_patch_1", known_keys=known
            )
            == "my_patch_1"
        )
        assert (
            derive_patch(cl_name="some_other_patch", meta_patch=None, known_keys=known)
            == "some_other_patch"
        )
        assert (
            derive_patch(cl_name=None, meta_patch=None, known_keys=frozenset()) is None
        )

    def test_is_revivable(self) -> None:
        assert is_revivable(dismissed=True, bundle_path="/x") is True
        assert is_revivable(dismissed=True, bundle_path=None) is False
        assert is_revivable(dismissed=False, bundle_path="/x") is False

    def test_is_dismissed(self) -> None:
        assert is_dismissed("dismissed") is True
        assert is_dismissed("active") is False
        assert is_dismissed(None) is False

    def test_has_attention(self) -> None:
        assert has_attention("FAILED") is True
        assert has_attention("waiting") is True
        assert has_attention("DONE") is False
        assert has_attention(None) is False

    def test_is_retrying(self) -> None:
        assert (
            is_retrying(
                retry_attempt=2,
                retry_of_timestamp=None,
                retried_as_timestamp=None,
                retry_chain_root_timestamp=None,
            )
            is True
        )
        assert (
            is_retrying(
                retry_attempt=0,
                retry_of_timestamp="ts",
                retried_as_timestamp=None,
                retry_chain_root_timestamp=None,
            )
            is True
        )
        assert (
            is_retrying(
                retry_attempt=0,
                retry_of_timestamp=None,
                retried_as_timestamp=None,
                retry_chain_root_timestamp=None,
            )
            is False
        )

    def test_classify_kind_workflow_overlay(self) -> None:
        assert classify_kind(
            name="a",
            container_kind=None,
            reservation_kind="claimed",
            agent_type="workflow",
            is_workflow_child=False,
        ) == ("agent", "workflow")
        assert classify_kind(
            name="a--b",
            container_kind=None,
            reservation_kind="claimed",
            agent_type="workflow",
            is_workflow_child=True,
        ) == ("member", "workflow-child")

    def test_classify_kind_unclaimed_reservation_falls_back_to_other(self) -> None:
        assert classify_kind(
            name="a",
            container_kind=None,
            reservation_kind="planned",
            agent_type=None,
            is_workflow_child=False,
        ) == ("other",)
