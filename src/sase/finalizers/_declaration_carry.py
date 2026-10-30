"""Host-authored carry declarations for finalizer context publications."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sase.finalizers._declaration_context import FinalContextPublication
from sase.finalizers.declaration_store import FinalizerDeclarationError


def synthesize_carry_declaration(
    publication: FinalContextPublication,
    *,
    artifacts_dir: str | None = None,
) -> dict[str, Any] | None:
    """Persist host-authored carry when a dirty inheriting handoff has no submission."""
    from sase.finalizers.commit_carry import carry_action_allowed_for_handoff

    context = publication.context
    repository_ids = [
        obligation.obligation_id
        for obligation in context.obligations
        if obligation.kind == "repository"
    ]
    if (
        publication.submission_required
        or not repository_ids
        or not carry_action_allowed_for_handoff(context.handoff)
    ):
        return None

    manifest = deepcopy(publication.payload.get("manifest_template"))
    if not isinstance(manifest, dict):
        raise FinalizerDeclarationError(
            "finalizer context has no usable manifest template",
            code="malformed_final_context",
        )
    payloads = manifest.get("payloads")
    if not isinstance(payloads, list):
        raise FinalizerDeclarationError(
            "finalizer manifest template payloads are malformed",
            code="malformed_final_context",
        )

    carried: set[str] = set()
    for item in payloads:
        if not isinstance(item, Mapping):
            continue
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            continue
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            continue
        for decision in repositories:
            if not isinstance(decision, dict):
                continue
            repo_id = decision.get("repo_id")
            if not isinstance(repo_id, str) or repo_id not in repository_ids:
                continue
            decision["action"] = "carry"
            decision.pop("message", None)
            decision.pop("bead_action", None)
            carried.add(repo_id)
    if carried != set(repository_ids):
        raise FinalizerDeclarationError(
            "manifest template does not cover every repository eligible for carry",
            code="malformed_final_context",
        )

    handoff = context.handoff
    if handoff is None:
        return None
    provenance = {
        "kind": "handoff_carry",
        "source": "host",
        "staged_ref": handoff.staged_ref,
    }
    from sase.finalizers.declaration import submit_final_manifest

    return submit_final_manifest(
        manifest,
        artifacts_dir=artifacts_dir,
        _synthesized_provenance=provenance,
        _only_if_absent=True,
    )
