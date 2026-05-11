"""Client-scoped notification suppression filters.

Suppression is a *projection* concern: a row is hidden from a particular
client (TUI, telegram, mobile, …) but remains in the underlying JSONL
store so other clients keep seeing it. Counts must therefore be
recomputed after filtering, since the Rust store reports unfiltered
counts.

The filter contract is defined by user config under
``notifications.suppress``::

    notifications:
      suppress:
        - client: tui
          types:
            - agent_completion

Each entry says: for this client, suppress notifications of these
semantic types. Type names are stable identifiers (``agent_completion``,
``plan_approval``, …) that map to concrete sender/action checks below,
so users don't need to know storage internals.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.notifications.models import Notification
from sase.notifications.priority import is_error, is_priority

log = logging.getLogger(__name__)


SemanticType = str
ClientName = str


def _is_agent_completion(n: Notification) -> bool:
    return n.sender == "user-agent" and n.action == "JumpToAgent"


def _is_agent_failure(n: Notification) -> bool:
    return n.sender == "user-agent" and n.action == "ViewErrorReport"


def _is_plan_approval(n: Notification) -> bool:
    return n.action == "PlanApproval"


def _is_user_question(n: Notification) -> bool:
    return n.action == "UserQuestion"


def _is_mentor_review(n: Notification) -> bool:
    return n.action == "JumpToMentorReview"


def _is_hitl(n: Notification) -> bool:
    return n.action == "HITL"


def _is_sync_result(n: Notification) -> bool:
    return n.action == "JumpToChangeSpec" and n.sender == "sync"


def _is_axe_error_digest(n: Notification) -> bool:
    return n.sender == "axe" and n.action == "ViewErrorReport"


_TYPE_PREDICATES: dict[SemanticType, Callable[[Notification], bool]] = {
    "agent_completion": _is_agent_completion,
    "agent_failure": _is_agent_failure,
    "plan_approval": _is_plan_approval,
    "user_question": _is_user_question,
    "mentor_review": _is_mentor_review,
    "hitl": _is_hitl,
    "sync_result": _is_sync_result,
    "axe_error_digest": _is_axe_error_digest,
}

KNOWN_SEMANTIC_TYPES: frozenset[SemanticType] = frozenset(_TYPE_PREDICATES)


def classify_notification(notification: Notification) -> set[SemanticType]:
    """Return all semantic type names that match ``notification``."""
    return {name for name, pred in _TYPE_PREDICATES.items() if pred(notification)}


@dataclass(frozen=True)
class SuppressionRule:
    """One ``client → types`` suppression entry from config."""

    client: ClientName
    types: frozenset[SemanticType]


@dataclass(frozen=True)
class NotificationCounts:
    """Recomputed counts after applying a client projection.

    Mirrors ``NotificationCountsWire`` but lives in this module so callers
    can use it without importing wire types. Convert with
    :meth:`to_wire` when handing back to wire-typed callers.
    """

    priority: int = 0
    errors: int = 0
    rest: int = 0
    muted: int = 0

    def to_wire(self) -> Any:
        from sase.core.notification_store_wire import NotificationCountsWire

        return NotificationCountsWire(
            priority=self.priority,
            errors=self.errors,
            rest=self.rest,
            muted=self.muted,
        )


def _normalize_client(name: Any) -> ClientName | None:
    if not isinstance(name, str):
        return None
    folded = name.strip().casefold()
    return folded or None


def _normalize_type(name: Any) -> SemanticType | None:
    if not isinstance(name, str):
        return None
    folded = name.strip().casefold()
    return folded or None


def parse_suppression_rules(config: Mapping[str, Any] | None) -> list[SuppressionRule]:
    """Parse ``notifications.suppress`` config into rule records.

    Accepts either a full merged config (``{"notifications": {...}}``) or
    a pre-extracted ``{"suppress": [...]}`` mapping.

    Malformed entries are logged at debug and skipped — bad config never
    raises, since a stale client config shouldn't break notification reads.
    Unknown client names are preserved as-is (case-folded) so future
    clients work without a parser update; unknown type names are dropped
    with a warning so typos don't silently suppress everything.
    """
    if config is None:
        return []

    raw_section: Any
    if "suppress" in config:
        raw_section = config.get("suppress")
    else:
        nested = config.get("notifications")
        if not isinstance(nested, Mapping):
            return []
        raw_section = nested.get("suppress")

    if raw_section is None:
        return []
    if not isinstance(raw_section, list):
        log.debug(
            "notifications.suppress must be a list, got %s", type(raw_section).__name__
        )
        return []

    rules: list[SuppressionRule] = []
    for index, entry in enumerate(raw_section):
        if not isinstance(entry, Mapping):
            log.debug(
                "skipping notifications.suppress[%d]: not a mapping (%s)",
                index,
                type(entry).__name__,
            )
            continue
        client = _normalize_client(entry.get("client"))
        if client is None:
            log.debug("skipping notifications.suppress[%d]: missing client", index)
            continue
        raw_types = entry.get("types")
        if not isinstance(raw_types, list) or not raw_types:
            log.debug(
                "skipping notifications.suppress[%d] (client=%s): types must be a non-empty list",
                index,
                client,
            )
            continue
        types: set[SemanticType] = set()
        for raw_type in raw_types:
            name = _normalize_type(raw_type)
            if name is None:
                log.debug(
                    "notifications.suppress[%d] (client=%s): skipping non-string type %r",
                    index,
                    client,
                    raw_type,
                )
                continue
            if name not in _TYPE_PREDICATES:
                log.warning(
                    "notifications.suppress[%d] (client=%s): unknown type %r — known: %s",
                    index,
                    client,
                    name,
                    sorted(_TYPE_PREDICATES),
                )
                continue
            types.add(name)
        if not types:
            log.debug(
                "skipping notifications.suppress[%d] (client=%s): no valid types",
                index,
                client,
            )
            continue
        rules.append(SuppressionRule(client=client, types=frozenset(types)))
    return rules


def suppressed_types_for_client(
    rules: Iterable[SuppressionRule], client: ClientName
) -> frozenset[SemanticType]:
    """Union of semantic types suppressed for ``client``."""
    target = _normalize_client(client)
    if target is None:
        return frozenset()
    out: set[SemanticType] = set()
    for rule in rules:
        if rule.client == target:
            out |= rule.types
    return frozenset(out)


def is_suppressed_for_client(
    notification: Notification,
    client: ClientName,
    *,
    rules: Iterable[SuppressionRule] | None = None,
    config: Mapping[str, Any] | None = None,
) -> bool:
    """Return True if ``notification`` should be hidden from ``client``.

    Pass either ``rules`` (already parsed) or ``config`` (raw merged
    config). When both are omitted, the merged repo+user config is
    loaded lazily.
    """
    resolved = _resolve_rules(rules, config)
    suppressed = suppressed_types_for_client(resolved, client)
    if not suppressed:
        return False
    return bool(classify_notification(notification) & suppressed)


def filter_notifications_for_client(
    notifications: Iterable[Notification],
    client: ClientName,
    *,
    rules: Iterable[SuppressionRule] | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[Notification]:
    """Return notifications visible to ``client`` after suppression."""
    resolved = _resolve_rules(rules, config)
    suppressed = suppressed_types_for_client(resolved, client)
    if not suppressed:
        return list(notifications)
    return [n for n in notifications if not (classify_notification(n) & suppressed)]


def compute_counts(notifications: Iterable[Notification]) -> NotificationCounts:
    """Recompute priority/errors/rest/muted counts from a list of rows.

    Mirrors the Rust ``counts_for`` logic: read or silent rows are
    excluded, muted rows go to ``muted``, errors to ``errors``, priority
    rows to ``priority``, and everything else to ``rest``.
    """
    priority = errors = rest = muted = 0
    for n in notifications:
        if n.read or n.silent:
            continue
        if n.muted:
            muted += 1
            continue
        if is_error(n):
            errors += 1
        elif is_priority(n):
            priority += 1
        else:
            rest += 1
    return NotificationCounts(priority=priority, errors=errors, rest=rest, muted=muted)


@dataclass(frozen=True)
class ClientNotificationSnapshot:
    """Result of ``read_notification_snapshot_for_client``.

    Carries the visible (post-filter) notifications, recomputed counts,
    and any snooze IDs that expired during the underlying snapshot read.
    The raw wire snapshot is preserved on ``raw`` for callers that need
    fields beyond the projection (stats, schema_version, …).
    """

    notifications: list[Notification]
    counts: NotificationCounts
    expired_ids: list[str]
    raw: Any


def read_notification_snapshot_for_client(
    client: ClientName,
    *,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
    rules: Iterable[SuppressionRule] | None = None,
    config: Mapping[str, Any] | None = None,
    snapshot_reader: Callable[..., Any] | None = None,
) -> ClientNotificationSnapshot:
    """Read the notification store and project it for ``client``.

    Wraps :func:`sase.notifications.store.read_notification_snapshot` so
    snooze-expiry semantics are preserved exactly. Counts are recomputed
    after filtering since the Rust store reports unfiltered counts.

    ``snapshot_reader`` is an injection point for tests; production
    callers should leave it ``None``.
    """
    if snapshot_reader is None:
        from sase.notifications.store import read_notification_snapshot

        snapshot_reader = read_notification_snapshot

    raw = snapshot_reader(
        include_dismissed=include_dismissed,
        expire_due_snoozes=expire_due_snoozes,
    )

    resolved = _resolve_rules(rules, config)
    visible = filter_notifications_for_client(
        list(raw.notifications), client, rules=resolved
    )
    counts = compute_counts(visible)
    expired = list(getattr(raw, "expired_ids", []) or [])
    return ClientNotificationSnapshot(
        notifications=visible, counts=counts, expired_ids=expired, raw=raw
    )


def _resolve_rules(
    rules: Iterable[SuppressionRule] | None,
    config: Mapping[str, Any] | None,
) -> list[SuppressionRule]:
    if rules is not None:
        return list(rules)
    if config is not None:
        return parse_suppression_rules(config)
    from sase.config.core import load_merged_config

    return parse_suppression_rules(load_merged_config())


__all__ = [
    "ClientNotificationSnapshot",
    "KNOWN_SEMANTIC_TYPES",
    "NotificationCounts",
    "SuppressionRule",
    "classify_notification",
    "compute_counts",
    "filter_notifications_for_client",
    "is_suppressed_for_client",
    "parse_suppression_rules",
    "read_notification_snapshot_for_client",
    "suppressed_types_for_client",
]
