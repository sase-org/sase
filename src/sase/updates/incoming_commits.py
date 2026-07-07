"""Incoming-commit summaries for SASE update surfaces."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.dev_update.models import DevUpdateRootPlan
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.github_source import GH_TIMEOUT_SECONDS
from sase.uv_tool.versions import CorePackageVersion

CommitSource = Literal["git", "github", "unavailable"]

_UNIT_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_LOG_FORMAT = "%h%x1f%s%x1e"
_GIT_TIMEOUT_SECONDS = 5.0
_GITHUB_PAGE_SIZE = 100

RunFn = Callable[..., subprocess.CompletedProcess[str]]
GhFn = Callable[[str], Mapping[str, Any]]
IncomingCommitsCacheKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class CommitSummary:
    """One incoming commit subject."""

    short_sha: str
    subject: str


@dataclass(frozen=True)
class IncomingCommits:
    """A capped incoming-commit preview plus the authoritative total count."""

    total: int
    commits: tuple[CommitSummary, ...]
    source: CommitSource
    error: str | None = None

    @property
    def shown(self) -> int:
        return len(self.commits)

    @property
    def extra(self) -> int:
        return max(0, self.total - self.shown)


@dataclass(frozen=True)
class RepoIncomingCommits:
    """Incoming commits for one repository label in a grouped preview."""

    label: str
    incoming: IncomingCommits


@dataclass(frozen=True)
class CommitSourceSpec:
    """Where to fetch incoming commits for one update candidate."""

    source: Literal["git", "github"]
    repo_full_name: str
    base_ref: str | None = None
    head_ref: str | None = None
    git_root: str | None = None
    current_ref: str = "HEAD"
    upstream_ref: str | None = None

    @property
    def cache_key(self) -> IncomingCommitsCacheKey:
        left = self.git_root or self.repo_full_name
        base = self.current_ref if self.source == "git" else self.base_ref or ""
        head = (
            (self.upstream_ref or "") if self.source == "git" else (self.head_ref or "")
        )
        return (self.source, left, base, head)


def core_package_commit_spec(
    package: CorePackageVersion,
) -> CommitSourceSpec | None:
    """Return an incoming-commit source for an updatable core package."""
    if not package.update_available:
        return None
    repo_full_name = _core_repo_full_name(package)
    if repo_full_name is None:
        return None
    if package.install_type == "editable":
        if package.git_root and package.upstream_ref:
            return CommitSourceSpec(
                source="git",
                repo_full_name=repo_full_name,
                git_root=package.git_root,
                upstream_ref=package.upstream_ref,
            )
        return None
    if not package.installed_version or not package.latest_version:
        return None
    return CommitSourceSpec(
        source="github",
        repo_full_name=repo_full_name,
        base_ref=_release_tag(package.installed_version),
        head_ref=_release_tag(package.latest_version),
    )


def plugin_entry_commit_spec(entry: PluginCatalogEntry) -> CommitSourceSpec | None:
    """Return an incoming-commit source for an updatable plugin."""
    if not entry.update_available:
        return None
    repo_full_name = entry.full_name.strip()
    if not repo_full_name:
        return None
    latest = entry.latest
    if latest.source == "editable":
        if latest.git_root and latest.upstream_ref:
            return CommitSourceSpec(
                source="git",
                repo_full_name=repo_full_name,
                git_root=latest.git_root,
                upstream_ref=latest.upstream_ref,
            )
        return None
    if latest.source != "index":
        return None
    if not entry.installed.version or not latest.version:
        return None
    return CommitSourceSpec(
        source="github",
        repo_full_name=repo_full_name,
        base_ref=_release_tag(entry.installed.version),
        head_ref=_release_tag(latest.version),
    )


def dev_update_root_commit_spec(root: DevUpdateRootPlan) -> CommitSourceSpec | None:
    """Return a local git incoming-commit source for an actionable dev root."""
    if not root.git_root or not root.upstream:
        return None
    label = Path(root.git_root).name or root.git_root
    return CommitSourceSpec(
        source="git",
        repo_full_name=label,
        git_root=root.git_root,
        upstream_ref=root.upstream,
    )


def fetch_incoming_commit_groups(
    specs: Sequence[tuple[str, CommitSourceSpec]],
    *,
    limit: int,
    offline: bool,
    seed: Mapping[IncomingCommitsCacheKey, IncomingCommits],
) -> tuple[RepoIncomingCommits, ...]:
    """Fetch grouped incoming commits, reusing only complete cached previews."""
    groups: list[RepoIncomingCommits] = []
    for label, spec in specs:
        cached = seed.get(spec.cache_key)
        if cached is not None and cached.extra == 0 and cached.source != "unavailable":
            incoming = cached
        else:
            incoming = fetch_incoming_commits(spec, limit=limit, offline=offline)
        groups.append(RepoIncomingCommits(label=label, incoming=incoming))
    return tuple(groups)


def fetch_incoming_commits(
    spec: CommitSourceSpec,
    *,
    limit: int = 7,
    offline: bool = False,
    run_fn: RunFn | None = None,
    gh_fn: GhFn | None = None,
) -> IncomingCommits:
    """Fetch incoming commits for *spec*, returning an unavailable value on failure."""
    limit = max(0, limit)
    try:
        if spec.source == "git":
            return _fetch_git_incoming_commits(spec, limit=limit, run_fn=run_fn)
        if offline:
            return _unavailable("offline mode")
        return _fetch_github_incoming_commits(
            spec,
            limit=limit,
            run_fn=run_fn,
            gh_fn=gh_fn,
        )
    except Exception as exc:  # noqa: BLE001 - update details must never crash UI.
        return _unavailable(_format_error(exc))


def _fetch_git_incoming_commits(
    spec: CommitSourceSpec,
    *,
    limit: int,
    run_fn: RunFn | None,
) -> IncomingCommits:
    if not spec.git_root or not spec.upstream_ref:
        return _unavailable("local git source is incomplete")
    rev_range = f"{spec.current_ref}..{spec.upstream_ref}"
    total_text = _run_git(
        spec.git_root,
        "rev-list",
        "--count",
        rev_range,
        run_fn=run_fn,
    )
    total = int(total_text.strip() or "0")
    commits: tuple[CommitSummary, ...] = ()
    if limit > 0 and total > 0:
        log = _run_git(
            spec.git_root,
            "log",
            f"-n{limit}",
            f"--format={_LOG_FORMAT}",
            rev_range,
            run_fn=run_fn,
        )
        commits = _parse_git_log(log)
    return IncomingCommits(total=total, commits=commits[:limit], source="git")


def _fetch_github_incoming_commits(
    spec: CommitSourceSpec,
    *,
    limit: int,
    run_fn: RunFn | None,
    gh_fn: GhFn | None,
) -> IncomingCommits:
    if not spec.base_ref or not spec.head_ref:
        return _unavailable("GitHub compare source is incomplete")
    api = (
        gh_fn
        if gh_fn is not None
        else lambda endpoint: _gh_api_json(endpoint, run_fn=run_fn)
    )
    endpoint = f"repos/{spec.repo_full_name}/compare/{spec.base_ref}...{spec.head_ref}"
    payload = api(endpoint)
    total = _int(payload.get("total_commits"))
    raw_commits = _commit_items(payload)
    if limit > 0 and total > len(raw_commits):
        page = max(1, math.ceil(total / _GITHUB_PAGE_SIZE))
        pages_to_fetch = max(1, math.ceil(limit / _GITHUB_PAGE_SIZE))
        raw_newest: list[Mapping[str, Any]] = []
        for _ in range(pages_to_fetch):
            if page < 1 or len(raw_newest) >= limit:
                break
            page_payload = api(f"{endpoint}?per_page={_GITHUB_PAGE_SIZE}&page={page}")
            raw_newest.extend(reversed(_commit_items(page_payload)))
            page -= 1
        commits = tuple(_summaries_from_github(raw_newest))[:limit]
    else:
        commits = tuple(reversed(_summaries_from_github(raw_commits)))[:limit]
    return IncomingCommits(total=total, commits=commits, source="github")


def _run_git(
    root: str,
    *args: str,
    run_fn: RunFn | None,
) -> str:
    runner = subprocess.run if run_fn is None else run_fn
    completed = runner(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = _first_nonempty_line(completed.stderr, completed.stdout)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"`git {' '.join(args)}` failed{suffix}")
    return completed.stdout


def _gh_api_json(endpoint: str, *, run_fn: RunFn | None) -> Mapping[str, Any]:
    if shutil.which("gh") is None:
        raise RuntimeError("the GitHub CLI (gh) was not found on PATH")
    runner = subprocess.run if run_fn is None else run_fn
    completed = runner(
        ["gh", "api", "-X", "GET", endpoint],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = _first_nonempty_line(completed.stderr, completed.stdout)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"`gh api` failed (exit {completed.returncode}){suffix}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse `gh api` output as JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("`gh api` returned JSON that was not an object")
    return payload


def _parse_git_log(stdout: str) -> tuple[CommitSummary, ...]:
    commits: list[CommitSummary] = []
    for raw in stdout.split(_RECORD_SEP):
        record = raw.strip("\n")
        if not record:
            continue
        short_sha, sep, subject = record.partition(_UNIT_SEP)
        if not sep:
            continue
        commits.append(CommitSummary(short_sha=short_sha, subject=subject))
    return tuple(commits)


def _summaries_from_github(items: list[Mapping[str, Any]]) -> list[CommitSummary]:
    summaries: list[CommitSummary] = []
    for item in items:
        sha = _str(item.get("sha"))
        if not sha:
            continue
        message = _str(_get(item, "commit", "message"))
        subject = message.splitlines()[0] if message else ""
        summaries.append(CommitSummary(short_sha=sha[:7], subject=subject))
    return summaries


def _commit_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    commits = payload.get("commits")
    if not isinstance(commits, list):
        return []
    return [item for item in commits if isinstance(item, Mapping)]


def _core_repo_full_name(package: CorePackageVersion) -> str | None:
    name = package.name.casefold()
    dist = package.distribution_name.casefold()
    if name == "sase" or dist == "sase":
        return "sase-org/sase"
    if name == "sase-core" or dist == "sase-core-rs":
        return "sase-org/sase-core"
    return None


def _release_tag(version: str) -> str:
    return version if version.startswith("v") else f"v{version}"


def _unavailable(error: str) -> IncomingCommits:
    return IncomingCommits(
        total=0,
        commits=(),
        source="unavailable",
        error=error,
    )


def _format_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"command timed out after {exc.timeout:g}s"
    message = str(exc).strip()
    return message or type(exc).__name__


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _get(item: Mapping[str, Any], *path: str) -> Any:
    value: Any = item
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0


__all__ = [
    "CommitSourceSpec",
    "CommitSummary",
    "IncomingCommits",
    "IncomingCommitsCacheKey",
    "RepoIncomingCommits",
    "core_package_commit_spec",
    "dev_update_root_commit_spec",
    "fetch_incoming_commit_groups",
    "fetch_incoming_commits",
    "plugin_entry_commit_spec",
]
