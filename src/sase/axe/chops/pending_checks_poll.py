"""Pending checks polling chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("pending_checks_poll")
def run_pending_checks_poll(ctx: ChopContext) -> None:
    """Poll for completed background checks on filtered changespecs."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_pending_checks_poll(ctx.filtered_changespecs)
