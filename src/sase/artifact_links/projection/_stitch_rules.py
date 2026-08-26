"""Project `implements`/`produced-by` rows from primary-repo commit trailers.

Both rules share one commit-history walk of the project's primary repository
only (never its sidecars -- see the plan's measured-facts table for why).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sase.agents_sync.git import run_git
from sase.artifact_links.projection._cache import read_rule_cache, write_rule_cache
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs
from sase.association_agents import commit_agent_association
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.commit_footer_facade import LinkedCommitTagValue, parse_commit_footer

_STITCH_BEAD_RULE_ID = "stitch-bead"
_STITCH_AGENT_RULE_ID = "stitch-agent"
_LOG_FORMAT = "--format=%H%x00%ct%x00%B%x00"


def project_stitch_rules(inputs: ProjectionInputs) -> tuple[ProjectedEdge, ...]:
    """Emit `stitch-bead` and `stitch-agent` rows off one commit-history walk."""

    if inputs.primary_repo_root is None or inputs.primary_repo_name is None:
        return ()
    cached_bead_sha, cached_bead_rows = read_rule_cache(
        inputs.project_key, _STITCH_BEAD_RULE_ID
    )
    cached_agent_sha, cached_agent_rows = read_rule_cache(
        inputs.project_key, _STITCH_AGENT_RULE_ID
    )
    # Both rules share one walk, so a mismatched pair (a partial prior write)
    # is treated as no cache at all rather than trusted half-way.
    cached_sha = cached_bead_sha if cached_bead_sha == cached_agent_sha else None

    try:
        bead_rows, agent_rows, head_sha, changed = _current_rows(
            inputs.primary_repo_root,
            inputs.primary_repo_name,
            cached_sha=cached_sha,
            cached_bead_rows=cached_bead_rows,
            cached_agent_rows=cached_agent_rows,
        )
    except Exception:  # noqa: BLE001 - degrade to staleness, not deletion.
        return (
            *_edges_from_rows(_STITCH_BEAD_RULE_ID, cached_bead_rows),
            *_edges_from_rows(_STITCH_AGENT_RULE_ID, cached_agent_rows),
        )

    if changed:
        write_rule_cache(
            inputs.project_key, _STITCH_BEAD_RULE_ID, signature=head_sha, rows=bead_rows
        )
        write_rule_cache(
            inputs.project_key,
            _STITCH_AGENT_RULE_ID,
            signature=head_sha,
            rows=agent_rows,
        )
    return (
        *_edges_from_rows(_STITCH_BEAD_RULE_ID, bead_rows),
        *_edges_from_rows(_STITCH_AGENT_RULE_ID, agent_rows),
    )


def _current_rows(
    repo_root: Path,
    repo_name: str,
    *,
    cached_sha: str | None,
    cached_bead_rows: list[dict[str, str]],
    cached_agent_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], str, bool]:
    head_sha = _read_head_sha(repo_root)
    if head_sha is None:
        raise RuntimeError(f"could not resolve HEAD for {repo_root}")
    if cached_sha == head_sha:
        return cached_bead_rows, cached_agent_rows, head_sha, False

    identity = AgentIdentitySnapshot.current()
    if cached_sha is None or not _is_ancestor(repo_root, cached_sha, head_sha):
        # No cache, or the cached sha is not on HEAD's own line of history
        # (rebase, amend, prune) -- `git log <cached>..HEAD` would still
        # succeed in that case (the sha is a valid object, just not an
        # ancestor) and silently produce the wrong incremental set, so the
        # ancestry check must gate the range query rather than its exit code.
        bead_rows, agent_rows = _log_commits(repo_root, repo_name, identity, "HEAD")
        return bead_rows, agent_rows, head_sha, True

    result = run_git(
        repo_root,
        ["log", _LOG_FORMAT, f"{cached_sha}..HEAD"],
        op="artifact_links.projection.stitch",
    )
    if result.returncode != 0:
        bead_rows, agent_rows = _log_commits(repo_root, repo_name, identity, "HEAD")
        return bead_rows, agent_rows, head_sha, True

    new_bead_rows, new_agent_rows = _parse_log_output(
        result.stdout, repo_name, identity
    )
    return (
        [*cached_bead_rows, *new_bead_rows],
        [*cached_agent_rows, *new_agent_rows],
        head_sha,
        True,
    )


def _is_ancestor(repo_root: Path, ancestor_sha: str, descendant_sha: str) -> bool:
    result = run_git(
        repo_root,
        ["merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        op="artifact_links.projection.stitch",
    )
    return result.returncode == 0


def _log_commits(
    repo_root: Path,
    repo_name: str,
    identity: AgentIdentitySnapshot,
    rev: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    result = run_git(
        repo_root,
        ["log", _LOG_FORMAT, rev],
        op="artifact_links.projection.stitch",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log {rev!r} failed in {repo_root}: {result.stderr}")
    return _parse_log_output(result.stdout, repo_name, identity)


def _parse_log_output(
    stdout: str,
    repo_name: str,
    identity: AgentIdentitySnapshot,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    chunks = stdout.split("\x00")
    bead_rows: list[dict[str, str]] = []
    agent_rows: list[dict[str, str]] = []
    for index in range(0, len(chunks) - 2, 3):
        sha = chunks[index].strip().casefold()
        if not sha:
            continue
        try:
            committed_at = int(chunks[index + 1].strip())
        except ValueError:
            continue
        body = chunks[index + 2]
        created_at = datetime.fromtimestamp(committed_at, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        footer = parse_commit_footer(body)
        tags = {tag.key: tag.value for tag in footer.tags}
        source_ref = f"stitch:{repo_name}@{sha}"

        bead_label = _tag_label(tags.get("BEAD"))
        if bead_label:
            bead_rows.append(
                {
                    "source_ref": source_ref,
                    "relation": "implements",
                    "target_ref": f"bead:{bead_label}",
                    "description": (
                        f"commit {sha[:12]}'s `SASE_BEAD=` trailer names bead "
                        f"{bead_label}"
                    ),
                    "created_at": created_at,
                }
            )

        association = commit_agent_association(tags.get("AGENT"), identity)
        if association is not None:
            agent_rows.append(
                {
                    "source_ref": source_ref,
                    "relation": "produced-by",
                    "target_ref": f"agent:{association.label}",
                    "description": (
                        f"commit {sha[:12]}'s `SASE_AGENT=` trailer names agent "
                        f"{association.label}"
                    ),
                    "created_at": created_at,
                }
            )
    return bead_rows, agent_rows


def _tag_label(value: object) -> str | None:
    if isinstance(value, LinkedCommitTagValue):
        return value.label.strip() or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _read_head_sha(repo_root: Path) -> str | None:
    git_dir = _resolve_git_dir(repo_root)
    if git_dir is None:
        return None
    try:
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head_text.startswith("ref:"):
        return head_text or None
    ref_name = head_text.removeprefix("ref:").strip()
    try:
        return (git_dir / ref_name).read_text(encoding="utf-8").strip() or None
    except OSError:
        return _read_packed_ref(git_dir, ref_name)


def _resolve_git_dir(repo_root: Path) -> Path | None:
    git_path = repo_root / ".git"
    if git_path.is_dir():
        return git_path
    if not git_path.is_file():
        return None
    try:
        text = git_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = Path(text.removeprefix("gitdir:").strip())
    if not target.is_absolute():
        target = (repo_root / target).resolve()
    return target if target.is_dir() else None


def _read_packed_ref(git_dir: Path, ref_name: str) -> str | None:
    try:
        lines = (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        sha, _, name = line.partition(" ")
        if name.strip() == ref_name:
            return sha.strip()
    return None


def _edges_from_rows(
    rule_id: str, rows: list[dict[str, str]]
) -> tuple[ProjectedEdge, ...]:
    return tuple(
        ProjectedEdge(
            source_ref=row["source_ref"],
            relation=row["relation"],
            target_ref=row["target_ref"],
            description=row["description"],
            rule_id=rule_id,
            created_at=row["created_at"],
        )
        for row in rows
    )


__all__ = ["project_stitch_rules"]
