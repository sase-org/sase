"""Suffix transformation checks chop."""

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.hook_jobs import HookJobRunner


@register_chop("suffix_transforms")
def run_suffix_transforms(ctx: ChopContext) -> None:
    """Run suffix transformation checks (needs both all and filtered changespecs)."""
    runner = HookJobRunner(
        ctx.runner_pool,
        ctx.metrics,
        ctx.zombie_timeout_seconds,
        ctx.max_runners,
        ctx.log_callback,
    )
    runner.run_suffix_transforms(ctx.all_changespecs, ctx.filtered_changespecs)
