"""Provenance helpers for the healer relaunch.

Public helpers live in this already-private module so the relaunch claim
can use them without importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

from typing import Any

from sase.agent.auto_restart._healer_common import HealerTarget


def attach_provenance(
    plan: Any,
    target: HealerTarget,
    *,
    verdict: Any,
    episode_id: str | None,
    lineage_root: str,
    ledger_key: str,
    evidence_dir: str | None,
    evidence_files: dict[str, Any] | None = None,
    witnesses: Any,
    facts: Any,
) -> None:
    from sase.agent.auto_restart.provenance import PROVENANCE_ENV

    env = provenance_env(
        target,
        verdict=verdict,
        episode_id=episode_id,
        lineage_root=lineage_root,
        ledger_key=ledger_key,
        evidence_dir=evidence_dir,
        evidence_files=evidence_files,
        witnesses=witnesses,
        facts=facts,
    )
    try:
        segment_envs = plan.force_reuse_plan.segment_envs
        for index, overlay in enumerate(segment_envs):
            merged = dict(overlay or {})
            merged.setdefault(PROVENANCE_ENV, env[PROVENANCE_ENV])
            segment_envs[index] = merged
    except AttributeError:
        pass


def provenance_env(
    target: HealerTarget,
    *,
    verdict: Any,
    episode_id: str | None,
    lineage_root: str,
    ledger_key: str,
    evidence_dir: str | None,
    evidence_files: dict[str, Any] | None = None,
    witnesses: Any,
    facts: Any,
) -> dict[str, str]:
    import datetime

    from sase.agent.auto_restart.provenance import provenance_segment_env
    from sase.core.time import get_timezone

    try:
        file_names = sorted(str(k) for k in (evidence_files or {}).keys())
    except Exception:
        file_names = []
    provenance = {
        "of_artifacts_dir": str(target.artifacts_dir),
        "of_timestamp": target.artifacts_dir.name,
        "lineage_root": lineage_root,
        "episode_id": episode_id,
        "ledger_key": ledger_key,
        "evidence_dir": evidence_dir,
        "evidence_files": file_names,
        "signature": getattr(verdict, "signature", None),
        "from_rev": None,
        "to_rev": None,
        "culprit_commit": None,
        "culprit_subject": None,
        "restarted_at": datetime.datetime.now(get_timezone()).isoformat(),
        "broke_detail": None,
    }
    refresh = getattr(witnesses, "refresh_log_line", None)
    if refresh is not None:
        provenance["from_rev"] = getattr(refresh, "from_rev", None) or None
        provenance["to_rev"] = getattr(refresh, "to_rev", None) or None
    provenance["from_rev"] = provenance["from_rev"] or _identity_revision(
        getattr(witnesses, "boot_identity", None)
    )
    provenance["to_rev"] = provenance["to_rev"] or _identity_revision(
        getattr(witnesses, "current_identity", None)
    )
    file_proof = getattr(witnesses, "file_proof", None)
    if file_proof is not None:
        provenance["culprit_commit"] = getattr(file_proof, "culprit_commit", None)
        provenance["culprit_subject"] = getattr(file_proof, "culprit_subject", None)
        provenance["to_rev"] = provenance["to_rev"] or provenance["culprit_commit"]
    phase = getattr(facts, "lifecycle_phase", None) or getattr(
        verdict, "phase_class", None
    )
    if phase:
        provenance["broke_detail"] = f"failed during {phase}"
    if refresh is not None:
        from_rev = getattr(refresh, "from_rev", None)
        to_rev = getattr(refresh, "to_rev", None)
        if from_rev and to_rev:
            detail = f"refresh moved sase from {from_rev} to {to_rev}"
            provenance["broke_detail"] = (
                f"{provenance['broke_detail']}; {detail}"
                if provenance["broke_detail"]
                else detail
            )
    return provenance_segment_env(provenance)


def _identity_revision(identity: Any) -> str | None:
    if not isinstance(identity, str) or not identity:
        return None
    parts = identity.split("|")
    for part in parts:
        name, separator, revision = part.partition("@")
        if separator and name == "sase" and revision:
            return revision
    for part in parts:
        _, separator, revision = part.partition("@")
        if separator and revision:
            return revision
    return None


__all__ = [
    "attach_provenance",
    "provenance_env",
]
