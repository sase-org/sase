"""Text formatters for the ``sase artifact`` CLI."""

from __future__ import annotations

import json
from collections.abc import Sequence

from sase.core.artifact_wire import (
    ARTIFACT_FILE_TYPES,
    ARTIFACT_FILE_TYPE_METADATA_KEY,
    ARTIFACT_FILE_TYPE_MISC,
    ArtifactDetailWire,
    ArtifactDoctorWire,
    ArtifactGraphWire,
    artifact_wire_to_json_dict,
)


def format_graph_text(graph: ArtifactGraphWire) -> str:
    lines = [
        f"root: {graph.root_id or '(full graph)'}",
        f"nodes: {len(graph.nodes)} shown / {graph.node_count} total",
        f"links: {len(graph.links)} shown / {graph.link_count} total",
        f"truncated: {str(graph.truncated).lower()}",
        f"limit: {graph.limit if graph.limit is not None else 'none'}",
    ]
    if not graph.links:
        lines.append("edges: none")
        return "\n".join(lines)

    lines.append("edges:")
    for link in graph.links:
        lines.append(f"  {link.source_id} -[{link.link_type}]-> {link.target_id}")
    return "\n".join(lines)


def format_node_table(nodes: object) -> str:
    node_rows = [_node_row(node) for node in _as_list(nodes)]
    if not node_rows:
        return "No artifacts found."
    return _format_table(
        ("KIND", "FILE TYPE", "ID", "TITLE", "PROVENANCE", "SOURCE", "UPDATED"),
        node_rows,
    )


def format_detail(detail: ArtifactDetailWire | object, *, artifact_id: str) -> str:
    data = _as_dict(detail)
    node = data.get("node")
    if not isinstance(node, dict):
        return f"Artifact not found: {artifact_id}"

    lines = [
        f"Artifact: {_field(node, 'display_title', artifact_id)}",
        f"  id: {_field(node, 'id')}",
        f"  kind: {_field(node, 'kind')}",
    ]
    file_type = _file_type_label(node)
    if file_type:
        lines.append(f"  file type: {file_type}")
    lines.append(f"  provenance: {_field(node, 'provenance')}")
    source = _source_label(node)
    if source:
        lines.append(f"  source: {source}")
    subtitle = _field(node, "subtitle")
    if subtitle:
        lines.append(f"  subtitle: {subtitle}")
    updated = _field(node, "updated_at")
    if updated:
        lines.append(f"  updated: {updated}")

    path_to_root = [item for item in _as_list(data.get("path_to_root")) if item]
    lines.extend(["", "Path to root:"])
    if path_to_root:
        lines.append("  " + " -> ".join(_field(item, "id") for item in path_to_root))
    else:
        lines.append("  none")

    lines.extend(["", "Children:"])
    children = _as_list(data.get("children"))
    if children:
        lines.append(_indent(format_node_table(children), "  "))
    else:
        lines.append("  none")

    lines.extend(["", "Outbound links:"])
    lines.extend(_format_link_groups(data.get("outbound_links"), direction="outbound"))

    lines.extend(["", "Inbound links:"])
    lines.extend(_format_link_groups(data.get("inbound_links"), direction="inbound"))

    lines.extend(["", "Payloads:"])
    payloads = _as_list(data.get("payloads"))
    if payloads:
        for payload in payloads:
            lines.append(
                "  "
                f"{_field(payload, 'payload_type')} "
                f"({_field(payload, 'provenance')}): "
                f"{_payload_summary(payload.get('payload'))}"
            )
    else:
        lines.append("  none")

    lines.extend(["", "Diagnostics:"])
    diagnostics = _as_list(data.get("diagnostics"))
    if diagnostics:
        lines.append(_indent(_format_issue_table(diagnostics), "  "))
    else:
        lines.append("  none")
    return "\n".join(lines)


def format_doctor(doctor: ArtifactDoctorWire | object) -> str:
    data = _as_dict(doctor)
    issues = _as_list(data.get("issues"))
    lines = [
        f"status: {'OK' if doctor_ok(data) else 'FAIL'}",
        f"issues: {len(issues)}",
    ]
    if issues:
        lines.append(_format_issue_table(issues))
    return "\n".join(lines)


def doctor_ok(doctor: ArtifactDoctorWire | object) -> bool:
    data = _as_dict(doctor)
    return bool(data.get("ok")) and not _as_list(data.get("issues"))


def _format_issue_table(issues: object) -> str:
    rows = [
        (
            _field(issue, "severity"),
            _field(issue, "issue_type"),
            _field(issue, "artifact_id"),
            _field(issue, "link_id"),
            _field(issue, "message"),
        )
        for issue in _as_list(issues)
    ]
    return _format_table(("SEVERITY", "TYPE", "ARTIFACT", "LINK", "MESSAGE"), rows)


def _format_link_groups(raw_links: object, *, direction: str) -> list[str]:
    links = _as_list(raw_links)
    if not links:
        return ["  none"]

    grouped: dict[str, list[dict[str, object]]] = {}
    for link in links:
        grouped.setdefault(_field(link, "link_type"), []).append(link)

    lines: list[str] = []
    for link_type in sorted(grouped):
        lines.append(f"  {link_type}:")
        for link in sorted(
            grouped[link_type],
            key=lambda item: (
                _field(item, "source_id"),
                _field(item, "target_id"),
                _field(item, "id"),
            ),
        ):
            if direction == "outbound":
                endpoint = f"{_field(link, 'source_id')} -> {_field(link, 'target_id')}"
            else:
                endpoint = f"{_field(link, 'source_id')} -> {_field(link, 'target_id')}"
            link_id = _field(link, "id")
            provenance = _field(link, "provenance")
            suffix = f" ({provenance})" if provenance else ""
            if link_id:
                lines.append(f"    {endpoint} [{link_id}]{suffix}")
            else:
                lines.append(f"    {endpoint}{suffix}")
    return lines


def _node_row(node: object) -> tuple[str, str, str, str, str, str, str]:
    data = _as_dict(node)
    return (
        _field(data, "kind"),
        _file_type_label(data),
        _field(data, "id"),
        _field(data, "display_title"),
        _field(data, "provenance"),
        _source_label(data),
        _field(data, "updated_at"),
    )


def _source_label(data: dict[str, object]) -> str:
    source_kind = _field(data, "source_kind")
    source_id = _field(data, "source_id")
    if source_kind and source_id:
        return f"{source_kind}:{source_id}"
    return source_kind or source_id


def _file_type_label(data: dict[str, object]) -> str:
    if _field(data, "kind") != "file":
        return ""
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return ARTIFACT_FILE_TYPE_MISC
    value = metadata.get(ARTIFACT_FILE_TYPE_METADATA_KEY)
    file_type = value if isinstance(value, str) else ARTIFACT_FILE_TYPE_MISC
    if file_type not in ARTIFACT_FILE_TYPES:
        return ARTIFACT_FILE_TYPE_MISC
    return file_type


def _payload_summary(value: object) -> str:
    if isinstance(value, dict):
        keys = ", ".join(sorted(str(key) for key in value))
        return f"object keys: {keys}" if keys else "object"
    if isinstance(value, list):
        return f"array items: {len(value)}"
    if value is None:
        return "null"
    text = json.dumps(value, sort_keys=True)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def _format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    header = "  ".join(
        headers[index].ljust(widths[index]) for index in range(len(headers))
    )
    divider = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(row[index].ljust(widths[index]) for index in range(len(row)))
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def _as_dict(value: object) -> dict[str, object]:
    data = artifact_wire_to_json_dict(value)
    return data if isinstance(data, dict) else {}


def _as_list(value: object) -> list[dict[str, object]]:
    data = artifact_wire_to_json_dict(value)
    if not isinstance(data, list):
        return []
    return [item if isinstance(item, dict) else {} for item in data]


def _field(data: object, name: str, default: str = "") -> str:
    if not isinstance(data, dict):
        data = _as_dict(data)
    value = data.get(name, default)
    return "" if value is None else str(value)
