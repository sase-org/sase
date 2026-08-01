"""Policy for automatic artifact-file capture.

The policy deliberately returns decisions instead of writing artifact records.
Callers can therefore apply the same authorship and durability rules before
either copying bytes or recording a VCS-backed reference.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
from typing import Literal, Protocol

from sase.repo_inventory import collect_repo_inventory


_CaptureOrigin = Literal["changed", "mentioned"]
_CaptureOutcome = Literal["store", "reference", "skip"]


@dataclass(frozen=True)
class CaptureCandidate:
    """One file considered for automatic artifact capture."""

    path: str
    origin: _CaptureOrigin
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class CaptureDecision:
    """The byte-storage decision and optional durable VCS provenance."""

    outcome: _CaptureOutcome
    reason: str
    vcs_repo: str | None = None
    vcs_sha: str | None = None
    vcs_relpath: str | None = None


@dataclass(frozen=True)
class CaptureLimits:
    """Per-run bounds used while deciding automatic captures."""

    max_stored_per_agent: int
    max_history_scan: int


class VcsProbe(Protocol):
    """Read-only VCS operations needed by the capture policy."""

    def repo_toplevel(self, path: str) -> str | None:
        """Return the repository toplevel containing *path*, when present."""

    def repo_identity(
        self,
        toplevel: str,
        *,
        project: str,
        workspace_num: int,
    ) -> str | None:
        """Return the inventory identity for *toplevel*, when known."""

    def durable_candidate_commits(
        self,
        toplevel: str,
        relpath: str,
        *,
        max_history_scan: int,
    ) -> tuple[str, ...] | None:
        """Return bounded commits from durable refs, or ``None`` on failure."""

    def blob_content_digests(
        self,
        toplevel: str,
        specs: Sequence[str],
    ) -> Mapping[str, str | None] | None:
        """Return SHA-256 digests for ``<commit>:<path>`` blob specs."""


@dataclass
class _CandidateContext:
    candidate: CaptureCandidate
    path: Path
    toplevel: str | None = None
    repo_identity: str | None = None
    relpath: str | None = None
    commits: tuple[str, ...] = ()
    probe_failed: bool = False
    matching_commit: str | None = None


class GitVcsProbe:
    """Git-backed capture probe with memoized discovery and batched blobs."""

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds
        self._toplevel_by_directory: dict[str, str | None] = {}
        self._identity_by_context: dict[tuple[str, str, int], str | None] = {}
        self._durable_refs_by_repo: dict[str, tuple[str, ...] | None] = {}

    def repo_toplevel(self, path: str) -> str | None:
        candidate = Path(path)
        directory = candidate if candidate.is_dir() else candidate.parent
        directory_key = str(directory.resolve(strict=False))
        if directory_key in self._toplevel_by_directory:
            return self._toplevel_by_directory[directory_key]

        result = self._run_git(directory_key, "rev-parse", "--show-toplevel")
        toplevel = (
            str(Path(result).resolve(strict=False)) if result is not None else None
        )
        self._toplevel_by_directory[directory_key] = toplevel
        return toplevel

    def repo_identity(
        self,
        toplevel: str,
        *,
        project: str,
        workspace_num: int,
    ) -> str | None:
        normalized_toplevel = str(Path(toplevel).resolve(strict=False))
        cache_key = (normalized_toplevel, project, workspace_num)
        if cache_key in self._identity_by_context:
            return self._identity_by_context[cache_key]

        inventory = collect_repo_inventory(project=project)
        identity = None
        for record in inventory.records:
            candidate_paths: list[str] = []
            clone = record.clone_for_workspace(workspace_num)
            if clone is not None:
                candidate_paths.append(clone.path)
            candidate_paths.append(record.path)
            if any(
                candidate_path
                and str(Path(candidate_path).resolve(strict=False))
                == normalized_toplevel
                for candidate_path in candidate_paths
            ):
                identity = record.name
                break
        self._identity_by_context[cache_key] = identity
        return identity

    def durable_candidate_commits(
        self,
        toplevel: str,
        relpath: str,
        *,
        max_history_scan: int,
    ) -> tuple[str, ...] | None:
        refs = self._durable_refs(toplevel)
        if not refs:
            return None
        result = self._run_git(
            toplevel,
            "rev-list",
            f"--max-count={max_history_scan}",
            *refs,
            "--",
            relpath,
        )
        if result is None:
            return None
        return tuple(line for line in result.splitlines() if line)

    def blob_content_digests(
        self,
        toplevel: str,
        specs: Sequence[str],
    ) -> Mapping[str, str | None] | None:
        unique_specs = tuple(dict.fromkeys(specs))
        if not unique_specs:
            return {}
        if any("\n" in spec or "\r" in spec for spec in unique_specs):
            return None
        try:
            result = subprocess.run(
                ["git", "-C", toplevel, "cat-file", "--batch"],
                input=("".join(f"{spec}\n" for spec in unique_specs)).encode(),
                capture_output=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return None
        if result.returncode != 0:
            return None
        return _parse_batch_digests(unique_specs, result.stdout)

    def _durable_refs(self, toplevel: str) -> tuple[str, ...] | None:
        normalized = str(Path(toplevel).resolve(strict=False))
        if normalized in self._durable_refs_by_repo:
            return self._durable_refs_by_repo[normalized]

        refs: list[str] = []
        for args in (
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
            ("rev-parse", "--abbrev-ref", "origin/HEAD"),
        ):
            ref = self._run_git(normalized, *args)
            if ref:
                refs.append(ref)
        durable_refs = tuple(dict.fromkeys(refs)) or None
        self._durable_refs_by_repo[normalized] = durable_refs
        return durable_refs

    def _run_git(self, toplevel: str, *args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", toplevel, *args],
                capture_output=True,
                check=False,
                text=True,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return None
        if result.returncode != 0:
            return None
        try:
            return result.stdout.strip()
        except UnicodeError:
            return None


def capture_file_exceeds_size_limit(
    size_bytes: int,
    *,
    max_file_size_bytes: int | None = None,
) -> bool:
    """Return whether one file is too large for automatic byte capture."""

    if max_file_size_bytes is None:
        from sase.config import get_artifact_capture_max_file_size_bytes

        max_file_size_bytes = get_artifact_capture_max_file_size_bytes()
    return size_bytes > max(1, max_file_size_bytes)


def decide_captures(
    candidates: Sequence[CaptureCandidate],
    *,
    artifacts_dir: str | Path,
    workspace_dir: str | Path,
    project: str,
    workspace_num: int,
    run_started_at: datetime | float,
    probe: VcsProbe,
    limits: CaptureLimits,
) -> list[CaptureDecision]:
    """Classify candidates as byte copies, VCS references, or skipped rows."""

    workspace = Path(workspace_dir).resolve(strict=False)
    artifacts = _resolve_path(Path(artifacts_dir), workspace)
    started_at = (
        run_started_at.timestamp()
        if isinstance(run_started_at, datetime)
        else float(run_started_at)
    )
    contexts = [
        _probe_context(
            candidate,
            workspace=workspace,
            project=project,
            workspace_num=workspace_num,
            max_history_scan=limits.max_history_scan,
            probe=probe,
        )
        for candidate in candidates
    ]
    _match_durable_blobs(contexts, probe)

    decisions: list[CaptureDecision] = []
    stored_count = 0
    for context in contexts:
        decision = _decide_one(context, artifacts=artifacts, started_at=started_at)
        if decision.outcome == "store":
            if stored_count >= limits.max_stored_per_agent:
                decision = CaptureDecision("skip", "capture_cap")
            else:
                stored_count += 1
        decisions.append(decision)
    return decisions


def _probe_context(
    candidate: CaptureCandidate,
    *,
    workspace: Path,
    project: str,
    workspace_num: int,
    max_history_scan: int,
    probe: VcsProbe,
) -> _CandidateContext:
    path = _resolve_path(Path(candidate.path), workspace)
    context = _CandidateContext(candidate=candidate, path=path)
    try:
        context.toplevel = probe.repo_toplevel(str(path))
        if context.toplevel is None:
            return context
        context.repo_identity = probe.repo_identity(
            context.toplevel,
            project=project,
            workspace_num=workspace_num,
        )
        if context.repo_identity is None:
            context.probe_failed = True
            return context
        context.relpath = path.relative_to(
            Path(context.toplevel).resolve(strict=False)
        ).as_posix()
        commits = probe.durable_candidate_commits(
            context.toplevel,
            context.relpath,
            max_history_scan=max_history_scan,
        )
        if commits is None:
            context.probe_failed = True
        else:
            context.commits = commits
    except Exception:  # noqa: BLE001 - capture policy must fail safe.
        context.probe_failed = True
    return context


def _match_durable_blobs(
    contexts: Sequence[_CandidateContext],
    probe: VcsProbe,
) -> None:
    by_repo: dict[str, list[_CandidateContext]] = defaultdict(list)
    for context in contexts:
        if context.toplevel and context.commits and not context.probe_failed:
            by_repo[context.toplevel].append(context)

    for toplevel, repo_contexts in by_repo.items():
        specs = [
            f"{commit}:{context.relpath}"
            for context in repo_contexts
            for commit in context.commits
        ]
        try:
            digests = probe.blob_content_digests(toplevel, specs)
        except Exception:  # noqa: BLE001 - capture policy must fail safe.
            digests = None
        if digests is None:
            for context in repo_contexts:
                context.probe_failed = True
            continue
        for context in repo_contexts:
            context.matching_commit = next(
                (
                    commit
                    for commit in context.commits
                    if digests.get(f"{commit}:{context.relpath}")
                    == context.candidate.sha256
                ),
                None,
            )


def _decide_one(
    context: _CandidateContext,
    *,
    artifacts: Path,
    started_at: float,
) -> CaptureDecision:
    if context.matching_commit is not None:
        return CaptureDecision(
            "reference",
            "vcs_reproducible",
            vcs_repo=context.repo_identity,
            vcs_sha=context.matching_commit,
            vcs_relpath=context.relpath,
        )
    if context.probe_failed:
        return CaptureDecision("store", "vcs_probe_failed")
    if _is_within(context.path, artifacts):
        return CaptureDecision("store", "artifacts_dir")
    if context.candidate.origin == "changed":
        return CaptureDecision("store", "changed")
    try:
        if context.path.stat().st_mtime >= started_at:
            return CaptureDecision("store", "run_window")
    except OSError:
        pass
    if context.toplevel is None:
        return CaptureDecision("store", "mentioned_external")
    return CaptureDecision("skip", "mentioned_repo")


def _parse_batch_digests(
    specs: Sequence[str],
    output: bytes,
) -> dict[str, str | None] | None:
    digests: dict[str, str | None] = {}
    offset = 0
    for spec in specs:
        line_end = output.find(b"\n", offset)
        if line_end < 0:
            return None
        header = output[offset:line_end]
        offset = line_end + 1
        if header.endswith(b" missing"):
            digests[spec] = None
            continue
        try:
            _object_id, object_type, size_text = header.rsplit(b" ", 2)
            size = int(size_text)
        except (ValueError, UnicodeError):
            return None
        if size < 0 or offset + size >= len(output):
            return None
        content = output[offset : offset + size]
        offset += size
        if output[offset : offset + 1] != b"\n":
            return None
        offset += 1
        digests[spec] = (
            hashlib.sha256(content).hexdigest() if object_type == b"blob" else None
        )
    return digests if offset == len(output) else None


def _resolve_path(path: Path, base: Path) -> Path:
    return (base / path if not path.is_absolute() else path).resolve(strict=False)


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True
