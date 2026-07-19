"""Associated-plan availability and invalid-content tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from tests.ace.tui.models._agent_associated_plan_helpers import (
    resolve_agent_associated_plan,
    write_epic,
    write_plan,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def test_known_missing_plan_keeps_path_and_unavailable_metadata(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing plan.md"
    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(missing), plan_path=str(missing))
    )

    assert summary is not None
    assert summary.actual_path == str(missing.resolve())
    assert summary.title is None
    assert summary.goal is None
    assert summary.effective_tier is None
    assert not summary.exists
    assert not summary.readable
    assert not summary.frontmatter_readable
    assert summary.phase_availability == "not-applicable"
    assert summary.phases == ()


@pytest.mark.parametrize(
    ("plan_action", "expected_tier", "expected_phase_availability"),
    [
        ("approve", "plan", "not-applicable"),
        ("commit", "tale", "not-applicable"),
        ("tale", "tale", "not-applicable"),
        ("epic", "epic", "unavailable"),
    ],
)
def test_known_missing_plan_preserves_explicit_approval_tier(
    tmp_path: Path,
    plan_action: str,
    expected_tier: str,
    expected_phase_availability: str,
) -> None:
    missing = tmp_path / "missing plan.md"

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(missing),
            plan_path=str(missing),
            plan_action=plan_action,
            plan_committed=False,
        )
    )

    assert summary is not None
    assert summary.effective_tier == expected_tier
    assert summary.phase_availability == expected_phase_availability
    assert summary.phases == ()


def test_damaged_frontmatter_keeps_readable_plan_association(tmp_path: Path) -> None:
    plan = tmp_path / "damaged.md"
    plan.write_text("---\ntier: [tale\n---\n# Plan\n", encoding="utf-8")

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.exists
    assert summary.readable
    assert not summary.frontmatter_readable
    assert summary.title is None
    assert summary.goal is None
    assert summary.effective_tier is None


@pytest.mark.parametrize(
    "content",
    [
        "---\ntier: [epic\n---\n# Plan\n",
        "---\n- epic\n---\n# Plan\n",
        (
            "---\ntier: epic\ntitle: Invalid epic\ngoal: Retain the goal\n"
            "phases:\n  - id: core\n    title: Valid first phase\n"
            "    depends_on: []\n  - id: later\n"
            "    title: Missing dependencies\n"
            "---\n# Plan\n"
        ),
    ],
)
def test_invalid_known_epic_never_leaks_partial_phases(
    tmp_path: Path,
    content: str,
) -> None:
    plan = tmp_path / "invalid epic.md"
    plan.write_text(content, encoding="utf-8")

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action="epic",
        )
    )

    assert summary is not None
    assert summary.phase_availability == "unavailable"
    assert summary.phases == ()


def test_unreadable_known_epic_never_attempts_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_epic(tmp_path / "unreadable.md")
    monkeypatch.setattr(plan_model.os, "access", lambda *_args: False)
    monkeypatch.setattr(
        plan_model,
        "validate_plan",
        lambda *_args: pytest.fail("unreadable plans must not be validated"),
    )

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action="epic",
        )
    )

    assert summary is not None
    assert summary.exists
    assert not summary.readable
    assert summary.phase_availability == "unavailable"
    assert summary.phases == ()


def test_readable_tale_never_renders_phases_even_with_epic_runtime_context(
    tmp_path: Path,
) -> None:
    plan = write_plan(tmp_path / "tale.md", "Keep the compact tale")

    summary = resolve_agent_associated_plan(
        make_agent(
            archived_plan_path=str(plan),
            plan_path=str(plan),
            plan_action="epic",
        )
    )

    assert summary is not None
    assert summary.effective_tier == "epic"
    assert summary.authored_tier == "tale"
    assert summary.phase_availability == "not-applicable"
    assert summary.phases == ()


def test_legacy_titleless_plan_keeps_association_with_unavailable_title(
    tmp_path: Path,
) -> None:
    plan = write_plan(
        tmp_path / "legacy.md",
        "Keep historical plans discoverable",
        title=None,
    )

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.title is None
    assert summary.goal == "Keep historical plans discoverable"
    assert summary.frontmatter_readable
