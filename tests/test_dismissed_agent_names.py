"""Tests for dismissed-name lifecycle helpers in ``sase.agent.names``.

Covers Phase 1 of the ``sase-10`` plan: prefix detection, idempotent
prefixing, conservative stripping, and collision-aware allocation that
draws from both dismissed bundles and historical artifact metadata.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    add_dismissed_prefix,
    allocate_dismissed_name,
    collect_dismissed_taken_names,
    is_dismissed_prefixed,
    strip_dismissed_prefix,
)

_DAY = date(2026, 4, 28)  # YYmmdd → "260428"
_OTHER_DAY = date(2026, 4, 29)  # → "260429"


class TestIsDismissedPrefixed:
    def test_matches_canonical_prefix(self) -> None:
        assert is_dismissed_prefixed("260428.foo")

    def test_matches_with_collision_suffix(self) -> None:
        assert is_dismissed_prefixed("260428.foo_2")

    def test_matches_when_base_has_dots(self) -> None:
        assert is_dismissed_prefixed("260428.m.claude.plan")

    def test_rejects_non_prefixed_name(self) -> None:
        assert not is_dismissed_prefixed("foo")

    def test_rejects_repeat_suffix_only(self) -> None:
        # Repeat-batch child names like ``a.1`` must not be mistaken for
        # dismissal prefixes.
        assert not is_dismissed_prefixed("a.1")

    def test_rejects_short_digit_run(self) -> None:
        assert not is_dismissed_prefixed("12345.foo")

    def test_rejects_long_digit_run(self) -> None:
        # Seven leading digits is not the canonical six-digit form.
        assert not is_dismissed_prefixed("1234567.foo")

    def test_rejects_missing_dot(self) -> None:
        assert not is_dismissed_prefixed("260428foo")

    def test_rejects_empty_string(self) -> None:
        assert not is_dismissed_prefixed("")


class TestAddDismissedPrefix:
    def test_adds_prefix_for_simple_name(self) -> None:
        assert add_dismissed_prefix("foo", _DAY) == "260428.foo"

    def test_accepts_datetime_input(self) -> None:
        ts = datetime(2026, 4, 28, 14, 30)
        assert add_dismissed_prefix("foo", ts) == "260428.foo"

    def test_idempotent_when_already_prefixed(self) -> None:
        # Same day — no change.
        assert add_dismissed_prefix("260428.foo", _DAY) == "260428.foo"

    def test_idempotent_ignores_caller_date_when_already_prefixed(self) -> None:
        # Even with a different completion date, an already-prefixed name
        # is preserved unchanged so re-dismissing doesn't double-prefix or
        # rewrite an established historical name.
        assert add_dismissed_prefix("260428.foo", _OTHER_DAY) == "260428.foo"

    def test_preserves_dotted_base(self) -> None:
        assert add_dismissed_prefix("m.claude.plan", _DAY) == "260428.m.claude.plan"

    def test_preserves_repeat_suffix(self) -> None:
        assert add_dismissed_prefix("a.1", _DAY) == "260428.a.1"

    def test_preserves_workflow_child_segment(self) -> None:
        assert add_dismissed_prefix("sase-z.2.code", _DAY) == "260428.sase-z.2.code"


class TestStripDismissedPrefix:
    def test_strips_canonical_prefix(self) -> None:
        assert strip_dismissed_prefix("260428.foo") == "foo"

    def test_strips_only_one_prefix(self) -> None:
        # If a name had been prefixed twice (would be a bug), stripping
        # only removes the first ``YYmmdd.`` so the inner prefix remains
        # visible for diagnosis.
        assert strip_dismissed_prefix("260428.260429.foo") == "260429.foo"

    def test_preserves_collision_suffix(self) -> None:
        # Phase 4 exit criterion: ``revive`` must keep collision suffix.
        assert strip_dismissed_prefix("260428.foo_2") == "foo_2"

    def test_preserves_dotted_base(self) -> None:
        assert strip_dismissed_prefix("260428.m.claude.plan") == "m.claude.plan"

    def test_returns_input_when_unprefixed(self) -> None:
        assert strip_dismissed_prefix("foo") == "foo"

    def test_returns_input_for_repeat_suffix_only(self) -> None:
        assert strip_dismissed_prefix("a.1") == "a.1"


class TestAllocateDismissedName:
    def test_returns_primary_when_pool_empty(self) -> None:
        assert allocate_dismissed_name("foo", _DAY, taken=set()) == "260428.foo"

    def test_appends_collision_suffix_starting_at_two(self) -> None:
        assert (
            allocate_dismissed_name("foo", _DAY, taken={"260428.foo"}) == "260428.foo_2"
        )

    def test_skips_taken_collision_suffixes(self) -> None:
        taken = {"260428.foo", "260428.foo_2", "260428.foo_3"}
        assert allocate_dismissed_name("foo", _DAY, taken=taken) == "260428.foo_4"

    def test_different_days_do_not_collide(self) -> None:
        # ``foo`` dismissed on a previous day does not block a fresh
        # ``YYmmdd.foo`` on a different day.
        taken = {"260427.foo", "260427.foo_2"}
        assert allocate_dismissed_name("foo", _DAY, taken=taken) == "260428.foo"

    def test_strips_prefix_from_already_prefixed_base(self) -> None:
        # Re-dismissing an already-dismissed name should not produce
        # ``260428.260427.foo``; the helper normalizes to the live base
        # before applying the current day's prefix.
        result = allocate_dismissed_name("260427.foo", _DAY, taken=set())
        assert result == "260428.foo"

    def test_preserves_collision_suffix_in_base(self) -> None:
        # ``foo.2`` is a legitimate base name (e.g. an existing
        # repeat-child). When stripped from a prior dismissal it must
        # be preserved so the new dismissed name keeps its identity.
        result = allocate_dismissed_name("260427.foo.2", _DAY, taken=set())
        assert result == "260428.foo.2"

    def test_handles_dotted_base_collisions(self) -> None:
        taken = {"260428.m.claude.plan"}
        assert (
            allocate_dismissed_name("m.claude.plan", _DAY, taken=taken)
            == "260428.m.claude.plan_2"
        )

    def test_passing_empty_taken_explicitly_skips_default_scan(self) -> None:
        # When the caller supplies *taken*, the helper must trust it —
        # otherwise a pre-built batch allocation cannot accumulate names
        # without each call rescanning the disk.
        with patch(
            "sase.agent.names.collect_dismissed_taken_names",
            side_effect=AssertionError("should not scan"),
        ):
            assert allocate_dismissed_name("foo", _DAY, taken=set()) == "260428.foo"


class TestCollectDismissedTakenNames:
    """Verify the default collision source covers bundles + artifacts."""

    def test_collects_prefixed_name_from_bundle_agent_name(
        self, tmp_path: Path
    ) -> None:
        bundles_dir = tmp_path / ".sase" / "dismissed_bundles" / "202604"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "20260428103000.json").write_text(
            json.dumps({"agent_name": "260428.foo", "raw_suffix": "20260428103000"})
        )
        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            taken = collect_dismissed_taken_names()
        assert "260428.foo" in taken

    def test_collects_prefixed_name_from_artifact_meta(self, tmp_path: Path) -> None:
        artifact_dir = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / "20260428103000"
        )
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "260428.bar"})
        )
        # Leave dismissed bundles dir non-existent so only artifacts
        # contribute.
        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / "missing",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            taken = collect_dismissed_taken_names()
        assert "260428.bar" in taken

    def test_ignores_unprefixed_names(self, tmp_path: Path) -> None:
        artifact_dir = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / "20260428103000"
        )
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "foo", "workflow_name": "a.1"})
        )
        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / "missing",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            taken = collect_dismissed_taken_names()
        assert taken == set()

    def test_ignores_corrupt_bundles_and_artifacts(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / ".sase" / "dismissed_bundles" / "202604"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "20260428103000.json").write_text("not json {")

        good_dir = bundles_dir.parent / "202605"
        good_dir.mkdir()
        (good_dir / "20260501090000.json").write_text(
            json.dumps({"agent_name": "260501.qux"})
        )

        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            taken = collect_dismissed_taken_names()
        assert taken == {"260501.qux"}

    def test_allocate_uses_default_scan_when_taken_omitted(
        self, tmp_path: Path
    ) -> None:
        bundles_dir = tmp_path / ".sase" / "dismissed_bundles" / "202604"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "20260428103000.json").write_text(
            json.dumps({"agent_name": "260428.foo"})
        )
        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            assert allocate_dismissed_name("foo", _DAY) == "260428.foo_2"
