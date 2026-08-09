"""Context construction for one-shot chop runs."""

from __future__ import annotations

from collections.abc import Callable

from sase.ace.patch import Patch, find_all_patches
from sase.core.query_facade import evaluate_query_many
from sase.core.state_write_guard import best_effort_test_state_write_allowed

from .chop_script_context import (
    ChopScriptContext,
    serialize_patches,
    write_chop_context,
)
from .config import AxeConfig
from .state import ensure_lumberjack_dirs


ONESHOT_LUMBERJACK_NAME = "_oneshot"


def build_oneshot_context(
    lumberjack_name: str,
    axe_config: AxeConfig,
    *,
    find_all_patches_fn: Callable[[], list[Patch]] = find_all_patches,
    evaluate_query_many_fn: Callable[
        [str, list[Patch]], list[bool]
    ] = evaluate_query_many,
) -> str:
    """Serialize a single-chop context.json under the lumberjack's tick dir.

    Mirrors what :class:`Lumberjack` writes once per tick so chop scripts see
    identical context regardless of whether the run was scheduled, kicked off
    by the CLI, or triggered from the TUI.
    """
    state_dir = ensure_lumberjack_dirs(lumberjack_name)
    tick_dir = state_dir / "tick"
    if not best_effort_test_state_write_allowed(tick_dir, category="axe-chop-state"):
        return str(tick_dir / "context.json")
    tick_dir.mkdir(parents=True, exist_ok=True)

    all_cs_file = str(tick_dir / "all_changespecs.json")
    filtered_cs_file = str(tick_dir / "filtered_changespecs.json")
    context_file = str(tick_dir / "context.json")

    all_patches = find_all_patches_fn()
    filtered_patches = all_patches
    if axe_config.query:
        mask = evaluate_query_many_fn(axe_config.query, all_patches)
        filtered_patches = [
            cs for cs, keep in zip(all_patches, mask, strict=True) if keep
        ]

    serialize_patches(all_patches, all_cs_file)
    serialize_patches(filtered_patches, filtered_cs_file)

    ctx = ChopScriptContext(
        max_hook_runners=axe_config.max_hook_runners,
        max_agent_runners=axe_config.max_agent_runners,
        zombie_timeout_seconds=axe_config.zombie_timeout_seconds,
        query=axe_config.query,
        lumberjack_name=lumberjack_name,
        state_dir=str(state_dir),
        all_patches_file=all_cs_file,
        filtered_patches_file=filtered_cs_file,
    )
    write_chop_context(ctx, context_file)
    return context_file


_build_oneshot_context = build_oneshot_context
