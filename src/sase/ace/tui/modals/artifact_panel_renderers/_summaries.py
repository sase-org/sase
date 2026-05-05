"""Shared detail sections appended after kind-specific artifact rendering."""

from __future__ import annotations

from collections import Counter

from rich.text import Text

from sase.core.artifact_wire import (
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactPayloadWire,
)

from ._common import append_kv, format_kind_counts


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
