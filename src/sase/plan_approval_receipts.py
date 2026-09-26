"""Direct-approval receipts for gateless ``sase plan approve`` runs.

Every direct approval writes one JSON receipt at
``sase_subdir("plan_approvals")/<shard>/<name>.json``, keyed by the local
plan's shard and stem. The receipt is the direct route's durable "approved"
fact: it drives idempotency, miss history, and the ``sase plan list``
Approved section.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DirectApprovalReceipt:
    """Durable record of one direct (gateless) plan approval."""

    plan_path: str
    action: str
    approved_at: str
    source: str = "cli"
    route: str = "none"
    project: str = ""
    plan_archive_ref: str | None = None
    saved_plan_path: str | None = None
    coder_agent: str | None = None
    coder_pid: int | None = None
    coder_error: str | None = None
    agent_session: str | None = None
    retired_gate_id: str | None = None
    original_path: str | None = None
    replaced_coders: tuple[str, ...] = ()
    recovered_gate_id: str | None = None
    schema_version: int = 1


def receipt_path_for(local_plan: str | Path) -> Path:
    """Return the receipt path for a local ``~/.sase/plans`` plan file."""
    from sase.core.paths import sase_subdir

    plan = Path(local_plan).expanduser()
    shard = (
        plan.parent.name
        if len(plan.parent.name) == 6 and plan.parent.name.isdigit()
        else ""
    )
    name = plan.stem + ".json"
    base = sase_subdir("plan_approvals")
    if shard:
        return base / shard / name
    return base / name


def read_direct_approval_receipt(
    local_plan: str | Path,
) -> DirectApprovalReceipt | None:
    """Return the receipt for *local_plan*, or ``None`` when absent/corrupt."""
    path = receipt_path_for(local_plan)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return _receipt_from_dict(raw)


def write_direct_approval_receipt(receipt: DirectApprovalReceipt) -> Path:
    """Write *receipt* atomically and return its path."""
    path = receipt_path_for(receipt.plan_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(receipt)
    payload["schema_version"] = 1
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".receipt-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def delete_direct_approval_receipt(local_plan: str | Path) -> None:
    """Remove the receipt for *local_plan*; an absent receipt is not an error."""
    receipt_path_for(local_plan).unlink(missing_ok=True)


def iter_direct_approval_receipts() -> tuple[DirectApprovalReceipt, ...]:
    """Return every readable direct-approval receipt, newest first."""
    from sase.core.paths import sase_subdir

    base = sase_subdir("plan_approvals")
    if not base.is_dir():
        return ()
    receipts: list[tuple[float, DirectApprovalReceipt]] = []
    for path in sorted(base.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        receipt = _receipt_from_dict(raw)
        if receipt is None:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        receipts.append((mtime, receipt))
    receipts.sort(key=lambda item: item[0], reverse=True)
    return tuple(receipt for _, receipt in receipts)


def _receipt_from_dict(raw: dict[str, Any]) -> DirectApprovalReceipt | None:
    plan_path = raw.get("plan_path")
    action = raw.get("action")
    approved_at = raw.get("approved_at")
    if not isinstance(plan_path, str) or not plan_path:
        return None
    if not isinstance(action, str) or not action:
        return None
    if not isinstance(approved_at, str) or not approved_at:
        return None

    def _opt_str(key: str) -> str | None:
        value = raw.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _opt_int(key: str) -> int | None:
        value = raw.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    def _opt_str_tuple(value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )

    route = raw.get("route")
    project = raw.get("project")
    source = raw.get("source")
    return DirectApprovalReceipt(
        plan_path=plan_path,
        action=action,
        approved_at=approved_at,
        source=source.strip() if isinstance(source, str) and source.strip() else "cli",
        route=route.strip() if isinstance(route, str) and route.strip() else "none",
        project=project.strip() if isinstance(project, str) and project.strip() else "",
        plan_archive_ref=_opt_str("plan_archive_ref"),
        saved_plan_path=_opt_str("saved_plan_path"),
        coder_agent=_opt_str("coder_agent"),
        coder_pid=_opt_int("coder_pid"),
        coder_error=_opt_str("coder_error"),
        # legacy agent-family spelling: pre-rename receipts carry ``family``;
        # new writers emit only ``agent_session``.
        agent_session=_opt_str("agent_session") or _opt_str("family"),
        retired_gate_id=_opt_str("retired_gate_id"),
        original_path=_opt_str("original_path"),
        replaced_coders=_opt_str_tuple(raw.get("replaced_coders")),
        recovered_gate_id=_opt_str("recovered_gate_id"),
    )


__all__ = [
    "DirectApprovalReceipt",
    "delete_direct_approval_receipt",
    "iter_direct_approval_receipts",
    "read_direct_approval_receipt",
    "receipt_path_for",
    "write_direct_approval_receipt",
]
