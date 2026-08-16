"""Cache-key, TTL, and root-then-member resolution tests for family previews."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
import sase.ace.tui.models.agent_family_preview_cache as cache_model
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_family_preview_cache import (
    FAMILY_PREVIEW_CACHE_MISS,
    _family_plan_preview_cache_key as family_plan_preview_cache_key,
    cached_family_plan_preview,
    should_resolve_family_plan_preview,
    warm_family_plan_previews,
)
from sase.agent_family_plan_preview import AgentFamilyPlanPreview
from tests.ace.tui.models._agent_associated_plan_helpers import write_epic, write_plan
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    cache_model._FAMILY_PREVIEW_CACHE.clear()
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    cache_model._FAMILY_PREVIEW_CACHE.clear()
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def _family_root(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_name": "fam",
        "agent_family": "fam",
        "agent_family_role": "root",
    }
    defaults.update(overrides)
    return make_agent(**defaults)


def _family_member(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_name": "fam.2",
        "parent_timestamp": "ts1",
    }
    defaults.update(overrides)
    return make_agent(**defaults)


class TestFamilyPlanPreviewCacheKey:
    def test_non_family_agent_has_no_key(self) -> None:
        agent = make_agent(agent_name="lonely")
        assert family_plan_preview_cache_key(agent) is None

    def test_stable_across_a_simulated_reload(self) -> None:
        first = _family_root(epic_bead_id="sase-1", phase_bead_id="sase-1.1")
        second = _family_root(epic_bead_id="sase-1", phase_bead_id="sase-1.1")

        assert family_plan_preview_cache_key(first) == family_plan_preview_cache_key(
            second
        )

    def test_changes_when_association_field_changes(self) -> None:
        first = _family_root(epic_bead_id="sase-1")
        second = _family_root(epic_bead_id="sase-2")

        assert family_plan_preview_cache_key(first) != family_plan_preview_cache_key(
            second
        )


class TestShouldResolveFamilyPlanPreview:
    def test_false_for_non_family_row(self) -> None:
        agent = make_agent(agent_name="plain")
        assert should_resolve_family_plan_preview(agent) is False

    def test_false_for_clan_container(self) -> None:
        agent = _family_root(is_clan_container=True)
        assert should_resolve_family_plan_preview(agent) is False

    def test_true_for_an_unresolved_family_root(self) -> None:
        agent = _family_root()
        assert should_resolve_family_plan_preview(agent) is True

    def test_false_once_warmed_within_ttl(self) -> None:
        agent = _family_root()
        warm_family_plan_previews([agent])
        assert should_resolve_family_plan_preview(agent) is False


class TestCachedFamilyPlanPreview:
    def test_reports_cache_miss_before_resolution(self) -> None:
        agent = _family_root()
        assert cached_family_plan_preview(agent) is FAMILY_PREVIEW_CACHE_MISS

    def test_reports_none_after_an_empty_resolution(self) -> None:
        agent = _family_root()
        warm_family_plan_previews([agent])
        assert cached_family_plan_preview(agent) is None

    def test_reports_the_preview_after_a_resolved_root(self, tmp_path: Path) -> None:
        plan = write_plan(tmp_path / "tale.md", "Ship the thing", tier="tale")
        agent = _family_root(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )

        warm_family_plan_previews([agent])
        preview = cached_family_plan_preview(agent)

        assert isinstance(preview, AgentFamilyPlanPreview)
        assert preview.kind == "tale"
        assert preview.title == "Associated plan metadata"


class TestWarmFamilyPlanPreviews:
    def test_resolves_the_root_entry_directly(self, tmp_path: Path) -> None:
        plan = write_plan(tmp_path / "tale.md", "Ship the thing", tier="tale")
        agent = _family_root(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )

        changed = warm_family_plan_previews([agent])
        key = family_plan_preview_cache_key(agent)

        assert key is not None
        preview = changed[key]
        assert isinstance(preview, AgentFamilyPlanPreview)
        assert preview.kind == "tale"

    def test_falls_back_to_the_first_concrete_member_when_root_is_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        write_epic(tmp_path / "plans" / "epic.md")
        monkeypatch.setattr(plan_model, "_lookup_issue", lambda *_a, **_kw: None)

        member = _family_member(
            epic_bead_id="sase-1",
            phase_bead_id="sase-1.1",
            epic_plan_ref="plans/epic.md",
            workspace_dir=str(tmp_path),
        )
        root = _family_root(
            workspace_dir=str(tmp_path),
            followup_agents=[member],
        )

        changed = warm_family_plan_previews([root])
        key = family_plan_preview_cache_key(root)

        assert key is not None
        preview = changed[key]
        assert preview is not None
        assert preview.kind == "phase"
        assert preview.title == "Canonical phase summaries"
        assert preview.parent_title == "Epic phase metadata"

    def test_authored_plan_wins_over_bead_identity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        write_epic(tmp_path / "plans" / "epic.md")
        submitted = write_plan(
            tmp_path / "submitted.md",
            "Ship the phase's own plan",
            tier="tale",
        )
        monkeypatch.setattr(plan_model, "_lookup_issue", lambda *_a, **_kw: None)

        agent = _family_root(
            agent_name="fam",
            agent_family="fam",
            phase_bead_id="sase-1.1",
            epic_bead_id="sase-1",
            epic_plan_ref="plans/epic.md",
            archived_plan_path=str(submitted),
            plan_action="tale",
            workspace_dir=str(tmp_path),
        )

        changed = warm_family_plan_previews([agent])
        key = family_plan_preview_cache_key(agent)

        assert key is not None
        preview = changed[key]
        assert preview is not None
        assert preview.kind == "tale"
        assert preview.title == "Associated plan metadata"

    def test_caches_none_when_nothing_resolves(self, tmp_path: Path) -> None:
        agent = _family_root(workspace_dir=str(tmp_path))

        changed = warm_family_plan_previews([agent])
        key = family_plan_preview_cache_key(agent)

        assert key is not None
        assert key in changed
        assert changed[key] is None

    def test_never_raises_when_one_family_fails_to_resolve(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = write_plan(tmp_path / "tale.md", "Ship the thing", tier="tale")
        good = _family_root(
            agent_name="good",
            agent_family="good",
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_committed=True,
            workspace_dir=str(tmp_path),
        )
        bad = _family_root(
            agent_name="bad",
            agent_family="bad",
            workspace_dir=str(tmp_path),
        )

        real_resolve = cache_model.resolve_agent_plan_enrichment

        def flaky_resolve(candidate: Agent, **kwargs: object) -> object:
            if candidate.agent_name == "bad":
                raise RuntimeError("boom")
            return real_resolve(candidate, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(cache_model, "resolve_agent_plan_enrichment", flaky_resolve)

        changed = warm_family_plan_previews([bad, good])

        good_key = family_plan_preview_cache_key(good)
        bad_key = family_plan_preview_cache_key(bad)
        assert good_key is not None
        assert bad_key is not None
        assert changed[good_key] is not None
        assert bad_key not in changed
