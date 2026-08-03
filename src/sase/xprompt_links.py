"""Resolve hosted URLs for launch-captured xprompt definition provenance."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from sase.agents_sync.git import GitRunner
from sase.sdd.hosted_links import HostedLinkResolver


class XpromptSourceRecord(TypedDict):
    """Python projection of one row from ``xprompt_sources.json``."""

    schema_version: int
    raw_ref: str
    name: str
    kind: str
    source_kind: str | None
    source_path: str | None
    definition_line: int | None
    repo: str | None
    repo_root: str | None
    repo_relpath: str | None
    chezmoi: bool
    skipped_reason: str | None


class XpromptTargetResolver:
    """Resolve one captured xprompt provenance record to a hosted blob URL.

    Shaped like ``_ArtifactTargetResolver``: a reference is linkified only
    when a hosted URL can be resolved for its definition, and any failure
    returns ``None`` rather than guessing.
    """

    def __init__(
        self,
        *,
        primary_root: Path,
        primary_revision: str,
        hosted: HostedLinkResolver | None,
        git_runner: GitRunner,
        repository_roots: dict[str, Path],
    ) -> None:
        self._primary_root = primary_root.resolve(strict=False)
        self._primary_revision = primary_revision
        self._hosted = hosted
        self._git_runner = git_runner
        self._repository_roots = repository_roots

    def __call__(self, record: XpromptSourceRecord) -> str | None:
        repo_name = record.get("repo")
        repo_relpath = record.get("repo_relpath")
        if not repo_name or not repo_relpath or self._hosted is None:
            return None
        root = self._resolve_root(repo_name, record.get("repo_root"))
        if root is None:
            return None
        revision = (
            self._primary_revision
            if root == self._primary_root
            else _git_revision(root, self._git_runner)
        )
        if not revision:
            return None
        url = self._hosted.blob_url_for_repository(root, revision, repo_relpath)
        if url is None:
            return None
        definition_line = record.get("definition_line")
        return f"{url}#L{definition_line}" if definition_line is not None else url

    def _resolve_root(
        self,
        repo_name: str,
        recorded_root: str | None,
    ) -> Path | None:
        """Prefer the captured root, falling back to it having disappeared.

        The recorded root is the exact source tree the definition was read
        from at launch time (correct even for a chezmoi remap), so it wins
        whenever it still exists. Only a since-removed recorded root falls
        back to the freshly resolved inventory root for the same repo name,
        which may itself be a materialized per-workspace clone.
        """

        if recorded_root:
            candidate = Path(recorded_root).expanduser()
            if candidate.is_dir():
                return candidate.resolve(strict=False)
        return self._repository_roots.get(repo_name)


def _git_revision(root: Path, git_runner: GitRunner) -> str | None:
    result = git_runner(root, ["rev-parse", "HEAD"], op="xprompt_links.revision")
    return result.stdout.strip() if result.returncode == 0 else None


__all__ = [
    "XpromptSourceRecord",
    "XpromptTargetResolver",
]
