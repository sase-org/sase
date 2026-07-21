"""Incoming-commit source and renderer tests."""

from __future__ import annotations

import io
import subprocess
from typing import Any

from rich.console import Console

from sase.dev_update.models import DevUpdateRootPlan
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.render_common import build_incoming_commits_renderable
from sase.updates import OutdatedComponent
from sase.updates.incoming_commits import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    allocate_commit_budget,
    component_commit_spec,
    core_package_commit_spec,
    dev_update_root_commit_spec,
    fetch_incoming_commit_groups,
    fetch_incoming_commits,
    plugin_entry_commit_spec,
)
from sase.uv_tool.versions import CorePackageVersion


def _render(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=120, no_color=True)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined]


def _plugin_entry(latest: LatestInfo) -> PluginCatalogEntry:
    return PluginCatalogEntry(
        name="github",
        repo="sase-github",
        full_name="sase-org/sase-github",
        owner="sase-org",
        description="",
        url="https://github.com/sase-org/sase-github",
        homepage="",
        topics=(),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="",
        installed=InstalledInfo(installed=True, version="1.2.0"),
        latest=latest,
    )


def test_github_compare_uses_true_total_and_newest_first() -> None:
    payload = {
        "total_commits": 9,
        "commits": [
            {
                "sha": f"{idx:040x}",
                "commit": {"message": f"commit {idx}\n\nbody"},
            }
            for idx in range(1, 10)
        ],
    }
    spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/sase",
        base_ref="v0.5.0",
        head_ref="v0.6.0",
    )

    incoming = fetch_incoming_commits(spec, gh_fn=lambda _endpoint: payload, limit=7)

    assert incoming.total == 9
    assert incoming.extra == 2
    assert incoming.source == "github"
    assert [commit.subject for commit in incoming.commits] == [
        "commit 9",
        "commit 8",
        "commit 7",
        "commit 6",
        "commit 5",
        "commit 4",
        "commit 3",
    ]


def test_github_compare_fetches_last_page_when_compare_array_is_truncated() -> None:
    calls: list[str] = []

    def gh(endpoint: str) -> dict[str, Any]:
        calls.append(endpoint)
        if "per_page=100&page=3" in endpoint:
            return {
                "total_commits": 251,
                "commits": [
                    {"sha": f"{idx:040x}", "commit": {"message": f"commit {idx}"}}
                    for idx in range(201, 252)
                ],
            }
        return {
            "total_commits": 251,
            "commits": [
                {"sha": f"{idx:040x}", "commit": {"message": f"commit {idx}"}}
                for idx in range(1, 251)
            ],
        }

    spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/sase",
        base_ref="v0.5.0",
        head_ref="v0.6.0",
    )

    incoming = fetch_incoming_commits(spec, gh_fn=gh, limit=7)

    assert len(calls) == 2
    assert incoming.total == 251
    assert [commit.subject for commit in incoming.commits[:2]] == [
        "commit 251",
        "commit 250",
    ]


def test_github_compare_walks_tail_pages_for_larger_limits() -> None:
    calls: list[str] = []

    def gh(endpoint: str) -> dict[str, Any]:
        calls.append(endpoint)
        if "per_page=100&page=3" in endpoint:
            start, stop = 201, 251
        elif "per_page=100&page=2" in endpoint:
            start, stop = 101, 200
        else:
            start, stop = 1, 250
        return {
            "total_commits": 251,
            "commits": [
                {"sha": f"{idx:040x}", "commit": {"message": f"commit {idx}"}}
                for idx in range(start, stop + 1)
            ],
        }

    spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/sase",
        base_ref="v0.5.0",
        head_ref="v0.6.0",
    )

    incoming = fetch_incoming_commits(spec, gh_fn=gh, limit=150)

    assert calls == [
        "repos/sase-org/sase/compare/v0.5.0...v0.6.0",
        "repos/sase-org/sase/compare/v0.5.0...v0.6.0?per_page=100&page=3",
        "repos/sase-org/sase/compare/v0.5.0...v0.6.0?per_page=100&page=2",
    ]
    assert incoming.total == 251
    assert len(incoming.commits) == 150
    assert incoming.commits[0].subject == "commit 251"
    assert incoming.commits[-1].subject == "commit 102"


def test_git_source_uses_rev_list_total_and_delimited_log_subjects() -> None:
    commands: list[tuple[str, ...]] = []

    def run(
        argv: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        args = tuple(argv[3:])
        commands.append(args)
        if args == ("rev-list", "--count", "HEAD..origin/main"):
            return subprocess.CompletedProcess(argv, 0, stdout="9\n", stderr="")
        if args == (
            "log",
            "-n7",
            "--format=%h%x1f%s%x1e",
            "HEAD..origin/main",
        ):
            stdout = "abc1234\x1fNewest subject\x1edef5678\x1fOlder subject\x1e"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")

    spec = CommitSourceSpec(
        source="git",
        repo_full_name="sase-org/sase-github",
        git_root="/repo/sase-github",
        upstream_ref="origin/main",
    )

    incoming = fetch_incoming_commits(spec, run_fn=run, limit=7)

    assert commands[0] == ("rev-list", "--count", "HEAD..origin/main")
    assert incoming.total == 9
    assert incoming.extra == 7
    assert incoming.commits == (
        CommitSummary("abc1234", "Newest subject"),
        CommitSummary("def5678", "Older subject"),
    )


def test_allocate_commit_budget_water_fills_global_budget() -> None:
    assert allocate_commit_budget([20], 20) == [20]
    assert allocate_commit_budget([20, 20], 20) == [10, 10]
    assert allocate_commit_budget([3, 2, 30], 20) == [3, 2, 15]
    assert allocate_commit_budget([3, 2, 4], 20) == [3, 2, 4]
    assert allocate_commit_budget([5, 5, 5], 2) == [1, 1, 0]
    assert allocate_commit_budget([0, -1, 4], 3) == [0, 0, 3]
    assert allocate_commit_budget([4, 4], 0) == [0, 0]


def test_source_specs_map_core_and_plugins() -> None:
    core = CorePackageVersion(
        name="sase-core",
        distribution_name="sase-core-rs",
        installed_version="0.2.0",
        latest_version="0.3.0",
        latest_checked=True,
        update_available=True,
    )
    core_spec = core_package_commit_spec(core)
    assert core_spec is not None
    assert core_spec.repo_full_name == "sase-org/sase-core"
    assert core_spec.base_ref == "v0.2.0"
    assert core_spec.head_ref == "v0.3.0"

    plugin = _plugin_entry(LatestInfo(checked=True, version="1.3.0", source="index"))
    plugin_spec = plugin_entry_commit_spec(plugin)
    assert plugin_spec is not None
    assert plugin_spec.repo_full_name == "sase-org/sase-github"
    assert plugin_spec.base_ref == "v1.2.0"
    assert plugin_spec.head_ref == "v1.3.0"

    editable = _plugin_entry(
        LatestInfo(
            checked=True,
            version="1.2.0+2.gdef5678",
            source="editable",
            update_available=True,
            git_root="/repo/sase-github",
            upstream_ref="origin/main",
        )
    )
    editable_spec = plugin_entry_commit_spec(editable)
    assert editable_spec is not None
    assert editable_spec.source == "git"
    assert editable_spec.git_root == "/repo/sase-github"
    assert editable_spec.upstream_ref == "origin/main"


def test_component_commit_spec_maps_cached_components() -> None:
    editable = OutdatedComponent(
        display_name="github",
        role="plugin",
        installed_version="1.2.0+1.gabc1234",
        latest_version="1.2.0+3.gdef5678",
        distribution_name="sase-github",
        install_type="editable",
        source_root="/repo/sase-github",
        upstream_ref="origin/main",
    )
    editable_spec = component_commit_spec(editable)
    assert editable_spec is not None
    assert editable_spec.source == "git"
    assert editable_spec.repo_full_name == "github"
    assert editable_spec.git_root == "/repo/sase-github"
    assert editable_spec.upstream_ref == "origin/main"

    host = OutdatedComponent(
        display_name="sase",
        role="host",
        installed_version="0.5.0",
        latest_version="0.6.0",
        distribution_name="sase",
    )
    host_spec = component_commit_spec(host)
    assert host_spec is not None
    assert host_spec.source == "github"
    assert host_spec.repo_full_name == "sase-org/sase"
    assert host_spec.base_ref == "v0.5.0"
    assert host_spec.head_ref == "v0.6.0"

    core = OutdatedComponent(
        display_name="sase-core",
        role="core",
        installed_version="v0.4.0",
        latest_version="v0.4.1",
        distribution_name="sase-core-rs",
    )
    core_spec = component_commit_spec(core)
    assert core_spec is not None
    assert core_spec.source == "github"
    assert core_spec.repo_full_name == "sase-org/sase-core"
    assert core_spec.base_ref == "v0.4.0"
    assert core_spec.head_ref == "v0.4.1"

    plugin = OutdatedComponent(
        display_name="telegram",
        role="plugin",
        installed_version="0.1.0",
        latest_version="0.2.0",
        distribution_name="sase-telegram",
    )
    assert component_commit_spec(plugin) is None


def test_dev_update_root_commit_spec() -> None:
    root = DevUpdateRootPlan(
        git_root="/repo/sase-github",
        status="actionable",
        reason="behind upstream by 2 commit(s)",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        packages=("sase-github",),
        behind=2,
    )

    spec = dev_update_root_commit_spec(root)

    assert spec is not None
    assert spec.source == "git"
    assert spec.repo_full_name == "sase-github"
    assert spec.git_root == "/repo/sase-github"
    assert spec.upstream_ref == "origin/main"
    assert (
        dev_update_root_commit_spec(
            DevUpdateRootPlan(
                git_root="/repo/sase-github",
                status="actionable",
                reason="no upstream",
                upstream=None,
                remote=None,
                remote_branch=None,
                packages=("sase-github",),
            )
        )
        is None
    )


def test_fetch_failures_degrade_to_unavailable() -> None:
    spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/sase",
        base_ref="v0.5.0",
        head_ref="v0.6.0",
    )

    incoming = fetch_incoming_commits(
        spec,
        gh_fn=lambda _endpoint: (_ for _ in ()).throw(RuntimeError("404")),
    )

    assert incoming.source == "unavailable"
    assert incoming.error == "404"


def test_github_incoming_commits_offline_does_not_call_github() -> None:
    spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/sase",
        base_ref="v0.5.0",
        head_ref="v0.6.0",
    )

    incoming = fetch_incoming_commits(
        spec,
        offline=True,
        gh_fn=lambda _endpoint: (_ for _ in ()).throw(
            AssertionError("GitHub must not be called offline")
        ),
    )

    assert incoming.source == "unavailable"
    assert incoming.error == "offline mode"


def test_fetch_incoming_commit_groups_reuses_only_complete_seed(
    monkeypatch: Any,
) -> None:
    complete_spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/complete",
        base_ref="v1.0.0",
        head_ref="v1.0.1",
    )
    partial_spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/partial",
        base_ref="v1.0.0",
        head_ref="v1.0.1",
    )
    unavailable_spec = CommitSourceSpec(
        source="github",
        repo_full_name="sase-org/unavailable",
        base_ref="v1.0.0",
        head_ref="v1.0.1",
    )
    fetched: list[str] = []

    def fake_fetch(
        spec: CommitSourceSpec, *, limit: int, offline: bool
    ) -> IncomingCommits:
        fetched.append(spec.repo_full_name)
        return IncomingCommits(
            total=limit,
            commits=(CommitSummary("fff0000", f"fetched {spec.repo_full_name}"),),
            source="github",
        )

    monkeypatch.setattr(
        "sase.updates.incoming_commits.fetch_incoming_commits",
        fake_fetch,
    )
    complete = IncomingCommits(
        total=1,
        commits=(CommitSummary("abc1234", "cached complete"),),
        source="github",
    )
    seed = {
        complete_spec.cache_key: complete,
        partial_spec.cache_key: IncomingCommits(
            total=3,
            commits=(CommitSummary("def5678", "cached partial"),),
            source="github",
        ),
        unavailable_spec.cache_key: IncomingCommits(
            total=0,
            commits=(),
            source="unavailable",
            error="offline",
        ),
    }

    groups = fetch_incoming_commit_groups(
        (
            ("complete", complete_spec),
            ("partial", partial_spec),
            ("unavailable", unavailable_spec),
        ),
        limit=7,
        offline=False,
        seed=seed,
    )

    assert fetched == ["sase-org/partial", "sase-org/unavailable"]
    assert groups[0].incoming is complete
    assert groups[1].incoming.commits[0].subject == "fetched sase-org/partial"
    assert groups[2].incoming.commits[0].subject == "fetched sase-org/unavailable"


def test_incoming_commits_renderer_states() -> None:
    incoming = IncomingCommits(
        total=3,
        commits=(
            CommitSummary("abc1234", "Newest"),
            CommitSummary("def5678", "Older"),
        ),
        source="github",
    )

    text = _render(build_incoming_commits_renderable(incoming))

    assert "↑ 3 incoming commits" in text
    assert "abc1234  Newest" in text
    assert "+1 more" in text
    assert "checking incoming commits" in _render(
        build_incoming_commits_renderable(loading=True)
    )
    assert "incoming commits unavailable (offline)" in _render(
        build_incoming_commits_renderable(
            IncomingCommits(0, (), "unavailable", error="offline")
        )
    )
    labeled = _render(build_incoming_commits_renderable(incoming, label="sase"))
    assert "↑ sase — 3 incoming commits" in labeled
    assert "sase: incoming commits unavailable (offline)" in _render(
        build_incoming_commits_renderable(
            IncomingCommits(0, (), "unavailable", error="offline"),
            label="sase",
        )
    )
