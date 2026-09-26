"""Explicit ``no-new`` prepared-completion receipt verification.

E4 verdict-completion gates host completion for a failed verification on a
covering verdict receipt: the same settled verify-monitor ToolRun must own
an eligible, unexpired ``no_new_failures`` receipt over the current
fingerprint, covering every obligated repository. Any mismatch refuses the
whole completion with one typed reason so settlement can launch ordinary
recovery. This module never mutates monitor, receipt, or repository state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

NO_NEW_ACCEPT = "no_new_failures"
PASS_ACCEPT = "pass"

_UNSETTLED_RUN_STATES = frozenset({"created", "running"})


@dataclass(frozen=True, slots=True)
class NoNewEvidence:
    """Eligibility evidence threaded into no-new commit actions."""

    receipt_id: str
    run_id: str
    verdict: str
    known_signatures: tuple[str, ...]
    accept: str
    tool_name: str


def intent_accept(intent: Mapping[str, Any]) -> str:
    """Return the sealed acceptance policy, defaulting older intents to pass."""

    accept = intent.get("accept", PASS_ACCEPT)
    return str(accept) if isinstance(accept, str) and accept else PASS_ACCEPT


def is_no_new_intent(intent: Mapping[str, Any]) -> bool:
    """Return whether *intent* carries the explicit no-new opt-in."""

    return intent_accept(intent) == NO_NEW_ACCEPT


def evidence_provenance(evidence: NoNewEvidence) -> dict[str, Any]:
    """Render auditable receipt provenance for commit and bead-close actions."""

    return {
        "accept": evidence.accept,
        "receipt_id": evidence.receipt_id,
        "run_id": evidence.run_id,
        "verdict": evidence.verdict,
        "known_signatures": list(evidence.known_signatures),
        "tool_name": evidence.tool_name,
    }


def verify_no_new_receipt(
    *,
    intent: Mapping[str, Any],
    meta: Mapping[str, Any],
    monitor_state: str,
    expected_receipt_id: str | None = None,
    expected_run_id: str | None = None,
) -> tuple[NoNewEvidence | None, str | None]:
    """Verify the covering receipt for an explicit no-new intent.

    Re-observes the current fingerprint and repeats the Rust lookup on every
    call, so settlement and the precommit gate share one check. Returns
    ``(evidence, None)`` when the failed verification is covered, otherwise
    ``(None, reason)`` with one typed refusal. Never raises.
    """

    try:
        return _verify(
            intent, meta, monitor_state, expected_receipt_id, expected_run_id
        )
    except Exception as exc:  # noqa: BLE001 - verification must fail closed.
        return None, f"no_new_verification_error:{exc}"


def _verify(
    intent: Mapping[str, Any],
    meta: Mapping[str, Any],
    monitor_state: str,
    expected_receipt_id: str | None,
    expected_run_id: str | None,
) -> tuple[NoNewEvidence | None, str | None]:
    if monitor_state not in ("completed", "failed"):
        return None, f"no_new_unsupported_outcome:{monitor_state or 'unknown'}"
    if str(meta.get("monitor_profile") or "") != "verify":
        return None, "no_new_requires_verify_monitor"
    run_id = meta.get("monitor_tool_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None, "no_new_missing_tool_run"
    run_id = run_id.strip()
    if expected_run_id and run_id != expected_run_id:
        return None, "no_new_wrong_source_run"
    monitor_id = meta.get("monitor_id")
    monitor_id = str(monitor_id).strip() if monitor_id else ""

    from sase.core.tool_run import tool_run_show, tool_run_triage_show

    try:
        envelope = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - unreadable store fails closed.
        return None, f"no_new_run_unreadable:{exc}"
    run = envelope.get("run")
    if not isinstance(run, dict):
        return None, "no_new_run_missing"
    state = str(run.get("state") or "")
    if state in _UNSETTLED_RUN_STATES:
        return None, f"no_new_run_unsettled:{state or 'unknown'}"
    if state == "lost":
        return None, "no_new_run_lost"
    owner_kind = run.get("owner_kind")
    owner_id = run.get("owner_id")
    if not owner_kind or not owner_id:
        return None, "no_new_missing_owner_link"
    if str(owner_kind) != "monitor" or (monitor_id and str(owner_id) != monitor_id):
        return None, "no_new_unrelated_tool_run"

    tool_name = run.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None, "no_new_command_mismatch:adhoc"
    tool_name = tool_name.strip()
    level = (
        (intent.get("verification") or {}).get("level")
        if isinstance(intent.get("verification"), Mapping)
        else None
    )
    expected_tool = {"check": "check", "check_full": "check-full"}.get(str(level))
    if expected_tool is None or tool_name != expected_tool:
        return None, f"no_new_command_mismatch:{tool_name}"

    try:
        triage = tool_run_triage_show({"run_id": run_id})
    except Exception as exc:  # noqa: BLE001 - unreadable triage fails closed.
        return None, f"no_new_triage_unreadable:{exc}"
    verdict = triage.get("verdict")
    verdict = str(verdict) if isinstance(verdict, str) and verdict else ""
    if verdict not in (PASS_ACCEPT, NO_NEW_ACCEPT):
        return None, f"no_new_verdict_insufficient:{verdict or 'missing'}"

    from sase.tool.argv import ToolRunUsageError, resolve_run_argv

    monitor_cwd = meta.get("monitor_cwd")
    monitor_cwd = (
        str(monitor_cwd).strip()
        if isinstance(monitor_cwd, str) and monitor_cwd.strip()
        else None
    )
    try:
        resolved = resolve_run_argv([tool_name], cwd=monitor_cwd)
    except ToolRunUsageError:
        return None, f"no_new_unknown_tool:{tool_name}"
    if resolved.adhoc or not resolved.tool_name:
        return None, f"no_new_unknown_tool:{tool_name}"

    from sase.tool.receipts import receipt_policy_for_resolved

    policy = receipt_policy_for_resolved(resolved)
    policy_accept = policy.get("accept") if isinstance(policy, dict) else None
    if not isinstance(policy_accept, list) or NO_NEW_ACCEPT not in [
        str(token) for token in policy_accept
    ]:
        return None, "no_new_policy_changed"

    from sase.tool.observe import observe_fingerprint

    fingerprint = observe_fingerprint(resolved)
    complete = (
        (fingerprint.get("completeness") or {}).get("complete")
        if isinstance(fingerprint.get("completeness"), Mapping)
        else False
    )
    if not complete:
        return None, "no_new_incomplete_fingerprint"

    from sase.core.tool_run import tool_run_receipt_lookup

    payload: dict[str, Any] = {
        "project": resolved.resolved_project_identity(),
        "tool_name": resolved.tool_name,
        "definition_digest": resolved.digest
        or str(fingerprint.get("definition_digest") or ""),
        "extra_args_digest": str(fingerprint.get("extra_args_digest") or ""),
        "fingerprint": fingerprint,
        "accept": [NO_NEW_ACCEPT],
    }
    try:
        result = tool_run_receipt_lookup(payload)
    except Exception as exc:  # noqa: BLE001 - lookup failures fail closed.
        return None, f"no_new_lookup_failed:{exc}"
    if result.get("outcome") != "covered":
        refusal = result.get("refusal") or "refused"
        reason = result.get("reason") or str(refusal)
        return None, f"no_new_receipt_{refusal}:{reason}"
    receipt = result.get("receipt")
    if not isinstance(receipt, dict):
        return None, "no_new_receipt_missing"
    if str(receipt.get("source_run_id") or "") != run_id:
        return None, "no_new_wrong_source_run"
    if (
        expected_receipt_id
        and str(receipt.get("receipt_id") or "") != expected_receipt_id
    ):
        return None, "no_new_receipt_changed"

    missing = _uncovered_obligations(intent, fingerprint, payload["project"])
    if missing:
        return None, f"no_new_incomplete_coverage:{','.join(sorted(missing))}"

    signatures = _known_signatures(receipt)
    return (
        NoNewEvidence(
            receipt_id=str(receipt.get("receipt_id") or ""),
            run_id=run_id,
            verdict=str(receipt.get("verdict") or verdict),
            known_signatures=tuple(signatures),
            accept=NO_NEW_ACCEPT,
            tool_name=tool_name,
        ),
        None,
    )


def _uncovered_obligations(
    intent: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
    project: str,
) -> list[str]:
    """Return obligated repo names missing from the receipt fingerprint.

    The primary (``main``) observation maps to the tool project identity;
    every other obligated repository maps by its prepared name, matching the
    fingerprint's linked-clone identity layout. Anything unmapped fails
    closed: a sibling the receipt never fingerprinted refuses the whole
    no-new completion.
    """

    from sase.monitor.host_completion_state import required_commit_repo_ids

    required = required_commit_repo_ids(intent)
    if not required:
        return []
    observations = intent.get("observations")
    by_id = {
        str(item.get("repo_id")): item
        for item in (observations if isinstance(observations, list) else [])
        if isinstance(item, Mapping) and item.get("repo_id")
    }
    covered = {
        str(repo.get("identity") or "")
        for repo in (fingerprint.get("repos") or [])
        if isinstance(repo, Mapping)
    }
    missing: list[str] = []
    for repo_id in required:
        observation = by_id.get(str(repo_id))
        if not isinstance(observation, dict):
            missing.append(str(repo_id))
            continue
        if str(observation.get("kind") or "") == "main":
            wanted = project
        else:
            wanted = str(observation.get("name") or "")
        if not wanted or wanted not in covered:
            missing.append(str(observation.get("name") or repo_id))
    return missing


def _known_signatures(receipt: Mapping[str, Any]) -> list[str]:
    """Return the receipt's KNOWN/FLAKY signature references."""

    refs = receipt.get("signature_refs")
    signatures: list[str] = []
    if isinstance(refs, list):
        for ref in refs:
            if not isinstance(ref, Mapping):
                continue
            signature = ref.get("signature")
            if isinstance(signature, str) and signature.strip():
                signatures.append(signature.strip())
    return sorted(set(signatures))


__all__ = [
    "NO_NEW_ACCEPT",
    "PASS_ACCEPT",
    "NoNewEvidence",
    "evidence_provenance",
    "intent_accept",
    "is_no_new_intent",
    "verify_no_new_receipt",
]
