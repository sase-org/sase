"""Markdown rendering for continuation fork replay blocks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..common import format_text_fence
from ._util import (
    MAX_PROTECTED_LEGACY_BYTES,
    STRICT_EVIDENCE_POLICIES,
    BlockContent,
)


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
    prefix_reset = manifest.get("prefix_reset_reason")
    if isinstance(prefix_reset, str) and prefix_reset:
        lines.append(f"- **Prefix reset:** {prefix_reset}")
    reused = [
        attribution
        for attribution in manifest.get("branch_attribution", [])
        if isinstance(attribution, Mapping) and attribution.get("reused") is True
    ]
    if reused:
        lines.append(
            f"- **Shared ancestry reused:** `{len(reused)}` attributed node(s)"
        )
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
    elif content.kind == "checkpoint":
        rows.extend(["", *_render_checkpoint(content.payload.get("checkpoint_body"))])
    else:
        rows.extend(["", *_render_legacy_boundary(content.payload)])
    return rows


def _render_agent_delta(payload: Mapping[str, Any]) -> list[str]:
    authored = str(payload.get("authored_local_request") or "").strip()
    lines = [
        "### User",
        "",
        "**Protected user instruction.** Carry this request unless an explicit "
        "attributed update supersedes it.",
        "",
        authored,
    ]
    lines.extend(_render_materialized_segments(payload.get("materialized_segments")))
    checkpoint_body = payload.get("checkpoint_body")
    if isinstance(checkpoint_body, Mapping) and checkpoint_body:
        lines.extend(["", *_render_checkpoint(checkpoint_body)])
    lines.extend(["", "### Assistant", ""])
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
            selected_diagnostics_text=(
                payload.get("selected_diagnostics_text")
                if isinstance(payload.get("selected_diagnostics_text"), str)
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
    checkpoint_body = payload.get("checkpoint_body")
    if isinstance(checkpoint_body, Mapping) and checkpoint_body:
        lines.extend(["", *_render_checkpoint(checkpoint_body)])
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
    if payload.get("legacy_evidence_policy_conflict"):
        lines.extend(
            [
                "",
                "`legacy_evidence_policy_conflict`: opaque legacy content may "
                "contain raw evidence, so `none`/`file` policy cannot embed it. "
                "Inspect the original artifact explicitly.",
            ]
        )
        return lines
    protected = payload.get("protected_text")
    if payload.get("protected_content_omitted"):
        lines.extend(
            [
                "",
                "Protected legacy content exceeded the automatic-launch budget. "
                "Supply a checkpoint or inspect the original artifact.",
            ]
        )
        return lines
    if isinstance(protected, str) and protected:
        lines.extend(
            [
                "",
                "### Protected Legacy Content",
                "",
                "**Protected.** This opaque snapshot is included within budget "
                "and is not reconstructed into guessed local turns.",
                "",
                format_text_fence(protected),
            ]
        )
    return lines


def _render_checkpoint(body: object) -> list[str]:
    document = _checkpoint_document(body)
    if not document:
        return []
    lines = ["### Checkpoint", ""]
    author = document.get("author")
    if isinstance(author, Mapping):
        actor_kind = author.get("actor_kind") or "unknown"
        actor_id = author.get("actor_id") or "unknown"
        lines.append(f"- **Attribution:** `{actor_kind}` `{actor_id}`")
    kind = document.get("kind")
    if isinstance(kind, str) and kind:
        lines.append(f"- **Kind:** `{kind}`")
    field_specs = (
        ("objective", "Objective", False),
        ("constraints", "Constraints", True),
        ("findings", "Findings", False),
        ("unresolved_decisions", "Unresolved decisions", True),
        ("remaining_work", "Remaining work", True),
    )
    rendered_any = False
    for key, title, protected in field_specs:
        value = _checkpoint_field_text(document.get(key))
        if not value:
            continue
        rendered_any = True
        heading = f"#### {title}"
        lines.extend(["", heading, ""])
        if protected:
            lines.extend(
                [
                    "**Protected.** Carry this decision or remaining work unless "
                    "an explicit attributed update supersedes it.",
                    "",
                ]
            )
        lines.append(value)
    if not rendered_any:
        inner = document.get("payload")
        if isinstance(inner, Mapping) and inner:
            lines.extend(["", format_text_fence(_mapping_preview(inner))])
    return lines


def _render_materialized_segments(raw_segments: object) -> list[str]:
    if not isinstance(raw_segments, list):
        return []
    lines: list[str] = []
    for segment in raw_segments:
        if not isinstance(segment, Mapping):
            continue
        provenance = str(segment.get("provenance") or "")
        text = segment.get("text")
        if provenance == "local_authored" or not isinstance(text, str) or not text:
            continue
        source_ref = segment.get("source_ref")
        protected = provenance == "local_materialized" and _looks_like_gate(
            source_ref if isinstance(source_ref, str) else None
        )
        lines.extend(["", "### Local Material", ""])
        if isinstance(source_ref, str) and source_ref:
            lines.append(f"- **Source:** `{source_ref}`")
        lines.append(f"- **Provenance:** `{provenance or 'unknown'}`")
        if protected:
            lines.extend(
                [
                    "",
                    "**Protected gate instruction.** Carry this instruction "
                    "unless an explicit attributed update supersedes it.",
                ]
            )
        lines.extend(["", format_text_fence(text)])
    return lines


def _checkpoint_document(body: object) -> Mapping[str, Any]:
    if not isinstance(body, Mapping):
        return {}
    inner = body.get("payload")
    if isinstance(inner, Mapping) and not any(
        key in body
        for key in (
            "objective",
            "constraints",
            "findings",
            "unresolved_decisions",
            "remaining_work",
        )
    ):
        merged = dict(inner)
        if "kind" in body and "kind" not in merged:
            merged["kind"] = body["kind"]
        if "author" in body and "author" not in merged:
            merged["author"] = body["author"]
        return merged
    return body


def _checkpoint_field_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]
        return "\n".join(f"- {item}" for item in items)
    return ""


def _looks_like_gate(source_ref: str | None) -> bool:
    if not source_ref:
        return False
    lowered = source_ref.lower()
    return "gate" in lowered


def _mapping_preview(payload: Mapping[str, Any]) -> str:
    import json

    return json.dumps(dict(payload), indent=2, sort_keys=True)


def prepare_legacy_payload(
    payload: dict[str, Any],
    *,
    evidence_policy: str | None,
) -> tuple[dict[str, Any], dict[str, str | None] | None]:
    """Apply evidence-policy and budget rules to opaque legacy content."""

    prepared = dict(payload)
    protected = prepared.get("protected_text")
    may_contain_raw = bool(prepared.get("may_contain_raw_evidence"))
    policy = evidence_policy or prepared.get("evidence_policy")
    if (
        may_contain_raw
        and isinstance(policy, str)
        and policy in STRICT_EVIDENCE_POLICIES
    ):
        has_protected_user = bool(
            isinstance(protected, str)
            and protected
            and prepared.get("has_protected_user_content")
        )
        prepared.pop("protected_text", None)
        if has_protected_user:
            prepared["legacy_evidence_policy_conflict"] = True
            return prepared, {
                "kind": "legacy_evidence_policy_conflict",
                "node_id": prepared.get("node_id")
                if isinstance(prepared.get("node_id"), str)
                else None,
                "parent_id": None,
                "reason": (
                    "opaque legacy content mixes protected instructions with raw "
                    "evidence under none/file policy"
                ),
            }
        return prepared, None
    if not isinstance(protected, str) or not protected:
        return prepared, None
    if len(protected.encode("utf-8")) > MAX_PROTECTED_LEGACY_BYTES:
        prepared.pop("protected_text", None)
        prepared["protected_content_omitted"] = True
        return prepared, {
            "kind": "protected_content_over_budget",
            "node_id": prepared.get("node_id")
            if isinstance(prepared.get("node_id"), str)
            else None,
            "parent_id": None,
            "reason": (
                "opaque legacy protected content exceeds the automatic-launch budget"
            ),
        }
    return prepared, None


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
