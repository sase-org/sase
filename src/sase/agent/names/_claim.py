"""Record agent-name claims without mutating previous owners.

Collision checks intentionally consider all project lifecycle states; disabled
projects can still contain historical owners for explicit agent names.
"""

from sase.agent.names._common import NameCollisionError
from sase.agent.names._registry import claim_registered_name


def claim_agent_name(
    name: str,
    claiming_dir: str,
    *,
    explicit: bool = False,
    force_reuse: bool = False,
) -> None:
    """Record *name* for *claiming_dir*.

    Explicit ``%id:<name>`` claims reject existing owners instead of
    renaming them. Auto/retry/resume/repeat callers are expected to allocate a
    free new name before claiming; this function no longer strips or rewrites
    prior artifact metadata on their behalf.
    """
    from sase.agent.names._resume import agent_name_allocation_lock

    with agent_name_allocation_lock():
        try:
            claim_registered_name(
                name,
                claiming_dir,
                replace_existing=force_reuse or not explicit,
            )
        except NameCollisionError:
            if explicit:
                raise
