"""Markdown rendering for continuation fork replay blocks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..common import format_text_fence
from ._util import BlockContent


def render_manifest(
    manifest: Mapping[str, Any],
    content_by_node_id: Mapping[str, BlockContent],
) -> str:
    blocks = [
        block
        for block in manifest.get("stable_blocks", [])
        if isinstance(block, Mapping)
    ]
    if not blocks:
        return ""
    lines = [
        "This fork uses versioned continuation replay. Blocks are stable, "
        "parent-first projections of exact continuation nodes; any historical "
        "source without recoverable node provenance is represented as an opaque "
        "legacy boundary.",
        "",
        f"- **Projection version:** `{manifest.get('projection_version', 'unknown')}`",
        f"- **Ordered nodes:** `{len(blocks)}`",
    ]
    omissions = [
        omission
        for omission in manifest.get("omissions", [])
        if isinstance(omission, Mapping)
    ]
    if omissions:
        lines.append("- **Omissions:**")
        lines.extend(f"  - {_format_omission(omission)}" for omission in omissions)

    for block in blocks:
        node_id = str(block.get("node_id") or "")
        content = content_by_node_id.get(node_id)
        lines.extend(["", *_render_block(block, content)])
    return "\n".join(lines).rstrip()


def _render_block(
    block: Mapping[str, Any],
    content: BlockContent | None,
) -> list[str]:
    block_id = str(block.get("block_id") or "unknown")
    node_id = str(block.get("node_id") or "unknown")
    kind = str(block.get("kind") or "unknown")
    parents = block.get("parent_ids")
    parent_text = ", ".join(f"`{item}`" for item in parents) if parents else "(none)"
    rows = [
        f"## Continuation Block `{block_id}`",
        "",
        f"- **Node:** `{node_id}`",
        f"- **Kind:** `{kind}`",
        f"- **Parents:** {parent_text}",
        f"- **Content:** `{block.get('content_ref') or 'unknown'}`",
    ]
    checkpoint_ref = block.get("checkpoint_ref")
    if isinstance(checkpoint_ref, str) and checkpoint_ref:
        rows.append(f"- **Checkpoint:** `{checkpoint_ref}`")
    intent_ref = block.get("intent_ref")
    if isinstance(intent_ref, str) and intent_ref:
        rows.append(f"- **Intent:** `{intent_ref}`")

    if content is None:
        rows.extend(
            [
                "",
                "### Missing Projection",
                "",
                "The continuation node was ordered by Rust, but no local "
                "projection content was available in this source set.",
            ]
        )
        return rows
    if content.kind == "agent_delta":
        rows.extend(["", *_render_agent_delta(content.payload)])
    elif content.kind == "monitor_result":
        rows.extend(["", *_render_monitor_result(content.payload)])
    else:
        rows.extend(["", *_render_legacy_boundary(content.payload)])
    return rows


def _render_agent_delta(payload: Mapping[str, Any]) -> list[str]:
    lines = [
        "### User",
        "",
        str(payload.get("authored_local_request") or "").strip(),
        "",
        "### Assistant",
        "",
    ]
    final_response = payload.get("final_response_text")
    if isinstance(final_response, str) and final_response:
        lines.append(final_response.strip())
    else:
        status = str(payload.get("status") or "unknown")
        lines.append(f"_No final response was captured for local status `{status}`._")
    return lines


def _render_monitor_result(payload: Mapping[str, Any]) -> list[str]:
    result = payload.get("result")
    selection = payload.get("selection")
    if isinstance(result, Mapping) and isinstance(selection, Mapping):
        from sase.monitor.result_projection import render_monitor_result_block

        return render_monitor_result_block(
            result,
            selection,
            output_text=(
                payload.get("output_text")
                if isinstance(payload.get("output_text"), str)
                else None
            ),
            output_log_path=(
                payload.get("output_log_path")
                if isinstance(payload.get("output_log_path"), str)
                else None
            ),
            command_text=(
                payload.get("command_text")
                if isinstance(payload.get("command_text"), str)
                else None
            ),
            heading_level=3,
        )

    lines = [
        "### Monitor Result",
        "",
        f"- **Monitor ID:** `{payload.get('monitor_id') or 'unknown'}`",
        f"- **Outcome:** `{payload.get('status') or 'unknown'}`",
    ]
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int):
        lines.append(f"- **Exit code:** `{exit_code}`")
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        lines.append(f"- **Cwd:** `{cwd}`")
    started_at = payload.get("started_at")
    if isinstance(started_at, str) and started_at:
        lines.append(f"- **Started:** `{started_at}`")
    finished_at = payload.get("finished_at")
    if isinstance(finished_at, str) and finished_at:
        lines.append(f"- **Finished:** `{finished_at}`")
    log_path = payload.get("log_path")
    proc_id = payload.get("monitor_id")
    if isinstance(log_path, str) and log_path:
        pointer = f"- **Retained output:** inspect `{log_path}`"
        if isinstance(proc_id, str) and proc_id:
            pointer += f" or run `sase monitor show {proc_id} --all-lines`"
        lines.append(pointer)
    command = payload.get("command")
    if isinstance(command, str) and command:
        lines.extend(["", "#### Command", "", format_text_fence(command)])
    return lines


def _render_legacy_boundary(payload: Mapping[str, Any]) -> list[str]:
    lines = [
        "### Opaque Legacy Boundary",
        "",
        "This source lacks recoverable continuation node provenance, so replay "
        "does not guess transcript turns from Markdown headings.",
        "",
        f"- **Source:** {payload.get('label') or 'unknown'}",
        f"- **Reason:** {payload.get('reason') or 'unknown'}",
    ]
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        lines.append(f"- **Transcript:** `{transcript}`")
    return lines


def _format_omission(omission: Mapping[str, Any]) -> str:
    kind = str(omission.get("kind") or "unknown")
    reason = str(omission.get("reason") or "unknown")
    node_id = omission.get("node_id")
    parent_id = omission.get("parent_id")
    details = []
    if isinstance(node_id, str) and node_id:
        details.append(f"node `{node_id}`")
    if isinstance(parent_id, str) and parent_id:
        details.append(f"parent `{parent_id}`")
    suffix = " · " + ", ".join(details) if details else ""
    return f"`{kind}`: {reason}{suffix}"
