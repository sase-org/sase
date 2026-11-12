"""Evidence helpers for the healer relaunch.

The public bundle writer lives in this already-private module so the
relaunch claim can use it without importing ``_``-prefixed names across
modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.auto_restart._healer_common import HealerTarget, read_json


def write_evidence(
    target: HealerTarget, *, verdict: Any, assembled: Any, episode_id: str | None
) -> tuple[str | None, dict[str, Any]]:
    """Preserve evidence before a relaunch; return the dir and bundle files.

    The ledger evidence directory is outside any artifacts dir, so it survives
    both named-row wipes and launcher-row resubmissions. The named-row restart
    path also copies this payload into its recovery bundle.
    """
    import datetime

    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.core.agent_auto_restart_wire import (
        auto_restart_witnesses_to_dict,
        recovery_verdict_to_dict,
    )
    from sase.core.time import get_timezone

    try:
        verdict_dict: dict[str, Any] = recovery_verdict_to_dict(verdict)
    except Exception:
        verdict_dict = {"signature": getattr(verdict, "signature", None)}
    try:
        witnesses_dict: dict[str, Any] = auto_restart_witnesses_to_dict(
            assembled.witnesses
        )
    except Exception:
        witnesses_dict = {}
    facts_dict: dict[str, Any] = dict(getattr(assembled.facts, "__dict__", {}) or {})
    done_dict = read_json(target.artifacts_dir / "done.json") or {}
    tail = _runner_log_tail(target)
    report_text: str | None = None
    try:
        report = target.artifacts_dir / "error_report.md"
        if report.is_file():
            report_text = report.read_text(encoding="utf-8")
    except OSError:
        report_text = None
    bundle: dict[str, Any] = {
        "done.json": done_dict,
        "failure_facts.json": facts_dict,
        "verdict.json": verdict_dict,
        "witnesses.json": witnesses_dict,
    }
    if episode_id is not None:
        bundle["episode_id.txt"] = episode_id
    if tail:
        bundle["runner_log_tail.txt"] = tail
    if report_text is not None:
        bundle["error_report.md"] = report_text
    stamp = datetime.datetime.now(get_timezone()).strftime("%Y%m%d%H%M%S")
    dest = ledger_mod.auto_restart_root() / "evidence" / f"{stamp}-{target.agent_name}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name, value in bundle.items():
            target_path = dest / Path(name).name
            if isinstance(value, str):
                target_path.write_text(value, encoding="utf-8")
            else:
                target_path.write_text(
                    json.dumps(value, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
    except OSError:
        return None, bundle
    return str(dest), bundle


def _runner_log_tail(target: HealerTarget) -> str:
    try:
        from sase.agent.auto_restart.history import FailedCandidate
        from sase.agent.auto_restart.history import candidate_log_tail

        candidate = FailedCandidate(
            source="done",
            name=target.agent_name,
            project=target.project,
            died_at=target.died_at,
            mtime=None,
            artifacts_dir=target.artifacts_dir,
            done=read_json(target.artifacts_dir / "done.json") or {},
            meta=read_json(target.artifacts_dir / "agent_meta.json") or {},
            bundle=None,
            log_path=None,
        )
        return candidate_log_tail(candidate)
    except Exception:
        return ""


__all__ = [
    "write_evidence",
]
