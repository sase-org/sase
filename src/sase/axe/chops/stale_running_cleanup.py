"""Stale RUNNING entries cleanup chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("stale_running_cleanup")
def run_stale_running_cleanup(ctx: ChopContext) -> None:
    """Clean up stale RUNNING entries for dead processes."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_stale_running_cleanup()
