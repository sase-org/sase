"""Beta-gated finalizer controller entry point."""

from __future__ import annotations

from typing import Any

from sase.finalizers.plan import load_persisted_finalizer_plan
from sase.llm_provider.types import ModelTier


def run_finalizers(
    *,
    provider: Any,
    original_prompt: str,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any = None,
) -> Any:
    """Run the beta finalizer plan.

    This foundation phase only owns plan resolution. The default bundled plan
    selects ``commit`` and delegates to the legacy reconciler for parity until
    the generic execution phase replaces this compatibility branch.
    """

    selected = _selected_instances(artifacts_dir)
    if not selected:
        return invoke_result
    if selected == ("commit",):
        from sase.llm_provider.commit_finalizer import run_commit_finalizer

        return run_commit_finalizer(
            provider=provider,
            original_prompt=original_prompt,
            invoke_result=invoke_result,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
            options=options,
        )
    joined = ", ".join(selected)
    raise RuntimeError(
        f"selected finalizer executor(s) are not implemented in this phase: {joined}"
    )


def _selected_instances(artifacts_dir: str | None) -> tuple[str, ...]:
    payload = load_persisted_finalizer_plan(artifacts_dir)
    if not payload:
        return ("commit",)
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return ("commit",)
    entries = plan.get("entries")
    if not isinstance(entries, list):
        return ("commit",)
    selected: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        instance_id = entry.get("instance_id")
        if isinstance(instance_id, str) and instance_id:
            selected.append(instance_id)
    return tuple(selected)


__all__ = ["run_finalizers"]
