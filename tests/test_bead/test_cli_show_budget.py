"""End-to-end structural budget guard for ``sase bead show``.

The ``inventory``, ``parser``, and ``store`` phases each guard their own
mechanism in isolation (git-probe memoization, narrow parser construction,
single-pass store reads). These tests assert the mechanisms compose through a
real ``sase bead show`` dispatch rather than only inside each phase's own
mocks — the combined budget the ``guard`` phase closes the epic on.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.bead.model import Issue, IssueType
from sase.core import bead_read_facade
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.repo_inventory import collect_repo_inventory
from tests.test_bead.cli_show_test_helpers import show


def test_show_full_reduces_the_bead_store_exactly_once(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``bead show`` calls the single-pass detail read once and never
    falls back to the three-read legacy path it replaced."""
    phase = nested_store["phase"]
    calls = {"show_issue_detail": 0, "list_issues": 0, "get_epic_children": 0}

    for name in calls:
        real = getattr(bead_read_facade, name)

        def counting(
            *args: object, _name: str = name, _real: object = real, **kwargs: object
        ) -> object:
            calls[_name] += 1
            return _real(*args, **kwargs)  # type: ignore[operator]

        monkeypatch.setattr(bead_read_facade, name, counting)

    show(phase, capsys)

    assert calls == {"show_issue_detail": 1, "list_issues": 0, "get_epic_children": 0}


def test_show_bounds_repo_inventory_subprocess_calls_for_ref_bearing_bead(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bead with ``refs`` resolves both its creator URL and its artifact
    reference context, each independently reaching ``collect_repo_inventory``.
    Before the ``inventory`` phase this doubled the subprocess storm — the
    measured extra ~1s that made ``sase-cl`` (a ref-bearing bead) slower than
    ``sase-bv``. Memoization must keep the combined cost a single probe.
    """
    primary = tmp_path / "widget"
    primary.mkdir()
    (primary / ".git").mkdir()
    config = {
        "is_sase_managed": True,
        "repos": {"sidecar": [{"name": "plans"}, {"name": "research"}]},
    }
    project_record = ProjectRecordWire(
        schema_version=3,
        project_name="widget",
        project_dir=str(tmp_path / "project"),
        project_file=str(tmp_path / "project" / "widget.sase"),
        archive_file=None,
        workspace_dir=str(primary),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )
    origin_probes: list[tuple[str, ...]] = []

    def run(
        argv: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        origin_probes.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="git@github.com:acme/widget.git\n",
            stderr="",
        )

    monkeypatch.setattr("sase._linked_repo_identity.subprocess.run", run)
    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project_record],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.read_project_local_config",
        lambda _primary: config,
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda _primary, _config: config,
    )

    issue = Issue(
        id="beads-refs-budget",
        title="Refs budget",
        issue_type=IssueType.TASK,
        owner="owner@example.com",
        created_by="bbugyi200.athena.q8--plan",
        refs=["research:202608/report.md"],
    )

    class _View:
        def show(self, issue_id: str) -> Issue:
            if issue_id == issue.id:
                return issue
            raise KeyError(issue_id)

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return [issue]

    @contextmanager
    def read_view() -> Iterator[_View]:
        yield _View()

    monkeypatch.setattr("sase.bead.cli_query.get_read_view", read_view)
    monkeypatch.setattr("sase.bead.cli_query.design_paths_are_relative", lambda: False)
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)
    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _cwd: (primary, 0),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store",
        lambda _workspace_dir, _workspace_num: object(),
    )

    class _Resolver:
        def agent_url(self, _agent_name: str) -> None:
            collect_repo_inventory(project="widget")
            return None

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda _store, *, primary_root: _Resolver(),
    )
    monkeypatch.setattr(
        "sase.bead.cli_query.artifact_reference_context",
        lambda: collect_repo_inventory(project="widget") and None,
    )

    show(issue, capsys)

    probe_count = origin_probes.count(("git", "remote", "get-url", "origin"))
    assert 1 <= probe_count <= 2
