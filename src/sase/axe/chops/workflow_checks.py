"""CRS/fix-hook workflow checks chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("workflow_checks")
def run_workflow_checks(ctx: ChopContext) -> None:
    """Run CRS/fix-hook workflow checks on filtered changespecs."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_workflow_checks(ctx.filtered_changespecs)
