"""Shared Git object-store maintenance for managed workspaces."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.core.git_object_sharing import (
    MUTATION_CONTEXT_EXISTING_REUSE,
    MUTATION_CONTEXT_MAINTENANCE_COMPACT,
    MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE,
    MUTATION_CONTEXT_MAINTENANCE_REPAIR,
    MUTATION_CONTEXT_NEW_CHECKOUT,
)
from sase.workspace_provider._git_objects_git import (
    checkout_object_bytes as _checkout_object_bytes,
    clear_borrower_config as _clear_borrower_config,
    configure_borrower_for_sharing as _configure_borrower_for_sharing,
    configure_primary_for_sharing as _configure_primary_for_sharing,
    fsck_connectivity as _fsck_connectivity,
    git_object_dir as _git_object_dir,
    is_git_checkout as _is_git_checkout,
    run_git as _run_git,
    status_porcelain as _status_porcelain,
)
from sase.workspace_provider._git_objects_model import (
    AlternateState,
    GitObjectSharingError,
    ObjectSharingResult,
)
from sase.workspace_provider._git_objects_state import (
    apply_alternates_plan as _apply_alternates_plan,
    classify_alternate_state as _classify_alternate_state,
    sharing_plan as _sharing_plan,
    state_from_plan as _state_from_plan,
    with_alternate_rollback as _with_alternate_rollback,
)
from sase.workspace_provider._utils_git import command_output


def git_object_dir(checkout_dir: str) -> Path:
    """Return the resolved Git object directory for *checkout_dir*."""

    return _git_object_dir(checkout_dir)


def configure_primary_for_sharing(primary_checkout_dir: str) -> None:
    """Protect a primary checkout whose objects are borrowed by workspaces."""

    _configure_primary_for_sharing(primary_checkout_dir)


def classify_alternate_state(
    checkout_dir: str,
    *,
    primary_checkout_dir: str,
) -> AlternateState:
    """Inspect and classify a checkout's alternates dependency."""

    return _classify_alternate_state(
        checkout_dir,
        primary_checkout_dir=primary_checkout_dir,
    )


def checkout_object_bytes(checkout_dir: str) -> int:
    return _checkout_object_bytes(checkout_dir)


def is_git_checkout(checkout_dir: str) -> bool:
    return _is_git_checkout(checkout_dir)


def status_porcelain(checkout_dir: str) -> subprocess.CompletedProcess[str]:
    return _status_porcelain(checkout_dir)


def fsck_connectivity(checkout_dir: str) -> None:
    _fsck_connectivity(checkout_dir)


def _apply_install_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    mutation_context: str,
    checkout_clean: bool | None = None,
    fresh_claim_status: str | None = None,
    fresh_occupant_status: str | None = None,
) -> AlternateState:
    """Install, repoint, or deliberately preserve one borrower's alternate."""

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    plan = _sharing_plan(
        primary,
        checkout,
        operation="install",
        mutation_context=mutation_context,
        checkout_clean=checkout_clean,
        fresh_claim_status=fresh_claim_status,
        fresh_occupant_status=fresh_occupant_status,
    )
    if str(plan["action"]) == "fail":
        _apply_alternates_plan(plan)
    planned = _state_from_plan(plan)
    primary_objects = Path(str(plan["expected_object_dir"]))
    dependency_mutation = bool(plan.get("dependency_mutation"))
    # Only record borrower metadata for a dependency that is, or is about to
    # become, the configured primary. When the core preserves a dependency it
    # chose not to repoint, writing our primary into the borrower's config
    # would leave the two disagreeing, and a later classification would read
    # the preserved alternate as foreign.
    configure_metadata = dependency_mutation or planned.status == "expected"

    if not dependency_mutation:
        # The core left the dependency exactly as it found it, so there is no
        # rewrite to verify. Proving connectivity here would fail the caller
        # over a pre-existing condition this call deliberately did not touch --
        # ordinary reuse defers a broken dependency to maintenance repair
        # rather than repointing it underneath a running agent.
        if configure_metadata:
            configure_primary_for_sharing(primary)
            _configure_borrower_for_sharing(
                checkout,
                primary_checkout_dir=primary,
                primary_object_dir=primary_objects,
            )
        return planned

    fsck_connectivity(primary)
    configure_primary_for_sharing(primary)
    _apply_alternates_plan(plan)
    _configure_borrower_for_sharing(
        checkout,
        primary_checkout_dir=primary,
        primary_object_dir=primary_objects,
    )
    fsck_connectivity(checkout)
    return classify_alternate_state(checkout, primary_checkout_dir=primary)


def _install_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> AlternateState:
    return _with_alternate_rollback(
        checkout_dir,
        lambda: _apply_install_sase_alternate(
            primary_checkout_dir,
            checkout_dir,
            mutation_context=MUTATION_CONTEXT_NEW_CHECKOUT,
        ),
    )


def ensure_sase_alternate(primary_checkout_dir: str, checkout_dir: str) -> None:
    """Ensure one freshly materialized checkout borrows the primary objects."""

    state = _install_sase_alternate(primary_checkout_dir, checkout_dir)
    if state.status != "expected":
        raise GitObjectSharingError(
            f"alternate for {checkout_dir} is {state.status}, expected shared"
        )


def ensure_sase_alternate_for_reuse(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> None:
    """Validate object sharing while reusing an existing checkout.

    ``sase_core`` never rewrites an existing checkout's object dependency for
    ordinary reuse: a usable one is preserved as it stands and a broken one is
    refused so explicit maintenance can repair it deliberately. A preserved
    dependency is therefore a success -- the checkout keeps working, it just
    does not get repointed underneath an agent that is about to use it.
    """

    checkout = checkout_dir.rstrip("/")
    status = status_porcelain(checkout)
    if status.returncode != 0:
        detail = command_output(status) or "status failed"
        raise GitObjectSharingError(
            "could not prove reusable checkout status before Git object-sharing "
            f"validation: {detail}"
        )
    clean = not status.stdout.strip()
    plan = _sharing_plan(
        primary_checkout_dir,
        checkout,
        operation="install",
        mutation_context=MUTATION_CONTEXT_EXISTING_REUSE,
        checkout_clean=clean,
    )
    if str(plan["action"]) == "fail":
        _apply_alternates_plan(plan)
    if str(plan["action"]) != "none":
        raise GitObjectSharingError(
            "ordinary checkout reuse attempted to mutate Git object-sharing "
            "state; leaving checkout unchanged"
        )


def _remove_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    mutation_context: str,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> None:
    """Remove the SASE-owned alternate marker from one borrower."""

    plan = _sharing_plan(
        primary_checkout_dir,
        checkout_dir,
        operation="remove",
        mutation_context=mutation_context,
        fresh_claim_status=fresh_claim_status,
        fresh_occupant_status=fresh_occupant_status,
    )
    _apply_alternates_plan(plan)
    _clear_borrower_config(checkout_dir.rstrip("/"))


def compact_checkout(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> ObjectSharingResult:
    """Install sharing, repack local-only objects, and verify connectivity.

    The caller passes what it freshly observed about the workspace's claim and
    occupant; ``sase_core`` refuses to compact unless both are clear.
    """

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    fsck_connectivity(primary)
    status = status_porcelain(checkout)
    clean = status.returncode == 0 and not status.stdout.strip()

    def _compact() -> None:
        _apply_install_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_COMPACT,
            checkout_clean=clean,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        _run_git(checkout, ["repack", "-a", "-d", "-l"], check=True)
        _run_git(checkout, ["prune-packed"], check=False)
        fsck_connectivity(checkout)

    _with_alternate_rollback(checkout, _compact)
    after = checkout_object_bytes(checkout)
    return ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="compacted",
    )


def repair_shared_checkout(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> ObjectSharingResult:
    """Repoint a SASE-owned borrower to the current primary and verify it.

    This is the deliberate maintenance repair that ordinary reuse defers to,
    so ``sase_core`` requires freshly observed clear claim and occupant
    readings before it will rewrite the dependency.
    """

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    fsck_connectivity(primary)

    def _repair() -> None:
        _apply_install_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_REPAIR,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        fsck_connectivity(checkout)

    _with_alternate_rollback(checkout, _repair)
    after = checkout_object_bytes(checkout)
    return ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="repaired",
    )


def dissociate_checkout(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> ObjectSharingResult:
    """Copy SASE-borrowed objects locally, remove that alternate, and verify.

    Both the repoint and the removal are maintenance mutations, so each is
    planned with the caller's freshly observed claim and occupant readings.
    """

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)

    def _dissociate() -> None:
        _apply_install_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        fsck_connectivity(checkout)
        _run_git(checkout, ["repack", "-a", "-d"], check=True)
        _remove_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        fsck_connectivity(checkout)

    _with_alternate_rollback(checkout, _dissociate)
    after = checkout_object_bytes(checkout)
    return ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="dissociated",
    )


__all__ = [
    "GitObjectSharingError",
    "checkout_object_bytes",
    "classify_alternate_state",
    "compact_checkout",
    "configure_primary_for_sharing",
    "dissociate_checkout",
    "ensure_sase_alternate",
    "ensure_sase_alternate_for_reuse",
    "fsck_connectivity",
    "git_object_dir",
    "is_git_checkout",
    "repair_shared_checkout",
    "status_porcelain",
]
