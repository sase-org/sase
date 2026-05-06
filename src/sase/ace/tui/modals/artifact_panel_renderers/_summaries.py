"""Shared detail sections appended after kind-specific artifact rendering."""

from __future__ import annotations

from collections import Counter

from rich.text import Text

from sase.core.artifact_wire import (
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactPayloadWire,
)

from ..artifact_panel_state import (
    ArtifactDetailRenderContext,
    ArtifactRelationshipContext,
)
from ._common import append_kv, format_kind_counts


def render_relationship_context(
    context: ArtifactDetailRenderContext | None,
) -> Text | None:
    """Render the compact, already-loaded relationship context strip."""
    if context is None or not _has_relationship_context(context):
        return None

    text = Text()
    text.append("\nContext\n", style="bold")
    if context.parent_label:
        append_kv(text, "Parent", context.parent_label)
    elif context.path_labels:
        append_kv(text, "Path", " > ".join(context.path_labels[-3:]))

    if context.children_total_count or context.children_loaded_count:
        append_kv(
            text,
            "Children",
            _count_with_peers(
                context.children_loaded_count,
                context.children_total_count,
                context.child_labels,
            ),
        )

    _append_relationship_hint(text, "Created", context.outbound, "created")
    _append_relationship_hint(text, "Created by", context.inbound, "created")
    _append_relationship_hint(text, "Related", context.outbound, "related")
    _append_relationship_hint(text, "Related from", context.inbound, "related")
    _append_relationship_hint(text, "Worker", context.outbound, "worker")
    _append_relationship_hint(text, "Worker for", context.inbound, "worker")

    outbound_counts = _relationship_counts(context.outbound)
    if outbound_counts:
        append_kv(text, "Outbound", outbound_counts)
    inbound_counts = _relationship_counts(context.inbound)
    if inbound_counts:
        append_kv(text, "Inbound", inbound_counts)

    if context.type_counts:
        append_kv(
            text,
            "Types",
            ", ".join(
                f"{count.artifact_type}={count.total_count}"
                for count in context.type_counts[:6]
            ),
        )
    return text


def render_payload_summary(payloads: list[ArtifactPayloadWire]) -> Text | None:
    if not payloads:
        return None
    text = Text()
    text.append("\nPayloads\n", style="bold")
    counts = Counter(payload.payload_type for payload in payloads)
    for payload_type, count in sorted(counts.items()):
        text.append(f"- {payload_type}: {count}\n")
    return text


def render_link_summary(detail: ArtifactDetailWire) -> Text | None:
    if not detail.outbound_links and not detail.inbound_links and not detail.children:
        return None
    text = Text()
    text.append("\nGraph links\n", style="bold")
    append_kv(text, "Path to root", len(detail.path_to_root))
    append_kv(
        text,
        "Children",
        format_kind_counts(node.kind for node in detail.children),
    )
    _append_link_counts(text, "Outbound", detail.outbound_links)
    _append_link_counts(text, "Inbound", detail.inbound_links)
    return text


def render_diagnostics(detail: ArtifactDetailWire) -> Text | None:
    if not detail.diagnostics:
        return None
    text = Text()
    text.append("\nDiagnostics\n", style="bold yellow")
    for issue in detail.diagnostics[:8]:
        text.append(f"- {issue.severity}: {issue.message}\n")
    if len(detail.diagnostics) > 8:
        text.append(f"... {len(detail.diagnostics) - 8} more diagnostics\n")
    return text


def has_relationship_summary(context: ArtifactDetailRenderContext | None) -> bool:
    """Return whether the context strip already covers graph relationships."""
    if context is None:
        return False
    return bool(
        context.parent_label
        or context.path_labels
        or context.children_loaded_count
        or context.children_total_count
        or context.outbound
        or context.inbound
    )


def _append_link_counts(text: Text, label: str, links: list[ArtifactLinkWire]) -> None:
    if not links:
        append_kv(text, label, "0")
        return
    counts = Counter(link.link_type for link in links)
    append_kv(
        text,
        label,
        ", ".join(
            f"{link_type}={count}" for link_type, count in sorted(counts.items())
        ),
    )


def _has_relationship_context(context: ArtifactDetailRenderContext) -> bool:
    return bool(
        context.parent_label
        or context.path_labels
        or context.children_loaded_count
        or context.children_total_count
        or context.outbound
        or context.inbound
        or context.type_counts
    )


def _append_relationship_hint(
    text: Text,
    label: str,
    contexts: tuple[ArtifactRelationshipContext, ...],
    link_type: str,
) -> None:
    context = next(
        (item for item in contexts if item.link_type == link_type),
        None,
    )
    if context is None:
        return
    append_kv(
        text,
        label,
        _count_with_peers(
            context.loaded_count,
            context.total_count,
            context.peer_labels,
        ),
    )


def _relationship_counts(
    contexts: tuple[ArtifactRelationshipContext, ...],
) -> str:
    if not contexts:
        return ""
    return ", ".join(
        f"{context.link_type}={_summary_count(context.loaded_count, context.total_count)}"
        for context in contexts
    )


def _count_with_peers(
    loaded_count: int,
    total_count: int,
    peer_labels: tuple[str, ...],
) -> str:
    count = _summary_count(loaded_count, total_count)
    if not peer_labels:
        return count
    return f"{count} - {', '.join(peer_labels)}"


def _summary_count(loaded_count: int, total_count: int) -> str:
    if total_count > loaded_count:
        return f"{loaded_count}/{total_count}"
    return str(total_count or loaded_count)
