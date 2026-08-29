"""Launch-selection helpers for workflow prompt steps."""

import json
import os
from typing import Any

from sase.llm_provider.launch_selection import LaunchSelection
from sase.xprompt.directives import PromptDirectives


def _read_agent_meta(artifacts_dir: str) -> dict[str, Any] | None:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as stream:
            meta = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return meta if isinstance(meta, dict) else None


def _read_model_alias_reservation(artifacts_dir: str) -> dict[str, Any] | None:
    meta = _read_agent_meta(artifacts_dir)
    if meta is None:
        return None
    reservation = meta.get("model_alias_reservation")
    return dict(reservation) if isinstance(reservation, dict) else None


def _launch_selection_from_agent_meta(
    artifacts_dir: str,
    *,
    directives: PromptDirectives,
) -> LaunchSelection | None:
    """Return the recorded agent model when the prompt has no ``%model``.

    Default ``sase pipe`` inherit copies the parent's ``llm_provider`` and
    ``model`` into the successor artifacts dir but does not prepend
    ``%model``. Without this fallback the anonymous workflow step would
    resolve ``llm_provider.default_model`` (Claude on a host that has the
    CLI) and break the inherit contract.
    """
    if getattr(directives, "model", None):
        return None
    meta = _read_agent_meta(artifacts_dir)
    if meta is None:
        return None
    provider = meta.get("llm_provider")
    model = meta.get("model")
    if not isinstance(provider, str) or not provider:
        return None
    if not isinstance(model, str) or not model:
        return None
    effort = meta.get("reasoning_effort")
    if effort is not None and not isinstance(effort, str):
        effort = None
    raw_trail = meta.get("model_alias_trail")
    alias_trail: tuple[str, ...] = ()
    if isinstance(raw_trail, list) and all(
        isinstance(item, str) and item for item in raw_trail
    ):
        alias_trail = tuple(raw_trail)
    return LaunchSelection(
        provider=provider,
        model=model,
        reasoning_effort=effort,
        effort_explicit=False,
        alias_trail=alias_trail,
        cursor_alias=None,
    )


def resolve_prompt_step_launch_selection(
    artifacts_dir: str,
    *,
    directives: PromptDirectives,
    provider_disables: Any,
) -> LaunchSelection:
    """Pick reservation, then inherited agent meta, then default_model."""
    from sase.llm_provider.launch_selection import (
        launch_selection_from_reservation,
        resolve_launch_selection,
    )

    reservation = _read_model_alias_reservation(artifacts_dir)
    launch_selection = launch_selection_from_reservation(
        reservation,
        directives=directives,
        provider_disables=provider_disables,
    )
    if launch_selection is not None:
        _mark_model_alias_reservation_redeemed(artifacts_dir, reservation)
        return launch_selection
    if isinstance(reservation, dict) and reservation.get("redeemed") is False:
        # A live bootstrap reservation that no longer matches must be spent
        # and re-resolved. Do not inherit the stale agent_meta target.
        _mark_model_alias_reservation_redeemed(artifacts_dir, reservation)
    else:
        inherited = _launch_selection_from_agent_meta(
            artifacts_dir, directives=directives
        )
        if inherited is not None:
            return inherited
    selection = resolve_launch_selection(
        directives,
        directives.model_alias_overrides,
        consume=True,
        provider_disables=provider_disables,
    )
    assert selection is not None
    return selection


def _mark_model_alias_reservation_redeemed(
    artifacts_dir: str,
    reservation: dict[str, Any] | None,
) -> None:
    if not reservation:
        return
    from sase.axe.run_agent_helpers import update_meta_fields

    redeemed = dict(reservation)
    redeemed["redeemed"] = True
    update_meta_fields(artifacts_dir, {"model_alias_reservation": redeemed})


def update_root_agent_meta_from_launch(
    artifacts_dir: str,
    *,
    directives: PromptDirectives,
    launch_selection: LaunchSelection,
) -> None:
    """Reconcile agent_meta.json with the authoritative launch selection."""
    from sase.axe.run_agent_helpers import update_meta_fields
    from sase.llm_provider.config import (
        DEFAULT_MODEL_FIELD,
        launch_model_setting_alias,
    )

    root_model_alias = (
        directives.model_alias
        if directives.model
        else launch_model_setting_alias(
            DEFAULT_MODEL_FIELD,
            directives.model_alias_overrides,
        )
    )
    step_model_alias_trail = list(launch_selection.alias_trail)
    root_meta_fields: dict[str, Any] = {
        "model": launch_selection.model,
        "llm_provider": launch_selection.provider,
        "model_alias_origin": launch_selection.alias_origin,
    }
    if root_model_alias:
        root_meta_fields["model_alias"] = root_model_alias
    if step_model_alias_trail:
        root_meta_fields["model_alias_trail"] = step_model_alias_trail
    if launch_selection.reasoning_effort:
        root_meta_fields["reasoning_effort"] = launch_selection.reasoning_effort
    update_meta_fields(
        artifacts_dir,
        root_meta_fields,
        remove_keys=() if step_model_alias_trail else ("model_alias_trail",),
    )
