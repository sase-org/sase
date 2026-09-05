"""Transaction, reveal-ladder, and hydration flow for ``$`` link-follow."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from sase.ace.link_reveal import is_link_reveal_active
from sase.core.artifact_entry_target import ArtifactEntryTarget

from ..relations.artifact_links import parse_link_ref
from ..widgets.artifacts.entry_navigation import (
    HydrationOutcome,
    HydrationResult,
    LinkRequestState,
)
from ._link_follow_helpers import pane_is_loading, pane_label
from ._link_follow_ladder import (
    RUNG_FOLD,
    RUNG_TOAST,
    capture_query_origin,
    end_link_follow_pinning,
    pane_limit_query,
    selected_follow_outcome,
    try_reveal_rung,
)
from ._link_follow_types import (
    LinkFollowTransaction,
    LinkTrailHop,
    record_link_follow_outcome,
)


class LinkFollowTransactionMixin:
    """Handle pending link-follow requests and async hydration."""

    _link_follow_generation: int
    _link_follow_transaction: LinkFollowTransaction | None
    _link_follow_dispatching: bool
    _link_hydration_waiters: dict[tuple[str, str], int]
    _link_hydration_in_flight: set[tuple[str, str]]
    _link_trail_guard: bool

    def _begin_link_follow_transaction(
        self,
        ref: str,
        target: ArtifactEntryTarget,
        origin: LinkTrailHop,
    ) -> int:
        self._link_follow_generation += 1
        generation = self._link_follow_generation
        pane = self._artifacts_entry_navigator(  # type: ignore[attr-defined]
            target.pane_id
        )
        origin_query, origin_target = capture_query_origin(self, pane, target.pane_id)
        self._link_follow_transaction = LinkFollowTransaction(
            generation=generation,
            ref=ref,
            target=target,
            origin=origin,
            rung=RUNG_FOLD,
            origin_query=origin_query,
            origin_target=origin_target,
        )
        return generation

    def _cancel_link_follow_transaction(self) -> None:
        """Invalidate any open transaction so its later completion is ignored."""
        self._link_follow_transaction = None
        ender = getattr(self, "_end_collapsed_query_transitions", None)
        if callable(ender):
            ender()

    def _complete_link_follow_request(
        self,
        generation: int | None,
        state: LinkRequestState,
    ) -> None:
        """Shared completion seam entry point: reported by a pane's request.

        A no-op while :attr:`_link_follow_dispatching` is set -- that means
        this report arrived synchronously, reentrantly, from within the very
        call that is about to receive *state* as a plain return value, so
        the dispatching call site handles it directly instead.
        """
        if generation is None or self._link_follow_dispatching:
            return
        self._handle_link_follow_outcome(generation, state)

    def _handle_link_follow_outcome(
        self,
        generation: int,
        state: LinkRequestState,
    ) -> None:
        transaction = self._link_follow_transaction
        if transaction is None or transaction.generation != generation:
            return  # a stale or already-finalized generation
        if state is LinkRequestState.PENDING:
            return  # keep the transaction open for a later report
        if state is LinkRequestState.SELECTED:
            self._link_follow_transaction = None
            record_link_follow_outcome(selected_follow_outcome(transaction.rung))
            self._finalize_selected_link_follow(transaction)
            return
        if state is LinkRequestState.FAILED:
            self._link_follow_transaction = None
            end_link_follow_pinning(self)
            record_link_follow_outcome("failed")
            self._notify_link_follow_failed(transaction)  # type: ignore[attr-defined]
            return
        self._handle_missing_link_follow(transaction)

    def _handle_missing_link_follow(self, transaction: LinkFollowTransaction) -> None:
        """Walk the remaining reveal rungs, then hydrate or report absence."""
        pane = self._artifacts_entry_navigator(  # type: ignore[attr-defined]
            transaction.target.pane_id
        )
        if pane is not None and not pane_is_loading(pane):
            rung = transaction.rung
            while rung < RUNG_TOAST:
                if try_reveal_rung(self, pane, transaction, rung):
                    retried = replace(transaction, rung=rung + 1)
                    self._link_follow_transaction = retried
                    req = self._request_artifacts_target  # type: ignore[attr-defined]
                    state = req(
                        transaction.target,
                        generation=transaction.generation,
                    )
                    self._handle_link_follow_outcome(transaction.generation, state)
                    return
                rung += 1
            if not transaction.hydrated and self._begin_link_hydration(
                pane, transaction
            ):
                return
        self._link_follow_transaction = None
        end_link_follow_pinning(self)
        record_link_follow_outcome("missing")
        self._notify_missing_in_inventory(  # type: ignore[attr-defined]
            transaction.ref,
            transaction.target,
        )

    def _begin_link_hydration(
        self,
        pane: Any,
        transaction: LinkFollowTransaction,
    ) -> bool:
        """Start (or coalesce into) one blocking direct-lookup for *transaction*.

        Keyed by (pane, ref) so a repeated request while a lookup is
        already running never spawns a second one -- a newer generation
        simply supersedes the old waiter by overwriting the map entry, so
        whichever transaction is live when the single in-flight lookup
        resolves is the one :meth:`_complete_link_hydration` applies it
        to. Returns ``False`` when the pane has no direct source, the ref
        cannot be parsed, or no event loop is available to run the
        lookup, so the caller falls back to the honest toast.
        """
        hydrate = getattr(pane, "hydrate_ref", None)
        if not callable(hydrate):
            return False
        parsed = parse_link_ref(transaction.ref)
        if parsed is None:
            return False
        kind, payload = parsed
        pane_id = transaction.target.pane_id
        key = (pane_id, transaction.ref)
        self._link_follow_transaction = replace(transaction, hydrated=True)
        waiters = self._link_hydration_waiters_map()
        waiters[key] = transaction.generation
        in_flight = self._link_hydration_in_flight_set()
        if key in in_flight:
            return True  # already running; the newer generation now owns it
        from ..util.pump_tasks import spawn_pump_free_task

        async def _runner() -> None:
            try:
                result = await asyncio.to_thread(hydrate, kind, payload)
            except Exception as exc:  # noqa: BLE001 - mapped to FAILED below
                result = HydrationResult(HydrationOutcome.FAILED, error=str(exc))
            in_flight.discard(key)
            self._complete_link_hydration(key, pane_id, result)

        task = spawn_pump_free_task(
            self,
            _runner(),
            name="sase-link-hydration",
            registry_attr="_link_hydration_tasks",
        )
        if task is None:
            del waiters[key]
            return False
        in_flight.add(key)
        return True

    def _link_hydration_waiters_map(self) -> dict[tuple[str, str], int]:
        waiters = getattr(self, "_link_hydration_waiters", None)
        if not isinstance(waiters, dict):
            waiters = {}
            self._link_hydration_waiters = waiters
        return waiters

    def _link_hydration_in_flight_set(self) -> set[tuple[str, str]]:
        in_flight = getattr(self, "_link_hydration_in_flight", None)
        if not isinstance(in_flight, set):
            in_flight = set()
            self._link_hydration_in_flight = in_flight
        return in_flight

    def _complete_link_hydration(
        self,
        key: tuple[str, str],
        pane_id: str,
        result: HydrationResult,
    ) -> None:
        """Apply one resolved hydration lookup, unless it has been superseded.

        Re-reads the live transaction rather than trusting anything
        captured before the lookup's ``await`` -- cancellation, a second
        follow, user navigation, or teardown may have replaced or cleared
        it while the lookup ran off the pump.
        """
        waiters = self._link_hydration_waiters_map()
        generation = waiters.pop(key, None)
        transaction = self._link_follow_transaction
        if (
            transaction is None
            or generation is None
            or transaction.generation != generation
            or transaction.ref != key[1]
            or transaction.target.pane_id != pane_id
        ):
            return  # superseded by a later follow, cancellation, or teardown
        if result.outcome is HydrationOutcome.FETCHED:
            self._install_hydrated_link_row(pane_id, transaction, result.payload)
            return
        self._link_follow_transaction = None
        end_link_follow_pinning(self)
        if result.outcome is HydrationOutcome.ABSENT:
            notify = self._notify_dangling_link_ref  # type: ignore[attr-defined]
            notify(transaction.ref)
            return
        if result.outcome is HydrationOutcome.FAILED:
            self._notify_link_follow_failed(transaction)  # type: ignore[attr-defined]
            return
        self._notify_missing_in_inventory(  # type: ignore[attr-defined]
            transaction.ref,
            transaction.target,
        )

    def _install_hydrated_link_row(
        self,
        pane_id: str,
        transaction: LinkFollowTransaction,
        payload: Any,
    ) -> None:
        """Merge one fetched row on the UI thread, then re-enter the ladder."""
        pane = self._artifacts_entry_navigator(pane_id)  # type: ignore[attr-defined]
        installer = (
            getattr(pane, "install_hydrated_row", None) if pane is not None else None
        )
        new_target = installer(payload) if callable(installer) else None
        if new_target is None:
            self._link_follow_transaction = None
            end_link_follow_pinning(self)
            self._notify_link_follow_failed(transaction)  # type: ignore[attr-defined]
            return
        retried = replace(transaction, target=new_target, rung=RUNG_FOLD)
        self._link_follow_transaction = retried
        state = self._request_artifacts_target(  # type: ignore[attr-defined]
            new_target,
            generation=transaction.generation,
        )
        self._handle_link_follow_outcome(transaction.generation, state)

    def _finalize_selected_link_follow(
        self, transaction: LinkFollowTransaction
    ) -> None:
        """Record the trail hop and refresh the rail exactly once."""
        previous_guard = self._link_trail_guard  # type: ignore[attr-defined]
        self._link_trail_guard = True
        try:
            self._record_link_trail(transaction.origin)  # type: ignore[attr-defined]
            note = getattr(self, "_note_artifacts_selection_for_link_trail", None)
            if callable(note):
                # Sync the last-observed-selection baseline while guarded,
                # so a later unguarded navigation doesn't mistake this
                # follow's own landing for user navigation and wipe the
                # hop just recorded above.
                note()
        finally:
            self._link_trail_guard = previous_guard
        end_link_follow_pinning(self)
        pane = self._artifacts_entry_navigator(  # type: ignore[attr-defined]
            transaction.target.pane_id
        )
        current = pane_limit_query(pane) or ""
        reveal = getattr(self, "_link_reveals", {}).get(transaction.target.pane_id)
        if is_link_reveal_active(
            reveal,
            pane_id=transaction.target.pane_id,
            current_canonical=current,
        ):
            self.notify(  # type: ignore[attr-defined]
                f"Revealed {transaction.ref} — press ^ to restore your query",
            )
        self.refresh_link_rail()  # type: ignore[attr-defined]

    def _notify_link_follow_failed(self, transaction: LinkFollowTransaction) -> None:
        self.notify(  # type: ignore[attr-defined]
            f"Failed to load {pane_label(transaction.target)} for {transaction.ref}",
            severity="error",
        )


__all__ = ["LinkFollowTransactionMixin"]
