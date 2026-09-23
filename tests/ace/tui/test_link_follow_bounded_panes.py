"""Bounded-pane reveals: Stitch windows, plan paths, and Patch stacks end to end."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from sase.ace.query_profile import compile_query_profile
from sase.ace.query_profile.profiles._provider import provider_query_schema
from sase.ace.testing import AcePage
from sase.ace.testing.fixtures import make_patch
from sase.ace.tui.actions.link_follow import _link_follow_outcomes
import sase.ace.tui.widgets.artifacts.commits as commits_module
import sase.ace.tui.widgets.artifacts.plans_pane as plans_pane_module
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.artifacts.commits_timeline import commit_row_target
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryTarget,
    HydrationOutcome,
)
from sase.ace.tui.widgets.artifacts.panes import ArtifactsPatchesPane
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_list import plan_row_target
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.ace.tui.widgets.artifacts.view import CommitsPane
from sase.core.query_profile_corpus_facade import (
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.plan_search.filter_query import parse_plan_filter_query
from sase.vcs_log._render_util import to_local
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot
from tests.ace.tui._commits_pane_helpers import _result, _result_with_sidecar

OLD_SHA = "d" * 40
OLD_SHORT = "ddddddd"
REPO = "alpha-platform-repository"


def _old_commit(timestamp: int) -> AggregatedCommitWire:
    return AggregatedCommitWire(
        REPO,
        VcsCommitWire(
            full_id=OLD_SHA,
            short_id=OLD_SHORT,
            author_name="Old Author",
            author_email="old@example.com",
            timestamp=timestamp,
            subject="feat(ancient): a commit older than the default window",
            body="",
            presence="local_only",
            origin="manual",
        ),
    )


def _window_collector(
    recent: VcsLogResult,
    full: VcsLogResult,
    old_timestamp: int,
) -> Any:
    """Collect the windowed recent set until a query covers the old commit."""

    def collect(**kwargs: Any) -> VcsLogResult:
        result = recent
        filter_spec = kwargs.get("filter_spec")
        if filter_spec is not None and old_timestamp > 0:
            now = datetime.now(tz=UTC)
            since = (
                filter_spec.since.resolve(now=now, boundary="since")
                if filter_spec.since is not None
                else None
            )
            until = (
                filter_spec.until.resolve(now=now, boundary="until")
                if filter_spec.until is not None
                else None
            )
            if (
                since is not None
                and until is not None
                and since <= old_timestamp <= until
            ):
                result = full
        commits = result.commits
        if not kwargs.get("include_sidecars", True):
            commits = tuple(
                entry
                for entry in commits
                if not any(
                    repo.name == entry.repo and repo.kind == "sidecar"
                    for repo in result.repos
                )
            )
        if getattr(filter_spec, "merges", "hide") != "show":
            commits = tuple(entry for entry in commits if not entry.commit.is_merge)
        return replace(result, commits=commits)

    return collect


def _fake_provider(
    monkeypatch: pytest.MonkeyPatch,
    short: str,
    commit: VcsCommitWire,
    *,
    expect_cwd: str | None = None,
) -> None:
    """Serve one commit through the VCS provider seam.

    The checkout may resolve from the pane's displayed result (the
    committed ``expect_cwd``) or from the project's repo inventory, so
    only pins the revision arguments, never the checkout path itself.
    """

    class _FakeProvider:
        def revision_id(self, revision: str, path: str) -> str:
            assert revision == f"{short}^{{commit}}"
            if expect_cwd is not None:
                assert path == expect_cwd
            return commit.full_id

        def log(
            self,
            path: str,
            limit: int,
            *,
            revs: tuple[str, ...],
            merges: str = "hide",
        ) -> list[VcsCommitWire]:
            assert limit == 1
            assert revs == (commit.full_id,)
            assert merges == "show"
            if expect_cwd is not None:
                assert path == expect_cwd
            return [commit]

    monkeypatch.setattr(
        "sase.vcs_provider.get_vcs_provider", lambda _cwd: _FakeProvider()
    )


async def _open_stitches(
    monkeypatch: pytest.MonkeyPatch, collect: Any
) -> tuple[AcePage, CommitsPane]:
    monkeypatch.setattr(commits_module, "run_vcs_log", collect)
    page = AcePage(initial_tab="patches")
    await page.__aenter__()
    await page.press(page.artifacts_digit("stitches"))
    await page.expect_state("artifacts_subtab", "stitches")
    pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
    await page.wait_for(lambda _state: pane.result is not None)
    return page, pane


async def _set_stitches_query(
    page: AcePage, pane: CommitsPane, query: str, *, expect: str | None = None
) -> None:
    bar = pane.query_one(CommitFilterBar)
    bar.post_message(CommitFilterBar.Submitted(query))
    await page.wait_for(lambda _state: pane.host_limit_query() == (expect or query))


async def _follow(page: AcePage, ref: str, target: ArtifactEntryTarget) -> None:
    """Drive one link follow the way the link-chip entry point does.

    The chip layer holds ``_link_trail_guard`` across the follow so pane
    syncs the request performs cannot mistake the follow for user
    navigation and cancel its own transaction.
    """
    app = page.app
    origin = app._current_link_trail_origin()
    app._link_trail_guard = True
    try:
        app._follow_artifacts_target(ref, target, origin)
    finally:
        app._link_trail_guard = False
    await page.wait_for(lambda _state: app._link_follow_transaction is None)


def _commit_day(timestamp: int) -> str:
    return to_local(timestamp).date().isoformat()


async def test_old_stitch_reveals_through_repo_day_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stitch older than ``since:24h`` lands in its repo-and-day window."""
    now = int(datetime.now(tz=UTC).timestamp())
    old_timestamp = now - 10 * 86400
    recent = _result(now)
    full = replace(recent, commits=(*recent.commits, _old_commit(old_timestamp)))
    page, pane = await _open_stitches(
        monkeypatch, _window_collector(recent, full, old_timestamp)
    )
    try:
        await _set_stitches_query(
            page,
            pane,
            "sidecar:false since:24h",
            expect="sidecar:false merges:hide since:24h",
        )
        assert (
            pane.host_query_row_for_target(
                ArtifactEntryTarget("stitches", (REPO, OLD_SHA))
            )
            is None
        )

        old = _old_commit(old_timestamp)
        _fake_provider(monkeypatch, "abc1234", old.commit, expect_cwd="/tmp/alpha")

        await _follow(
            page,
            f"stitch:{REPO}@abc1234",
            ArtifactEntryTarget("stitches", (REPO, "abc1234")),
        )

        app = page.app
        day = _commit_day(old_timestamp)
        target = ArtifactEntryTarget("stitches", (REPO, OLD_SHA))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == (
            f"project:{REPO} repo:{REPO} sidecar:true merges:hide "
            f"since:{day} until:{day}"
        )
        assert _link_follow_outcomes["context"] == 1
        reveal = app._link_reveals["stitches"]
        assert reveal.label == f"{REPO} · {day}"

        app.action_prev_query()
        await page.wait_for(
            lambda _state: (
                pane.host_limit_query() == "sidecar:false merges:hide since:24h"
            )
        )
        assert _link_follow_outcomes["context"] == 1
    finally:
        await page.__aexit__(None, None, None)


async def test_sidecar_stitch_context_carries_sidecar_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sidecar stitch hidden by ``sidecar:false`` reveals with ``sidecar:true``."""
    result = _result_with_sidecar()
    sidecar_entry = next(entry for entry in result.commits if entry.repo == "plans")
    page, pane = await _open_stitches(monkeypatch, _window_collector(result, result, 0))
    try:
        await _set_stitches_query(
            page,
            pane,
            "sidecar:false since:24h",
            expect="sidecar:false merges:hide since:24h",
        )
        target = commit_row_target(sidecar_entry)
        assert pane.selected_entry_target() != target

        _fake_provider(
            monkeypatch,
            "ccc1234",
            sidecar_entry.commit,
            expect_cwd="/tmp/plans",
        )
        from sase.vcs_log.resolve import ResolvedRepos

        def _inventory(**_kwargs: object) -> ResolvedRepos:
            return ResolvedRepos(repos=list(result.repos), warnings=[])

        monkeypatch.setattr("sase.vcs_log.resolve.resolve_log_repos", _inventory)
        assert (
            pane.hydrate_ref("stitch", "plans@ccc1234").outcome
            is HydrationOutcome.FETCHED
        )

        await _follow(
            page,
            "stitch:plans@ccc1234",
            ArtifactEntryTarget("stitches", ("plans", "ccc1234")),
        )

        assert pane.selected_entry_target() == target
        query = pane.host_limit_query()
        assert "repo:plans" in query
        assert "sidecar:true" in query
        assert _link_follow_outcomes["context"] == 1
    finally:
        await page.__aexit__(None, None, None)


async def test_merge_stitch_context_carries_merges_show(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merge hidden by ``merges:hide`` reveals with ``merges:show``."""
    now = int(datetime.now(tz=UTC).timestamp())
    base = _result(now)
    merge_entry = AggregatedCommitWire(
        REPO,
        VcsCommitWire(
            full_id="e" * 40,
            short_id="eee1234",
            author_name="Merge Bot",
            author_email="merge@example.com",
            timestamp=now + 60,
            parent_ids=("a" * 40, "b" * 40),
            subject="Merge pull request #123 from sase-org/merge-support",
            body="Add merge support.",
            presence="synced",
        ),
    )
    result = replace(base, commits=(merge_entry, *base.commits))
    assert merge_entry.commit.is_merge
    page, pane = await _open_stitches(monkeypatch, _window_collector(result, result, 0))
    try:
        target = commit_row_target(merge_entry)
        assert pane.selected_entry_target() != target

        _fake_provider(
            monkeypatch, "eee1234", merge_entry.commit, expect_cwd="/tmp/alpha"
        )

        await _follow(
            page,
            f"stitch:{REPO}@eee1234",
            ArtifactEntryTarget("stitches", (REPO, "eee1234")),
        )

        assert pane.selected_entry_target() == target
        assert "merges:show" in pane.host_limit_query()
        assert _link_follow_outcomes["context"] == 1
    finally:
        await page.__aexit__(None, None, None)


async def _open_plans(
    page: AcePage, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> Any:
    value = replace(_snapshot(tmp_path), archive_truncated=True)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane_module,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )
    await page.press(page.artifacts_digit("ref:plan"))
    pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
    pane.set_project_scope("alpha")
    await page.wait_for(
        lambda _state: pane.snapshot is not None and pane.snapshot.project == "alpha"
    )
    return pane


async def test_archived_plan_reveals_through_path_context_after_scan(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filtered-out archived plan lands via ``path:`` once the scan reports."""
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_plans(page, tmp_path, monkeypatch)
        archive_row = next(row for row in pane._rows.values() if row.kind == "archive")
        target = plan_row_target(archive_row)
        identity = target.parts[2]
        assert "/" in identity

        bar = pane.query_one(PlanFilterBar)
        bar.post_message(PlanFilterBar.Submitted("kind:active"))
        await page.wait_for(lambda _state: pane.host_limit_query() == "kind:active")
        assert pane.selected_entry_target() != target

        await _follow(page, f"plan:{identity}", target)

        app = page.app
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == f"path:{identity}"
        assert _link_follow_outcomes["context"] == 1
        reveal = app._link_reveals["ref:plan"]
        assert reveal.label == f"plan {identity.rsplit('/', 1)[-1]}"


def test_provider_schema_accepts_rendered_path_query() -> None:
    """A research-like provider pane accepts the ``path:`` context this phase renders."""
    profile = compile_query_profile(
        provider_query_schema(
            "research",
            {
                "ref": {
                    "properties": {
                        "status": {"type": "string"},
                        "kind": {"type": "string"},
                    }
                }
            },
        )
    )
    path_field = profile.field("path")
    assert path_field is not None
    assert path_field.exact_match is False

    full_path = "/home/bryan/x/sase--research/reports/2026/deep_topic.md"
    index = compile_artifact_query_index(
        pane_id=profile.pane_id,
        generation=1,
        profile=profile,
        entries=[
            {"stable_id": "target", "fields": {"path": full_path}},
            {"stable_id": "other", "fields": {"path": "/home/bryan/x/notes/todo.md"}},
        ],
    )
    rendered = f"path:{full_path}"
    values = parse_plan_filter_query(rendered)
    assert values.paths == (full_path,)
    assert evaluate_artifact_query_many(rendered, index).matched_row_ids == ("target",)


async def test_filtered_patch_reveals_its_stack() -> None:
    """A Patch hidden by a text query lands with its whole stack shown."""
    patches = [
        make_patch(
            name="stack-root",
            description="stack root",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="stack-mid",
            description="stack middle",
            status="Ready",
            parent="stack-root",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="stack-leaf",
            description="stack leaf",
            status="Ready",
            parent="stack-mid",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="unrelated",
            description="something else entirely",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
    ]
    async with AcePage(initial_tab="patches", patches=patches) as page:
        app = page.app
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        leaf = next(item for item in patches if item.name == "stack-leaf")
        target = patch_row_target(leaf)

        app._commit_patch_query("unrelated")
        assert [item.name for item in app.patches] == ["unrelated"]
        assert pane.selected_entry_target() != target

        await _follow(page, "patch:stack-leaf", target)

        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "ancestor:stack-root"
        assert _link_follow_outcomes["context"] == 1
        reveal = app._link_reveals["patches"]
        assert reveal.label == "stack stack-root"


async def test_terminal_patch_reveals_by_name_lifting_hide_toggles() -> None:
    """A Reverted Patch hidden by the hide toggles lands via ``name:``."""
    patches = [
        make_patch(
            name="old-thing",
            description="long reverted work",
            status="Reverted",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="fresh-thing",
            description="current work",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
    ]
    async with AcePage(initial_tab="patches", patches=patches) as page:
        app = page.app
        assert app.hide_reverted is True
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        app._commit_patch_query("")
        assert [item.name for item in app.patches] == ["fresh-thing"]
        old = patches[0]
        target = patch_row_target(old)
        assert pane.selected_entry_target() != target

        await _follow(page, "patch:old-thing", target)

        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "name:old-thing"
        assert _link_follow_outcomes["context"] == 1


async def test_collapsed_patch_group_expands_for_jump() -> None:
    """A Patch inside a collapsed group is revealed without a query change."""
    patches = [
        make_patch(
            name="grouped-a",
            description="first in group",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="grouped-b",
            description="second in group",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
    ]
    async with AcePage(initial_tab="patches", patches=patches) as page:
        app = page.app
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        app._commit_patch_query("")
        assert [item.name for item in app.patches] == ["grouped-a", "grouped-b"]
        before_query = pane.host_limit_query()
        second = patches[1]
        target = patch_row_target(second)

        from sase.ace.tui.models.patch_groups import enumerate_patch_group_keys

        keys = enumerate_patch_group_keys(app.patches)
        assert keys
        assert app._patch_group_fold_registry.collapse_keys(keys) is True
        app._refresh_display()
        assert pane._patch_target_visible_in_list(target) is False

        await _follow(page, "patch:grouped-b", target)

        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == before_query
        assert _link_follow_outcomes["fold"] == 1
