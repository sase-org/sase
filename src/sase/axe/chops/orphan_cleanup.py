"""Orphaned workspace claims cleanup chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("orphan_cleanup")
def run_orphan_cleanup(ctx: ChopContext) -> None:
    """Clean up orphaned workspace claims for reverted CLs."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_orphan_cleanup(ctx.all_changespecs)
