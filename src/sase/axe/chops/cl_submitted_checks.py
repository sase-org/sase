"""CL submitted check cycle chop."""

from sase.axe.check_cycles import CheckCycleRunner
from sase.axe.chop_registry import ChopContext, register_chop


@register_chop("cl_submitted_checks")
def run_cl_submitted_checks(ctx: ChopContext) -> None:
    """Run the full CL submitted check cycle."""
    runner = CheckCycleRunner(ctx.parsed_query, ctx.log_callback)
    runner.run_full_check_cycle()
