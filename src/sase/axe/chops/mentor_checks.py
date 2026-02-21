"""Mentor completion and startup checks chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("mentor_checks")
def run_mentor_checks(ctx: ChopContext) -> None:
    """Run mentor completion and startup checks on filtered changespecs."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_mentor_checks(ctx.filtered_changespecs)
