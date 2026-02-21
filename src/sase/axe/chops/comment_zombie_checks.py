"""Comment zombie detection chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("comment_zombie_checks")
def run_comment_zombie_checks(ctx: ChopContext) -> None:
    """Check for zombie comment entries on filtered changespecs."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_comment_zombie_checks(ctx.filtered_changespecs)
