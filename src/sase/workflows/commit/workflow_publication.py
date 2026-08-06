"""Post-commit publication steps for the commit workflow."""

from __future__ import annotations

from collections.abc import Callable

from sase.output import print_status
from sase.workflows.commit.checkpoint import CommitCheckpoint


def run_agent_publication_step(
    cp: CommitCheckpoint,
    method: str,
    *,
    checkpoint_save: Callable[[CommitCheckpoint], str | None],
    get_vcs_provider: Callable[[str], object],
) -> bool:
    """Publish generated bead pages and the committing agent hood."""
    if method not in ("create_commit", "create_pull_request"):
        return True
    message = str(cp.payload.get("message") or "")
    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    if "publish_bead_pages" not in cp.completed_steps:
        from sase.bead_pages.publication import publish_committed_bead_pages

        try:
            anchor = resolve_checkout_anchor(cp.cwd)
            publish_committed_bead_pages(
                message,
                primary_root=anchor.primary_root,
                project=anchor.project_name,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort projection.
            print_status(
                f"Could not publish committed bead pages: {exc}",
                "warning",
            )
        cp.completed_steps.append("publish_bead_pages")
        checkpoint_save(cp)

    from sase.sdd.plan_header_refresh import refresh_committed_plan_header

    if not cp.publication_agent:
        refresh_committed_plan_header(message, primary_root=cp.cwd)
        return True

    if not cp.primary_revision:
        provider = get_vcs_provider(cp.cwd)
        try:
            revision = provider.revision_id("HEAD", cp.cwd)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - provider boundary
            print_status(
                "The primary commit succeeded, but its immutable revision "
                f"could not be resolved for agent publication: {exc}. "
                "Run `sase commit --resume` to retry without creating "
                "another primary commit.",
                "error",
            )
            return False
        if not isinstance(revision, str) or not revision.strip():
            print_status(
                "The primary commit succeeded, but the VCS provider did "
                "not return an immutable revision. Run "
                "`sase commit --resume` to retry without creating another "
                "primary commit.",
                "error",
            )
            return False
        cp.primary_revision = revision.strip()
        checkpoint_save(cp)

    if "publish_prompt_archive" not in cp.completed_steps:
        from sase.agents_sync.prompt_archive import publish_prompt_archive

        try:
            prompt_outcome = publish_prompt_archive(
                cp.publication_agent,
                cp.primary_revision,
                commit_cwd=cp.cwd,
            )
        except Exception as exc:  # noqa: BLE001 - auxiliary publication boundary
            # The archive never reached the durable queue, so no later pass
            # knows it is owed. Stop here and let `sase commit --resume` retry.
            print_status(
                "The primary commit succeeded, but prompt archive publication "
                f"failed before a retry could be confirmed: {exc}. Run "
                "`sase commit --resume` to retry without creating another "
                "primary commit.",
                "error",
            )
            return False
        if prompt_outcome.error and not prompt_outcome.queued:
            print_status(
                "The primary commit succeeded, but prompt archive publication "
                f"could not be queued: {prompt_outcome.error}. Run "
                "`sase commit --resume` to retry without creating another "
                "primary commit.",
                "error",
            )
            return False
        if prompt_outcome.error:
            # The request is durable: the same agent-hood publication carries
            # this prompt, so the archive is rebuilt on the next drain.
            print_status(
                "The primary commit succeeded, but prompt archive publication "
                f"was deferred and will retry with agent publication: "
                f"{prompt_outcome.error}",
                "warning",
            )
        elif prompt_outcome.skip_reason:
            print_status(
                "The primary commit succeeded, but prompt archive "
                f"publication was skipped: {prompt_outcome.skip_reason}.",
                "warning",
            )
        cp.completed_steps.append("publish_prompt_archive")
        checkpoint_save(cp)

    refresh_committed_plan_header(message, primary_root=cp.cwd)
    if "publish_agent_hood" in cp.completed_steps:
        return True

    from sase.agents_sync.commit_publication import publish_committed_agent_hood

    try:
        outcome = publish_committed_agent_hood(
            cp.publication_agent,
            cp.primary_revision,
            commit_cwd=cp.cwd,
        )
    except Exception as exc:  # noqa: BLE001 - auxiliary publication boundary
        print_status(
            "The primary commit succeeded, but agent publication failed "
            f"before a retry could be confirmed: {exc}. Run "
            "`sase commit --resume` to retry without creating another "
            "primary commit.",
            "error",
        )
        return False
    if outcome.error and not outcome.queued and not outcome.skip_reason:
        print_status(
            "The primary commit succeeded, but agent publication could "
            f"not be queued: {outcome.error}. Run `sase commit --resume` "
            "to retry without creating another primary commit.",
            "error",
        )
        return False
    if outcome.queued:
        print_status(
            _agent_publication_deferred_message(outcome),
            "warning",
        )
    elif outcome.skip_reason:
        reason = outcome.skip_reason.rstrip(".")
        print_status(
            "The primary commit succeeded, but agent publication was "
            f"skipped for repository {cp.cwd!r}: {reason}.",
            "warning",
        )
    cp.completed_steps.append("publish_agent_hood")
    checkpoint_save(cp)
    return True


def _agent_publication_deferred_message(outcome: object) -> str:
    """Explain how to recover a deferred agent-hood publication."""
    from sase.agents_sync.publication_outbox import (
        PUBLICATION_DROP_COMMAND,
        PUBLICATION_RETRY_COMMAND,
    )

    error = getattr(outcome, "error", None)
    quarantined = int(getattr(outcome, "quarantined", 0) or 0)
    retired = int(getattr(outcome, "retired", 0) or 0)
    error_detail = f" Last error: {error}" if error else ""
    if quarantined or retired:
        counts = ", ".join(
            (
                *((f"{quarantined} quarantined",) if quarantined else ()),
                *((f"{retired} retired",) if retired else ()),
            )
        )
        plural = "" if quarantined + retired == 1 else "s"
        remediation = (
            f"Run `{PUBLICATION_RETRY_COMMAND}` to retry."
            if quarantined and not retired
            else f"Run `{PUBLICATION_DROP_COMMAND}` to drop the retired request{plural}."
            if retired and not quarantined
            else (
                f"Run `{PUBLICATION_RETRY_COMMAND}` to retry the quarantined "
                f"request(s) and `{PUBLICATION_DROP_COMMAND}` to drop the "
                "retired one(s)."
            )
        )
        return (
            "Primary commit succeeded, but this project already has "
            f"{counts} agent-hood publication request{plural}. "
            "The link written to this commit may remain unavailable until the "
            f"outbox is cleared. {remediation}{error_detail}"
        )
    return (
        "Primary commit succeeded; agent-hood publication is queued and will "
        f"retry automatically.{error_detail}"
    )
