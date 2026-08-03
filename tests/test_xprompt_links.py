"""Tests for hosted URL resolution of xprompt definition provenance."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._store_types import SddStore
from sase.sdd.hosted_links import HostedLinkResolver
from sase.xprompt_links import (
    XpromptSourceRecord,
    XpromptTargetResolver,
)

_GITHUB_PRIMARY_REMOTE = "git@github.com:sase-org/sase.git"
_GITHUB_CHEZMOI_REMOTE = "git@github.com:bryanbugyi34/dotfiles.git"
_GITLAB_REMOTE = "git@gitlab.example.com:someone/somewhere.git"


class _FakeGit:
    """Deterministic git boundary recording every invocation."""

    def __init__(
        self,
        *,
        remotes: dict[Path, str] | None = None,
        heads: dict[Path, str] | None = None,
    ) -> None:
        self.remotes = remotes or {}
        self.heads = heads or {}
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def __call__(
        self,
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        self.calls.append((Path(cwd), tuple(args)))
        if args[:2] == ["remote", "get-url"]:
            remote = self.remotes.get(Path(cwd))
            if remote:
                return subprocess.CompletedProcess(args, 0, f"{remote}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "")
        if args == ["rev-parse", "HEAD"]:
            sha = self.heads.get(Path(cwd))
            if sha:
                return subprocess.CompletedProcess(args, 0, f"{sha}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "fatal: not a repository")
        raise AssertionError(args)


def _store(root: Path) -> SddStore:
    return SddStore("in_tree", root, root)


def _hosted(
    primary_root: Path,
    git_runner: _FakeGit,
) -> HostedLinkResolver:
    return HostedLinkResolver(
        _store(primary_root),
        primary_root=primary_root,
        git_runner=git_runner,
    )


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    return root


def _record(
    *,
    repo: str | None,
    repo_root: str | None,
    repo_relpath: str | None,
    definition_line: int | None = None,
    chezmoi: bool = False,
) -> XpromptSourceRecord:
    return {
        "schema_version": 1,
        "raw_ref": "#plan",
        "name": "plan",
        "kind": "part",
        "source_kind": "markdown",
        "source_path": None,
        "definition_line": definition_line,
        "repo": repo,
        "repo_root": repo_root,
        "repo_relpath": repo_relpath,
        "chezmoi": chezmoi,
        "skipped_reason": None,
    }


def test_resolves_line_anchor_against_github_primary_repo(tmp_path: Path) -> None:
    primary = _repo(tmp_path, "sase")
    git = _FakeGit(remotes={primary: _GITHUB_PRIMARY_REMOTE})
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary},
    )
    record = _record(
        repo="sase",
        repo_root=str(primary),
        repo_relpath="src/sase/default_config.yml",
        definition_line=42,
    )

    url = resolver(record)

    assert url == (
        f"https://github.com/sase-org/sase/blob/{'a' * 40}/"
        "src/sase/default_config.yml#L42"
    )


def test_resolves_markdown_definition_without_line_anchor(tmp_path: Path) -> None:
    primary = _repo(tmp_path, "sase")
    git = _FakeGit(remotes={primary: _GITHUB_PRIMARY_REMOTE})
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary},
    )
    record = _record(
        repo="sase",
        repo_root=str(primary),
        repo_relpath="sase/xprompts/deploy.md",
        definition_line=None,
    )

    url = resolver(record)

    assert url == (
        f"https://github.com/sase-org/sase/blob/{'a' * 40}/sase/xprompts/deploy.md"
    )
    assert "#L" not in (url or "")


def test_chezmoi_repo_with_github_origin_resolves_against_recorded_root(
    tmp_path: Path,
) -> None:
    primary = _repo(tmp_path, "sase")
    chezmoi_root = _repo(tmp_path, "chezmoi")
    git = _FakeGit(
        remotes={primary: _GITHUB_PRIMARY_REMOTE, chezmoi_root: _GITHUB_CHEZMOI_REMOTE},
        heads={chezmoi_root: "f" * 40},
    )
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary, "chezmoi": chezmoi_root},
    )
    record = _record(
        repo="chezmoi",
        repo_root=str(chezmoi_root),
        repo_relpath="home/dot_config/sase/sase.yml",
        definition_line=1029,
        chezmoi=True,
    )

    url = resolver(record)

    assert url == (
        "https://github.com/bryanbugyi34/dotfiles/blob/"
        f"{'f' * 40}/home/dot_config/sase/sase.yml#L1029"
    )


def test_non_github_remote_yields_no_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.config as config_module

    monkeypatch.setattr(config_module, "load_merged_config", lambda: {})
    primary = _repo(tmp_path, "sase")
    other = _repo(tmp_path, "other")
    git = _FakeGit(
        remotes={primary: _GITHUB_PRIMARY_REMOTE, other: _GITLAB_REMOTE},
        heads={other: "b" * 40},
    )
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary, "other": other},
    )
    record = _record(repo="other", repo_root=str(other), repo_relpath="README.md")

    assert resolver(record) is None


def test_unresolvable_head_yields_no_link(tmp_path: Path) -> None:
    primary = _repo(tmp_path, "sase")
    other = _repo(tmp_path, "other")
    git = _FakeGit(
        remotes={primary: _GITHUB_PRIMARY_REMOTE, other: _GITHUB_CHEZMOI_REMOTE}
    )
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary, "other": other},
    )
    record = _record(repo="other", repo_root=str(other), repo_relpath="README.md")

    assert resolver(record) is None


def test_record_with_no_repository_is_skipped(tmp_path: Path) -> None:
    primary = _repo(tmp_path, "sase")
    git = _FakeGit(remotes={primary: _GITHUB_PRIMARY_REMOTE})
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary},
    )
    record = _record(repo=None, repo_root=None, repo_relpath=None)

    assert resolver(record) is None


def test_disappeared_recorded_root_falls_back_to_inventory_root(
    tmp_path: Path,
) -> None:
    primary = _repo(tmp_path, "sase")
    live_root = _repo(tmp_path, "chezmoi-live")
    git = _FakeGit(
        remotes={primary: _GITHUB_PRIMARY_REMOTE, live_root: _GITHUB_CHEZMOI_REMOTE},
        heads={live_root: "c" * 40},
    )
    resolver = XpromptTargetResolver(
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_hosted(primary, git),
        git_runner=git,
        repository_roots={"sase": primary, "chezmoi": live_root},
    )
    vanished_root = tmp_path / "workspace-that-no-longer-exists" / "chezmoi"
    record = _record(
        repo="chezmoi",
        repo_root=str(vanished_root),
        repo_relpath="home/dot_config/sase/sase.yml",
        chezmoi=True,
    )

    url = resolver(record)

    assert url == (
        "https://github.com/bryanbugyi34/dotfiles/blob/"
        f"{'c' * 40}/home/dot_config/sase/sase.yml"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
