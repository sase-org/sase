"""Backend coverage for the Artifacts Bugs pane."""

from pathlib import Path

import pluggy
import pytest

from sase.ace.testing import make_patch
from sase.ace.tui.artifacts_bugs import (
    _BugScope,
    collect_bug_snapshot,
    create_project_issue,
    update_project_issue,
)
from sase.bead.model import BeadTier, Issue, IssueType
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.vcs_provider import IssueWire
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.testing import FakeIssueProvider


def _provider(*plugins: object) -> VCSPluginManager:
    manager = pluggy.PluginManager("sase_vcs")
    manager.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        manager.register(plugin)
    return VCSPluginManager(manager)


def _record() -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name="alpha",
        project_dir="/state/projects/alpha",
        project_file="/state/projects/alpha/alpha.sase",
        archive_file=None,
        workspace_dir="/repos/alpha",
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=["a"],
        display_name="Alpha Project",
    )


def test_snapshot_collects_provider_issues_and_local_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = IssueWire(
        number=42,
        title="Fix the cache",
        state="open",
        body="Cache entries can become stale.",
        labels=("bug",),
        updated_at="2026-07-15T10:00:00Z",
        url="https://example.test/issues/42",
    )
    provider = _provider(FakeIssueProvider([issue]))
    epic = Issue(
        id="sase-42",
        title="Cache repair",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    epic.patch_name = "cache_fix"
    epic.patch_bug_id = "42"
    task = Issue(
        id="alpha-task",
        title="Cache task",
        issue_type=IssueType.TASK,
        external_ref="bug:alpha#42",
    )
    patch = make_patch(name="cache_fix")
    patch.bug = "#42"

    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_a, **_kw: [_record()],
    )
    monkeypatch.setattr("sase.vcs_provider.get_vcs_provider", lambda _cwd: provider)
    monkeypatch.setattr(
        "sase.bead.workspace.get_project_beads_dirs_for_project",
        lambda project: [Path(f"/{project}/beads")],
    )
    monkeypatch.setattr(
        "sase.core.bead_read_facade.list_issues", lambda _path: [epic, task]
    )

    snapshot = collect_bug_snapshot("a", "open", [patch])

    assert snapshot.project_key == "alpha"
    assert snapshot.display_name == "Alpha Project"
    assert snapshot.issues == (issue,)
    assert snapshot.links_for(42).epics == (epic,)
    assert snapshot.links_for(42).beads == (task,)
    assert snapshot.links_for(42).patches == (patch,)


def test_snapshot_capability_gate_does_not_call_remote_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_a, **_kw: [_record()],
    )
    monkeypatch.setattr("sase.vcs_provider.get_vcs_provider", lambda _cwd: _provider())

    snapshot = collect_bug_snapshot("alpha", "open", [])

    assert snapshot.supported is False
    assert snapshot.issues == ()
    assert snapshot.error == ""


def test_create_and_update_use_fake_provider_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(FakeIssueProvider())
    scope = _BugScope(
        project_key="alpha",
        display_name="Alpha",
        project_file="/state/alpha.sase",
        cwd="/repos/alpha",
        provider=provider,
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifacts_bugs._resolve_bug_scope", lambda _project: scope
    )

    created = create_project_issue(
        "alpha", title="New issue", body="Body", labels=("bug",)
    )
    updated = update_project_issue("alpha", created.number, state="closed")

    assert created.number == 1
    assert created.labels == ("bug",)
    assert updated.state == "closed"


def test_snapshot_resolves_display_name_scope_for_local_bead_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A #gh project scoped by display name still keeps its local bead links."""
    issue = IssueWire(
        number=7,
        title="Cache thrash",
        state="open",
        body="Body",
        labels=("bug",),
        updated_at="2026-07-15T10:00:00Z",
        url="https://example.test/issues/7",
    )
    provider = _provider(FakeIssueProvider([issue]))
    epic = Issue(
        id="widget-1",
        title="Widget epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    epic.patch_bug_id = "7"
    record = ProjectRecordWire(
        schema_version=3,
        project_name="gh_acme__widget",
        project_dir="/state/projects/gh_acme__widget",
        project_file="/state/projects/gh_acme__widget/gh_acme__widget.sase",
        archive_file=None,
        workspace_dir="/repos/widget",
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        display_name="widget",
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_a, **_kw: [record],
    )
    monkeypatch.setattr("sase.vcs_provider.get_vcs_provider", lambda _cwd: provider)

    beads_dirs_calls: list[str] = []

    def get_beads_dirs(project: str) -> list[Path] | None:
        beads_dirs_calls.append(project)
        return [Path(f"/{project}/beads")] if project == "gh_acme__widget" else None

    monkeypatch.setattr(
        "sase.bead.workspace.get_project_beads_dirs_for_project",
        get_beads_dirs,
    )
    monkeypatch.setattr("sase.core.bead_read_facade.list_issues", lambda _path: [epic])

    snapshot = collect_bug_snapshot("widget", "open", [])

    assert snapshot.project_key == "gh_acme__widget"
    assert beads_dirs_calls == ["gh_acme__widget"]
    assert snapshot.links_for(7).epics == (epic,)
