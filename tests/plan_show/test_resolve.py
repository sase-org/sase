"""Tests for :mod:`sase.plan_show.resolve`.

Drives resolution through the real Rust plan-reference/plan-search bindings
over temp trees (as ``tests/test_plan_search_facade.py`` does), and through
the real notification store (redirected to a per-test ``~/.sase`` by the
autouse ``_isolate_sase_home`` conftest fixture). Only the bead-store read
view and the live-agent visibility loader are stubbed.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.bead.model import Issue
from sase.core.time import get_timezone
from sase.notifications.models import Notification
from sase.notifications.store import append_notification
from sase.plan_show.model import PlanShowAmbiguity, PlanShowMiss, PlanShowRecord
from sase.plan_show.resolve import resolve_plan_show_target

_LIVE_AGENT_TS = "20260613120000"


@pytest.fixture(autouse=True)
def _visible_plan_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make pending plan notifications resolvable, mirroring the sibling
    ``sase plan approve``/``reject`` CLI test fixtures."""
    monkeypatch.setattr(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        lambda notifications: (
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="demo-cl",
                project_file="/tmp/demo-project.sase",
                status="PLAN",
                start_time=None,
                raw_suffix=_LIVE_AGENT_TS,
                agent_name="planner",
                workspace_dir="/work/demo-project",
            ),
        ),
    )


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (sdd_root, plans_root, local_root) for a hermetic corpus."""
    sdd_root = tmp_path / "sdd"
    plans_root = sdd_root / "plans"
    local_root = tmp_path / "local_plans"
    plans_root.mkdir(parents=True)
    local_root.mkdir(parents=True)
    return sdd_root, plans_root, local_root


def _write_plan(
    path: Path, *, title: str = "T", goal: str = "G", tier: str = "tale"
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntier: {tier}\ntitle: {title}\ngoal: {goal}\n---\n# {title}\n",
        encoding="utf-8",
    )


def _resolve(
    raw: str | None,
    *,
    sdd_root: Path,
    plans_root: Path,
    local_root: Path,
    cwd: Path,
    target_kind: str = "auto",
) -> PlanShowRecord | PlanShowMiss | PlanShowAmbiguity:
    return resolve_plan_show_target(
        raw,
        target_kind=target_kind,
        cwd=cwd,
        roots=(plans_root, local_root),
        repo_root=sdd_root,
        local_dir=local_root,
    )


def _append_plan_notification(
    notification_id: str,
    plan_file: Path,
    *,
    response_dir: str = "/tmp/resp",
    agent_cl_name: str = "demo-cl",
    agent_name: str = "planner",
) -> None:
    append_notification(
        Notification(
            id=notification_id,
            timestamp=datetime.now(get_timezone()).isoformat(),
            sender="plan",
            files=[str(plan_file)],
            action="PlanApproval",
            action_data={
                "response_dir": response_dir,
                "agent_cl_name": agent_cl_name,
                "agent_name": agent_name,
            },
        )
    )


def _use_bead_view(monkeypatch: pytest.MonkeyPatch, issues: dict[str, Issue]) -> None:
    class _View:
        def show(self, issue_id: str) -> Issue:
            if issue_id in issues:
                return issues[issue_id]
            raise KeyError(issue_id)

    @contextmanager
    def read_view() -> Iterator[_View]:
        yield _View()

    monkeypatch.setattr("sase.plan_show.resolve.get_read_view", read_view)


# --- path rung ---------------------------------------------------------


def test_rung_path_resolves_absolute_path(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    plan_path = plans_root / "202608" / "a.md"
    _write_plan(plan_path)

    result = _resolve(
        str(plan_path),
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "path"
    assert result.target.status == "exact"
    assert result.plan.exists is True


def test_rung_path_resolves_relative_path(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "a.md")

    result = _resolve(
        "sdd/plans/202608/a.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "path"


def test_rung_path_declines_for_missing_file(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)

    result = _resolve(
        str(plans_root / "202608" / "missing.md"),
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowMiss)


# --- ref rung ------------------------------------------------------------


def test_rung_ref_resolves_plans_reference(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "a.md")

    result = _resolve(
        "plans:202608/a.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "ref"
    assert result.target.status == "exact"
    assert result.plan.reference == "plan:202608/a.md"


def test_rung_ref_accepts_legacy_marker_path(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "a.md")

    # Forced so the ``path`` rung (which would otherwise also match this
    # cwd-relative string) doesn't win first.
    result = _resolve(
        "sdd/plans/202608/a.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
        target_kind="ref",
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "ref"


def test_rung_ref_reports_month_drift(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "a.md")

    result = _resolve(
        "plans:202607/a.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.status == "drifted"


def test_rung_ref_ambiguous_reports_candidates(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202607" / "a.md")
    _write_plan(plans_root / "202608" / "a.md")

    result = _resolve(
        "plans:202609/a.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowAmbiguity)
    assert len(result.candidates) == 2


# --- proposal rung -------------------------------------------------------


def test_rung_proposal_resolves_by_id_and_prefix(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    plan_path = plans_root / "202608" / "proposed.md"
    _write_plan(plan_path)
    _append_plan_notification("abcdef120001", plan_path)

    by_id = _resolve(
        "abcdef120001",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )
    by_prefix = _resolve(
        "abcdef12",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    for result in (by_id, by_prefix):
        assert isinstance(result, PlanShowRecord)
        assert result.target.kind == "proposal"
        assert result.proposal is not None
        assert result.proposal.id_prefix == "abcdef12"


def test_rung_proposal_ambiguous_prefix(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    first = plans_root / "202608" / "first.md"
    second = plans_root / "202608" / "second.md"
    _write_plan(first)
    _write_plan(second)
    _append_plan_notification("abcdef120001", first)
    _append_plan_notification("abcdef120002", second)

    result = _resolve(
        "abcdef12",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowAmbiguity)
    assert len(result.candidates) == 2


def test_rung_proposal_skips_path_shaped_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resolve_pending_plan should not be called")

    monkeypatch.setattr("sase.plan_show.resolve.resolve_pending_plan", _fail)

    result = _resolve(
        "some/path.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
        target_kind="proposal",
    )

    assert isinstance(result, PlanShowMiss)


def test_omitted_target_with_zero_pending_is_a_reasoned_miss(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)

    result = _resolve(
        None,
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowMiss)
    assert result.reason is not None
    assert "no pending plan proposals" in result.reason


def test_omitted_target_with_one_pending_resolves(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    plan_path = plans_root / "202608" / "proposed.md"
    _write_plan(plan_path)
    _append_plan_notification("abcdef120001", plan_path)

    result = _resolve(
        None,
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "proposal"
    assert result.target.raw is None
    assert result.proposal is not None
    assert result.proposal.id_prefix == "abcdef12"


def test_omitted_target_with_several_pending_is_a_reasoned_miss(
    tmp_path: Path,
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    first = plans_root / "202608" / "first.md"
    second = plans_root / "202608" / "second.md"
    _write_plan(first)
    _write_plan(second)
    _append_plan_notification("abcdef120001", first)
    _append_plan_notification("12345670002", second)

    result = _resolve(
        None,
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowMiss)
    assert result.reason is not None
    assert "multiple pending plan proposals" in result.reason


# --- name rung -------------------------------------------------------------


def test_rung_name_matches_bare_slug(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "unique_name.md")

    result = _resolve(
        "unique_name",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "name"


@pytest.mark.parametrize(
    "raw", ["202608/unique_name", "202608/unique_name.md", "plans:202608/unique_name"]
)
def test_rung_name_matches_shard_slug_with_and_without_suffix(
    tmp_path: Path, raw: str
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "unique_name.md")

    # Forced: some of these forms are also legal ``ref`` inputs, and ``ref``
    # is tried before ``name`` in the auto ladder. This test is specifically
    # about the ``name`` rung's own normalization.
    result = _resolve(
        raw,
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
        target_kind="name",
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "name"


def test_rung_name_ambiguous_across_repo_and_local(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "dup.md")
    _write_plan(local_root / "202608" / "dup.md")

    result = _resolve(
        "dup",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowAmbiguity)
    assert len(result.candidates) == 2


def test_miss_carries_close_match_suggestions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "unique_name.md")
    # A non-path-shaped miss falls all the way to the ``bead`` rung; stub it
    # so this test never touches the real repo's bead store.
    _use_bead_view(monkeypatch, {})

    result = _resolve(
        "uniqe_name",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowMiss)
    assert result.suggestions
    assert "plan:202608/unique_name.md" in result.suggestions


# --- bead rung -------------------------------------------------------------


def test_rung_bead_resolves_via_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "a.md")
    _use_bead_view(
        monkeypatch,
        {"sase-64": Issue(id="sase-64", title="T", design="plans:202608/a.md")},
    )

    result = _resolve(
        "sase-64",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
    )

    assert isinstance(result, PlanShowRecord)
    assert result.target.kind == "bead"
    assert result.bead == "sase-64"


def test_rung_bead_declines_without_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _use_bead_view(monkeypatch, {"sase-64": Issue(id="sase-64", title="T", design="")})

    result = _resolve(
        "sase-64",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
        target_kind="bead",
    )

    assert isinstance(result, PlanShowMiss)


def test_rung_bead_skips_path_shaped_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("get_read_view should not be called")

    monkeypatch.setattr("sase.plan_show.resolve.get_read_view", _fail)

    result = _resolve(
        "some/path.md",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
        target_kind="bead",
    )

    assert isinstance(result, PlanShowMiss)


# --- forced target has no fallthrough ---------------------------------


def test_forced_target_kind_misses_without_fallthrough(tmp_path: Path) -> None:
    sdd_root, plans_root, local_root = _roots(tmp_path)
    _write_plan(plans_root / "202608" / "unique_name.md")

    result = _resolve(
        "unique_name",
        sdd_root=sdd_root,
        plans_root=plans_root,
        local_root=local_root,
        cwd=tmp_path,
        target_kind="path",
    )

    assert isinstance(result, PlanShowMiss)
