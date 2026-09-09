"""Singleton-to-family follow promotion derivation for fleet agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.dispatch.follow_store import FollowStoreSnapshot

from ._fleet_agents_payload import host_payloads, summary_payloads
from ._fleet_agents_scalars import locator_id, mapping, optional_str

PromotionIdentity = tuple[str, str, str]


def followed_batch_family_promotions(
    snapshot: FollowStoreSnapshot | None,
    followed_response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Derive safe singleton-to-family follow promotions from hydrated rows."""
    if (
        snapshot is None
        or followed_response is None
        or followed_response.get("disabled")
    ):
        return ()

    family_locators = _family_locators_by_identity(followed_response)
    if not family_locators:
        return ()

    promotions: list[dict[str, Any]] = []
    promoted_sources: set[str] = set()
    for record in snapshot.active_records:
        if record.get("created_by") != "explicit":
            continue
        source = mapping(record.get("logical_locator"))
        if not source or _locator_family_id(source):
            continue
        source_identity = _promotion_identity(source)
        if source_identity is None:
            continue
        matches = family_locators.get(source_identity)
        if matches is None or len(matches) != 1:
            continue
        target = next(iter(matches.values()))
        source_id = locator_id(source)
        if source_id in promoted_sources or source_id == locator_id(target):
            continue
        promotions.append(
            {
                "schema_version": 1,
                "from": dict(source),
                "to": dict(target),
            }
        )
        promoted_sources.add(source_id)
    return tuple(promotions)


def _family_locators_by_identity(
    response: Mapping[str, Any],
) -> dict[PromotionIdentity, dict[str, dict[str, Any]]]:
    locators: dict[PromotionIdentity, dict[str, dict[str, Any]]] = {}
    for host in host_payloads(response):
        for summary in summary_payloads(host):
            locator = mapping(summary.get("logical_locator"))
            if not locator or not _locator_family_id(locator):
                continue
            identity = _promotion_identity(locator)
            if identity is None:
                continue
            locators.setdefault(identity, {})[locator_id(locator)] = dict(locator)
    return locators


def _promotion_identity(locator: Mapping[str, Any]) -> PromotionIdentity | None:
    project = mapping(locator.get("project"))
    origin = mapping(project.get("origin"))
    installation_id = optional_str(
        origin.get("installation_id"),
        locator.get("origin_installation_id"),
        locator.get("installation_id"),
    )
    project_id = optional_str(project.get("project_id"), locator.get("project_id"))
    agent_id = optional_str(locator.get("agent_id"))
    if installation_id is None or project_id is None or agent_id is None:
        return None
    return (installation_id, project_id, agent_id)


def _locator_family_id(locator: Mapping[str, Any]) -> str | None:
    return optional_str(locator.get("family_id"))
