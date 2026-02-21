"""Comment check cycle chop."""

from sase.axe.check_cycles import CheckCycleRunner
from sase.axe.chop_registry import ChopContext, register_chop


@register_chop("comment_checks")
def run_comment_checks(ctx: ChopContext) -> None:
    """Run the reviewer/author comment check cycle."""
    runner = CheckCycleRunner(ctx.parsed_query, ctx.log_callback)
    runner.run_comment_check_cycle()
