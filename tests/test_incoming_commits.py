"""Incoming-commit source and renderer tests."""

from __future__ import annotations

import io
import subprocess
from typing import Any

from rich.console import Console

from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.render_common import build_incoming_commits_renderable
from sase.updates.incoming_commits import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    core_package_commit_spec,
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
