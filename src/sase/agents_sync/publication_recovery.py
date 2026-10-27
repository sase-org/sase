"""Shared GH013 push-rejection recovery for agents-sidecar publishers.

Every agents-sidecar push path (full sync, commit drain, direct prompt
publication, and prompt migration) classifies a failed push through the Rust
``sidecar_publication`` contract before touching logs or retry state. Remote
output is untrusted and may contain secrets, so secret-scanning and
repository-rule rejections always surface sanitized, value-free diagnostics;
only validated relative paths and commit identities are kept for attribution.

Secret-scanning recovery preserves sole-copy objects privately, records
permanent content blocks before any replay, and resets only the verified
managed machine publication clone to the freshly fetched upstream tip — never
a primary checkout, never ``HEAD^``, and never a hard-coded branch. Each step
is idempotent, so an interrupted recovery resumes safely on the next drain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.agents_sync.git import GitRunner

REJECTED_SECRET_SCAN = "rejected_secret_scan"
REJECTED_REPOSITORY_RULE = "rejected_repository_rule"
REJECTED_NON_FAST_FORWARD = "rejected_non_fast_forward"
REJECTED_FETCH_FIRST = "rejected_fetch_first"

RECOVERY_RETRY_DIVERGENCE = "retry_divergence"
RECOVERY_REBUILD_CLEAN = "rebuild_clean"
RECOVERY_STOP = "stop"

_DIVERGENCE_CLASSIFICATIONS = frozenset(
    {REJECTED_NON_FAST_FORWARD, REJECTED_FETCH_FIRST}
)

# Files under this prefix can hold the only surviving copy of a captured
# object after its ephemeral source goes away. They are preserved privately
# before any reset touches the managed clone.
_ARCHIVE_OBJECT_PREFIX = "files/objects/"

_MAX_ATTRIBUTED_PATHS = 8


@dataclass(frozen=True, slots=True)
class PublicationPushRejection:
    """Sanitized classification of one failed agents-sidecar push."""

    classification: str
    commit_ids: tuple[str, ...]
    relative_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicationPushRecovery:
    """What one failed push means for the calling publisher.

    ``action`` is ``retry_divergence`` (remote moved; run the existing
    integrate-and-retry path), ``rebuild_clean`` (the managed clone was
    already reset to the upstream tip and offending content is blocked;
    rebuild from sources without dropping another commit), or ``stop``
    (``error`` holds the sanitized terminal diagnostic).
    """

    rejection: PublicationPushRejection
    action: str
    blocked_paths: tuple[str, ...] = ()
    preserved_paths: tuple[str, ...] = ()
    upstream_tip: str | None = None
    error: str | None = None


def classify_publication_push(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
) -> PublicationPushRejection:
    """Classify one push result through Rust core, failing safe on any error.

    A missing or misbehaving binding never authorizes a retry of rejected
    bytes; it degrades to an unattributed terminal failure.
    """

    try:
        from sase.core.sidecar_publication_facade import (
            classify_sidecar_publication_push_result,
        )

        result = classify_sidecar_publication_push_result(
            returncode=returncode, stdout=stdout, stderr=stderr
        )
    except Exception:  # noqa: BLE001 - classification failure never retries.
        return PublicationPushRejection("unknown_failure", (), ())
    return PublicationPushRejection(
        classification=result.classification,
        commit_ids=result.commit_ids,
        relative_paths=result.relative_paths,
    )


def sanitized_push_error(
    prefix: str,
    rejection: PublicationPushRejection,
    *,
    blocked_paths: tuple[str, ...] = (),
) -> str:
    """Render a value-free diagnostic for a content-security push rejection.

    Only validated relative paths appear; raw remote output (which may echo
    secrets) never does. Transport and divergence failures keep their legacy
    diagnostics at the call site because those carry no content verdict.
    """

    if rejection.classification == REJECTED_SECRET_SCAN:
        blocked = blocked_paths or rejection.relative_paths
        if blocked:
            shown = ", ".join(f"{path!r}" for path in blocked[:_MAX_ATTRIBUTED_PATHS])
            extra = (
                f" (+{len(blocked) - _MAX_ATTRIBUTED_PATHS} more)"
                if len(blocked) > _MAX_ATTRIBUTED_PATHS
                else ""
            )
            return (
                f"{prefix}: remote secret scanning rejected the push; "
                f"blocked {len(blocked)} path(s) locally ({shown}{extra}); "
                "clean publication continues without them"
            )
        return (
            f"{prefix}: remote secret scanning rejected the push; "
            "the rejected batch was reset and no path could be attributed, "
            "so clean units will be isolated on rebuild"
        )
    if rejection.classification == REJECTED_REPOSITORY_RULE:
        return (
            f"{prefix}: remote repository rules rejected the push; "
            "no secret was confirmed and nothing was blocked"
        )
    return f"{prefix}: git push failed without a recognized remote rejection"


def recover_publication_push(
    repo: Path,
    git_runner: GitRunner,
    *,
    project_key: str,
    repository_identity: str,
    returncode: int,
    stdout: str,
    stderr: str,
    affected_requests: tuple[str, ...] = (),
) -> PublicationPushRecovery:
    """Classify one failed push and recover shared publication state.

    Must be called under the publication lock. Divergent remotes ask for the
    caller's existing integrate-and-retry path. Secret-scanning rejections
    preserve sole-copy objects, record permanent blocks, reset the managed
    clone to the fetched upstream tip, and ask for one bounded clean
    rebuild. Everything else stops with a sanitized diagnostic. Never raises:
    an internal failure stops the publisher with a value-free error instead.
    """

    rejection = classify_publication_push(
        returncode=returncode, stdout=stdout, stderr=stderr
    )
    if rejection.classification in _DIVERGENCE_CLASSIFICATIONS:
        return PublicationPushRecovery(rejection, RECOVERY_RETRY_DIVERGENCE)
    if rejection.classification != REJECTED_SECRET_SCAN:
        return PublicationPushRecovery(rejection, RECOVERY_STOP)
    try:
        return _recover_secret_scanning_rejection(
            repo,
            git_runner,
            project_key=project_key,
            repository_identity=repository_identity,
            rejection=rejection,
            affected_requests=affected_requests,
        )
    except Exception as exc:  # noqa: BLE001 - recovery failure stops safely.
        return PublicationPushRecovery(
            rejection,
            RECOVERY_STOP,
            error=(
                "agents publication recovery failed safely without resetting: "
                f"{type(exc).__name__}"
            ),
        )


def _recover_secret_scanning_rejection(
    repo: Path,
    git_runner: GitRunner,
    *,
    project_key: str,
    repository_identity: str,
    rejection: PublicationPushRejection,
    affected_requests: tuple[str, ...],
) -> PublicationPushRecovery:
    from sase.agents_sync.publication_protection import (
        record_publication_push_rejection,
    )

    tip = _fetch_upstream_tip(repo, git_runner)
    if tip is None:
        # Fail safely with local commits intact. Blocks are still recorded
        # below so the next drain withholds the same bytes even though this
        # batch could not be reset yet.
        digests = _digests_for_paths(repo, git_runner, rejection.relative_paths)
        blocked = _record_blocks(
            record_publication_push_rejection,
            project_key=project_key,
            repository_identity=repository_identity,
            rejection=rejection,
            digests=digests,
            affected_requests=affected_requests,
        )
        return PublicationPushRecovery(
            rejection,
            RECOVERY_STOP,
            blocked_paths=blocked,
            error=(
                "agents publication push was rejected by secret scanning and "
                "the upstream tip could not be verified, so the batch was "
                "left in place; offending content is blocked and the next "
                "drain will withhold it"
            ),
        )
    changed = _outgoing_changed_paths(repo, git_runner, tip)
    if changed is None:
        # Fall back to every tracked archive object at HEAD: a superset that
        # keeps preservation complete when the range cannot be enumerated.
        changed = _tracked_archive_objects(repo, git_runner)
        if changed is None:
            return PublicationPushRecovery(
                rejection,
                RECOVERY_STOP,
                error=(
                    "agents publication push was rejected by secret scanning "
                    "and the outgoing content could not be enumerated, so "
                    "nothing was reset"
                ),
            )
    preserved = _preserve_archive_objects(repo, project_key=project_key, paths=changed)
    if isinstance(preserved, str):
        return PublicationPushRecovery(rejection, RECOVERY_STOP, error=preserved)
    digests = _digests_for_paths(repo, git_runner, rejection.relative_paths)
    blocked = _record_blocks(
        record_publication_push_rejection,
        project_key=project_key,
        repository_identity=repository_identity,
        rejection=rejection,
        digests=digests,
        affected_requests=affected_requests,
    )
    reset_error = _reset_managed_clone_to_tip(
        repo, git_runner, repository_identity=repository_identity, tip=tip
    )
    if reset_error is not None:
        return PublicationPushRecovery(
            rejection,
            RECOVERY_STOP,
            blocked_paths=blocked,
            preserved_paths=preserved,
            upstream_tip=tip,
            error=reset_error,
        )
    return PublicationPushRecovery(
        rejection,
        RECOVERY_REBUILD_CLEAN,
        blocked_paths=blocked,
        preserved_paths=preserved,
        upstream_tip=tip,
    )


def _record_blocks(
    record_push_rejection: object,
    *,
    project_key: str,
    repository_identity: str,
    rejection: PublicationPushRejection,
    digests: dict[str, str],
    affected_requests: tuple[str, ...],
) -> tuple[str, ...]:
    """Persist permanent blocks for attributed paths; never raises."""

    blocked: list[str] = []
    # Coerce defensively: the ledger stores request identities as strings,
    # and a non-string entry must never silently drop a block.
    identities = tuple(str(request) for request in affected_requests)
    for path in rejection.relative_paths:
        digest = digests.get(path)
        if digest is None:
            continue
        try:
            result = record_push_rejection(  # type: ignore[operator]
                project_key,
                repository_identity=repository_identity,
                relative_destination=path,
                sha256=digest,
                classification=REJECTED_SECRET_SCAN,
                affected_requests=identities,
            )
        except Exception:  # noqa: BLE001 - one bad row never stops the rest.
            continue
        if result is None:
            # The core contract only returns None for a non-secret
            # classification; our classification is fixed, so treat this as
            # a skipped row rather than a recorded block.
            continue
        blocked.append(path)
    return tuple(blocked)


def _digests_for_paths(
    repo: Path,
    git_runner: GitRunner,
    paths: tuple[str, ...],
) -> dict[str, str]:
    """Hash attributed paths from the worktree, falling back to HEAD blobs."""

    import hashlib

    digests: dict[str, str] = {}
    for path in paths:
        candidate = repo / path
        try:
            if candidate.is_symlink() or not candidate.is_file():
                raise OSError("not a regular worktree file")
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            shown = _show_head_blob(git_runner, repo, path)
            if shown is None:
                continue
            digest = shown
        digests[path] = digest
    return digests


def _show_head_blob(git_runner: GitRunner, repo: Path, path: str) -> str | None:
    """Hash one HEAD blob as UTF-8 text; binary blobs stay unattributed."""

    import hashlib

    try:
        shown = git_runner(
            repo,
            ["show", f"HEAD:{path}"],
            op="agents_sync.publication_recovery_head_blob",
        )
    except Exception:  # noqa: BLE001 - an unreadable blob stays unattributed.
        return None
    if shown.returncode != 0 or not isinstance(shown.stdout, str):
        return None
    try:
        return hashlib.sha256(shown.stdout.encode("utf-8")).hexdigest()
    except Exception:  # noqa: BLE001 - encoding failure stays unattributed.
        return None


def _fetch_upstream_tip(repo: Path, git_runner: GitRunner) -> str | None:
    """Fetch the configured upstream and return its tip SHA, or None."""

    try:
        upstream = git_runner(
            repo,
            ["rev-parse", "--symbolic-full-name", "@{upstream}"],
            op="agents_sync.publication_recovery_upstream",
        )
    except Exception:  # noqa: BLE001 - an unresolvable upstream stops recovery.
        return None
    if upstream.returncode != 0 or not isinstance(upstream.stdout, str):
        return None
    full_ref = upstream.stdout.strip()
    if not full_ref.startswith("refs/remotes/"):
        return None
    remote = full_ref[len("refs/remotes/") :].split("/", 1)[0]
    if not remote:
        return None
    try:
        fetched = git_runner(
            repo, ["fetch", remote], network=True, op="agents_sync.recovery_fetch"
        )
    except Exception:  # noqa: BLE001 - a failed fetch stops recovery safely.
        return None
    if fetched.returncode != 0:
        return None
    try:
        tip = git_runner(
            repo,
            ["rev-parse", "--verify", full_ref],
            op="agents_sync.publication_recovery_tip",
        )
    except Exception:  # noqa: BLE001 - an unreadable tip stops recovery safely.
        return None
    if tip.returncode != 0 or not isinstance(tip.stdout, str):
        return None
    sha = tip.stdout.strip()
    if len(sha) not in (40, 64) or any(
        char not in "0123456789abcdefABCDEF" for char in sha
    ):
        return None
    return sha.lower()


def _outgoing_changed_paths(
    repo: Path, git_runner: GitRunner, tip: str
) -> tuple[str, ...] | None:
    """List files changed across the full outgoing range ``tip..HEAD``.

    The whole range matters, not just the tip tree: a later push would
    resend blocked bytes sitting in an older unpushed commit.
    """

    try:
        changed = git_runner(
            repo,
            ["diff", "--name-only", "-z", tip, "HEAD"],
            op="agents_sync.publication_recovery_range",
        )
    except Exception:  # noqa: BLE001 - an unreadable range stops recovery.
        return None
    if changed.returncode != 0 or not isinstance(changed.stdout, str):
        return None
    return tuple(path for path in changed.stdout.split("\0") if path and path != "HEAD")


def _tracked_archive_objects(
    repo: Path, git_runner: GitRunner
) -> tuple[str, ...] | None:
    """List tracked archive objects at HEAD (preservation fallback)."""

    try:
        listed = git_runner(
            repo,
            ["ls-tree", "-r", "--name-only", "-z", "HEAD", "--", "files/objects"],
            op="agents_sync.publication_recovery_objects",
        )
    except Exception:  # noqa: BLE001 - an unreadable tree stops recovery.
        return None
    if listed.returncode != 0 or not isinstance(listed.stdout, str):
        return None
    return tuple(path for path in listed.stdout.split("\0") if path)


def _preserve_archive_objects(
    repo: Path, *, project_key: str, paths: tuple[str, ...]
) -> tuple[str, ...] | str:
    """Copy sole-copy outgoing objects to private storage, verifying each.

    Returns the preserved paths, or a value-free error when any copy fails.
    A failed preservation stops the mutation and keeps every source
    recoverable in place; it never authorizes publication.
    """

    from sase.agents_sync.prompt_archive.protection import (
        preserve_private_publication_object,
    )

    import hashlib

    preserved: list[str] = []
    for path in paths:
        if not path.startswith(_ARCHIVE_OBJECT_PREFIX):
            continue
        source = repo / path
        try:
            if source.is_symlink() or not source.is_file():
                continue
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            preserve_private_publication_object(
                project_key=project_key, sha256=digest, source=source
            )
        except (OSError, ValueError):
            return (
                "agents publication recovery could not preserve a withheld "
                f"object at {path!r}; the batch was left in place"
            )
        preserved.append(path)
    return tuple(preserved)


def _reset_managed_clone_to_tip(
    repo: Path,
    git_runner: GitRunner,
    *,
    repository_identity: str,
    tip: str,
) -> str | None:
    """Reset only the verified managed clone to the fetched tip.

    Refuses when the toplevel is not *repo*, the worktree is bare, or the
    origin URL does not match the publication target, so a primary checkout
    or arbitrary user repo can never be reset here. Returns a value-free
    error string, or None on success. Untracked files (including pending
    objects not yet committed) survive ``reset --hard`` by design; no broad
    untracked cleanup ever runs here because it could delete the only copy
    of a preserved object.
    """

    try:
        toplevel = git_runner(
            repo,
            ["rev-parse", "--show-toplevel"],
            op="agents_sync.publication_recovery_toplevel",
        )
    except Exception:  # noqa: BLE001 - an unverifiable repo is never reset.
        return (
            "agents publication recovery could not verify the managed clone; "
            "the batch was left in place"
        )
    if toplevel.returncode != 0 or not isinstance(toplevel.stdout, str):
        return (
            "agents publication recovery could not verify the managed clone; "
            "the batch was left in place"
        )
    try:
        if Path(toplevel.stdout.strip()).resolve() != repo.resolve():
            return (
                "agents publication recovery refused to reset outside the "
                "managed publication clone"
            )
    except OSError:
        return (
            "agents publication recovery could not verify the managed clone; "
            "the batch was left in place"
        )
    try:
        bare = git_runner(
            repo,
            ["rev-parse", "--is-bare-repository"],
            op="agents_sync.publication_recovery_bare",
        )
        origin = git_runner(
            repo,
            ["config", "--get", "remote.origin.url"],
            op="agents_sync.publication_recovery_origin",
        )
    except Exception:  # noqa: BLE001 - an unverifiable repo is never reset.
        return (
            "agents publication recovery could not verify the managed clone; "
            "the batch was left in place"
        )
    if (
        bare.returncode != 0
        or (bare.stdout or "").strip() != "false"
        or origin.returncode != 0
        or (origin.stdout or "").strip() != repository_identity
    ):
        return (
            "agents publication recovery refused to reset outside the "
            "managed publication clone"
        )
    try:
        reset = git_runner(
            repo,
            ["reset", "--hard", tip],
            op="agents_sync.publication_recovery_reset",
        )
    except Exception:  # noqa: BLE001 - a failed reset keeps local commits.
        return (
            "agents publication recovery could not reset the managed clone; "
            "the batch was left in place"
        )
    if reset.returncode != 0:
        return (
            "agents publication recovery could not reset the managed clone; "
            "the batch was left in place"
        )
    return None


__all__ = [
    "RECOVERY_REBUILD_CLEAN",
    "RECOVERY_RETRY_DIVERGENCE",
    "RECOVERY_STOP",
    "REJECTED_FETCH_FIRST",
    "REJECTED_NON_FAST_FORWARD",
    "REJECTED_REPOSITORY_RULE",
    "REJECTED_SECRET_SCAN",
    "PublicationPushRecovery",
    "PublicationPushRejection",
    "classify_publication_push",
    "recover_publication_push",
    "sanitized_push_error",
]
