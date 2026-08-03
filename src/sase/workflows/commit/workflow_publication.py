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
    """Durably mark sidecar work for the publications lumberjack."""
    if method not in ("create_commit", "create_pull_request"):
        return True
    message = str(cp.payload.get("message") or "")
    from sase.core.commit_footer_facade import parse_commit_footer

    footer_keys = {tag.key for tag in parse_commit_footer(message).tags}
    if not cp.publication_agent and not footer_keys.intersection({"BEAD", "PLAN"}):
        return True

    revision_required = bool(cp.publication_agent or "PLAN" in footer_keys)
    if revision_required and not cp.primary_revision:
        try:
            provider = get_vcs_provider(cp.cwd)
            revision = provider.revision_id("HEAD", cp.cwd)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - provider boundary
            print_status(
                "The primary commit succeeded, but its immutable revision "
                f"could not be resolved for sidecar publication: {exc}. "
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
    primary_revision = cp.primary_revision or ""

    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    anchor = resolve_checkout_anchor(cp.cwd)
    queued = False
    if "publish_bead_pages" not in cp.completed_steps:
        from sase.bead_pages.publication import mark_committed_bead_pages

        try:
            bead_outcome = mark_committed_bead_pages(
                message,
                primary_root=anchor.primary_root,
                primary_revision=primary_revision,
                project=anchor.project_name,
            )
        except Exception as exc:  # noqa: BLE001 - auxiliary queue boundary.
            print_status(
                f"Could not queue committed bead pages: {exc}",
                "warning",
            )
        else:
            queued = queued or bead_outcome.queued
            if bead_outcome.error:
                print_status(
                    f"Could not queue committed bead pages: {bead_outcome.error}",
                    "warning",
                )
        cp.completed_steps.append("publish_bead_pages")
        checkpoint_save(cp)

    if "PLAN" in footer_keys:
        from sase.sdd.plan_header_refresh import mark_committed_plan_header

        try:
            plan_outcome = mark_committed_plan_header(
                message,
                primary_root=anchor.primary_root,
                primary_revision=primary_revision,
                project=anchor.project_name,
            )
        except Exception as exc:  # noqa: BLE001 - auxiliary queue boundary.
            print_status(
                f"Could not queue committed plan header: {exc}",
                "warning",
            )
        else:
            queued = queued or plan_outcome.queued
            if plan_outcome.error:
                print_status(
                    f"Could not queue committed plan header: {plan_outcome.error}",
                    "warning",
                )

    if not cp.publication_agent:
        if queued:
            _print_publications_lane_status()
        return True

    if "publish_prompt_archive" not in cp.completed_steps:
        # Prompt archives are regenerated as part of the queued agent-hood
        # transaction. Preserve the historical checkpoint for artifact staging.
        cp.completed_steps.append("publish_prompt_archive")
        checkpoint_save(cp)

    if "publish_agent_hood" in cp.completed_steps:
        if queued:
            _print_publications_lane_status()
        return True

    from sase.agents_sync.commit_publication import (
        enqueue_committed_agent_publication,
    )

    try:
        agent_outcome = enqueue_committed_agent_publication(
            cp.publication_agent,
            primary_revision,
            commit_cwd=cp.cwd,
        )
    except Exception as exc:  # noqa: BLE001 - auxiliary publication boundary
        print_status(
            f"Could not queue committed agent publication: {exc}",
            "warning",
        )
        agent_outcome = None
    if agent_outcome is not None:
        queued = queued or agent_outcome.queued
    if (
        agent_outcome is not None
        and agent_outcome.error
        and not agent_outcome.queued
        and not agent_outcome.skip_reason
    ):
        print_status(
            f"Could not queue committed agent publication: {agent_outcome.error}",
            "warning",
        )
    if agent_outcome is not None and (
        agent_outcome.quarantined or agent_outcome.retired
    ):
        print_status(
            _agent_publication_deferred_message(agent_outcome),
            "warning",
        )
    elif agent_outcome is not None and agent_outcome.skip_reason:
        reason = agent_outcome.skip_reason.rstrip(".")
        print_status(
            "The primary commit succeeded, but agent publication was "
            f"skipped for repository {cp.cwd!r}: {reason}.",
            "warning",
        )
    cp.completed_steps.append("publish_agent_hood")
    checkpoint_save(cp)
    if queued and not (
        agent_outcome is not None
        and (agent_outcome.quarantined or agent_outcome.retired)
    ):
        _print_publications_lane_status()
    return True


def _print_publications_lane_status() -> None:
    print_status(
        "Primary commit succeeded; sidecar publication is queued for the "
        "`publications` lane.",
        "info",
    )


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
            "`publications` lane backlog is cleared. "
            f"{remediation}{error_detail}"
        )
    return (
        "Primary commit succeeded; sidecar publication is queued for the "
        f"`publications` lane.{error_detail}"
    )
