"""Persisting continuation-budget decisions and recording refusal metadata."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTINUATION_BUDGET_DECISION_FILENAME = "continuation_budget_decision.json"


def persist_decision(
    artifacts_dir: str | None,
    record: Mapping[str, Any],
) -> str | None:
    if not artifacts_dir:
        return None
    root = Path(artifacts_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / CONTINUATION_BUDGET_DECISION_FILENAME
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{CONTINUATION_BUDGET_DECISION_FILENAME}.",
            suffix=".tmp",
            dir=str(root),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(tmp_name, path)
        return str(path)
    except OSError:
        return None


def persist_projected_prompt(
    artifacts_dir: str | None,
    prompt: str,
    *,
    original_prompt: str,
    decision: Mapping[str, Any],
) -> str | None:
    if not artifacts_dir or prompt == original_prompt:
        return None
    if str(decision.get("kind") or "") != "compact":
        return None
    root = Path(artifacts_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "continuation_budget_prompt.md"
        path.write_text(prompt, encoding="utf-8")
        return str(path)
    except OSError:
        return None


def record_child_metadata(
    artifacts_dir: str | None,
    decision: Mapping[str, Any],
    *,
    decision_path: str | None,
    projected_prompt_bytes: int,
    projected_prompt_path: str | None,
) -> None:
    if not artifacts_dir:
        return
    fields: dict[str, Any] = {
        "continuation_budget_kind": decision.get("kind"),
        "continuation_budget_prompt_bytes": decision.get("estimated_prompt_bytes"),
        "continuation_budget_prompt_budget_bytes": decision.get("prompt_budget_bytes"),
        "continuation_budget_target_bytes": decision.get("target_prompt_bytes")
        or decision.get("prompt_budget_bytes"),
    }
    if decision_path:
        fields["continuation_budget_decision_path"] = decision_path
    fields["continuation_budget_projected_prompt_bytes"] = projected_prompt_bytes
    if projected_prompt_path:
        fields["continuation_budget_projected_prompt_path"] = projected_prompt_path
    disposition = decision.get("disposition")
    if isinstance(disposition, str) and disposition:
        fields["continuation_budget_disposition"] = disposition
    try:
        from sase.axe.run_agent_helpers import update_meta_field

        for key, value in fields.items():
            update_meta_field(artifacts_dir, key, value)
    except Exception:
        return


def record_delivery_refusal(
    env: Mapping[str, str],
    message: str,
    *,
    decision_path: str | None,
) -> None:
    try:
        from sase.monitor.continuation_delivery import (
            DELIVERY_ARTIFACTS_ENV,
            DELIVERY_IDENTITY_ENV,
            DELIVERY_KEY_ENV,
        )
        from sase.monitor.delivery import (
            apply_delivery_transition,
            load_delivery_record,
        )
    except Exception:
        return
    artifacts_dir = env.get(DELIVERY_ARTIFACTS_ENV)
    raw_key = env.get(DELIVERY_KEY_ENV)
    identity = env.get("SASE_AGENT_NAME") or env.get(DELIVERY_IDENTITY_ENV)
    if not artifacts_dir or not raw_key:
        return
    try:
        key_payload = json.loads(raw_key)
    except ValueError:
        return
    if not isinstance(key_payload, Mapping):
        return
    try:
        key = {
            "monitor_id": str(key_payload["monitor_id"]),
            "result_id": str(key_payload["result_id"]),
            "branch": str(key_payload["branch"]),
        }
    except KeyError:
        return
    try:
        record = load_delivery_record(artifacts_dir, key)
        current = str(record.get("disposition") or "") if record else ""
        target = "needs_attention" if current == "acknowledged" else "nonlaunchable"
        reason = f"context_budget_exceeded: {message}"
        if decision_path:
            reason = f"{reason} (decision: {decision_path})"
        apply_delivery_transition(
            artifacts_dir,
            key,
            target,
            selected_action="continue",
            reason=reason,
            reserved_identity=identity,
        )
    except Exception:
        return


def record_parent_refusal(
    env: Mapping[str, str],
    message: str,
    *,
    decision_path: str | None,
    prompt_path: str | None,
) -> None:
    parent_dir = _parent_artifacts_dir(env)
    if parent_dir is None:
        return
    try:
        meta_path = Path(parent_dir) / "agent_meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return
    if not isinstance(data, dict) or not data.get("monitor_id"):
        return
    try:
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(parent_dir, "monitor_followup_outcome", "not-launchable")
        update_meta_field(parent_dir, "monitor_followup_error", message)
        if decision_path:
            update_meta_field(
                parent_dir,
                "monitor_followup_budget_decision_path",
                decision_path,
            )
        if prompt_path:
            update_meta_field(parent_dir, "monitor_followup_prompt_path", prompt_path)
    except Exception:
        return


def _parent_artifacts_dir(env: Mapping[str, str]) -> str | None:
    try:
        from sase.agent._family_attach_types import FAMILY_ATTACH_ENV
    except Exception:
        return None
    raw = env.get(FAMILY_ATTACH_ENV)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    parent_dir = data.get("parent_artifacts_dir") if isinstance(data, dict) else None
    return parent_dir if isinstance(parent_dir, str) and parent_dir else None


def prompt_path(artifacts_dir: str | None) -> str | None:
    if not artifacts_dir:
        return None
    path = Path(artifacts_dir) / "agent_prompt.md"
    return str(path) if path.exists() else None
