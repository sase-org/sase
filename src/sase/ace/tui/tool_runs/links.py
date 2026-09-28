"""Links from LLM Calls, slow-tool rows, and Context cards to ToolRuns.

Plan §3.9 (epic sase-1bt, phase ``run-links``): a Bash row whose command
runs ``sase tool run …`` (or a ``sase monitor start`` wrapping one) gains a
verdict suffix and a jump to the run's block; a running or settled
``sase tool run`` row in the Main deck slow-tool list gains a live-stage or
verdict suffix; monitor and named-proc Context cards gain a ``Tool run``
row. All rendering here is pure: callers pass in-memory summaries plus
``now`` and never stat, open SQLite, or read a log.

Join rule (the core brief/glance wires carry no ``display_argv``, so the
match is time plus command tokens, not argv equality):

- same node (the caller scopes ``runs`` to the node already);
- run ``created_ts`` within ``[call start − 2 s, call end + 2 s]``;
- the call command names a tool run (``sase tool run`` or a wrapping
  ``sase monitor start``) and either carries the run's label/tool token
  or yields the run id through the scrape fallback;
- fallback: the 32-hex run id scraped from the call output, which the
  compact footer prints (``sase tool show <id> -l``).

When several runs fall in one call window, the nearest ``created_ts``
wins. Non-tool Bash rows never match.

This module is a facade: the implementation lives in
:mod:`sase.ace.tui.tool_runs.links_commands`,
:mod:`sase.ace.tui.tool_runs.links_jumps`,
:mod:`sase.ace.tui.tool_runs.links_suffixes`,
:mod:`sase.ace.tui.tool_runs.links_matching`, and
:mod:`sase.ace.tui.tool_runs.links_context`, with multiply-used helpers in
:mod:`sase.ace.tui.tool_runs._links_shared`.
"""

from __future__ import annotations

from sase.ace.tui.tool_runs.links_commands import extract_run_ids, is_tool_run_command
from sase.ace.tui.tool_runs.links_context import (
    context_row_for_agent,
    context_row_for_agent_cached,
    node_runs_for_agent,
    run_links_for_agent_entries,
    slow_suffixes_for_agent_sources,
)
from sase.ace.tui.tool_runs.links_jumps import (
    TOOLRUN_JUMP_TARGET_PREFIX,
    run_id_from_jump_target,
    run_jump_hint_label,
    tool_run_jump_target,
    visible_tool_run_jump_targets,
)
from sase.ace.tui.tool_runs.links_matching import (
    CALL_WINDOW_SLOP_S,
    match_llm_call_to_run,
    match_llm_calls_to_runs,
    pick_context_run,
    slow_suffixes_for_entries,
)
from sase.ace.tui.tool_runs.links_suffixes import (
    context_tool_run_line,
    llm_call_run_suffix_text,
    slow_tool_run_suffix_text,
    suffix_text_with_jump,
)

__all__ = [
    "CALL_WINDOW_SLOP_S",
    "TOOLRUN_JUMP_TARGET_PREFIX",
    "context_row_for_agent",
    "context_row_for_agent_cached",
    "context_tool_run_line",
    "extract_run_ids",
    "is_tool_run_command",
    "llm_call_run_suffix_text",
    "match_llm_call_to_run",
    "match_llm_calls_to_runs",
    "node_runs_for_agent",
    "pick_context_run",
    "run_id_from_jump_target",
    "run_jump_hint_label",
    "run_links_for_agent_entries",
    "slow_suffixes_for_agent_sources",
    "slow_suffixes_for_entries",
    "slow_tool_run_suffix_text",
    "suffix_text_with_jump",
    "tool_run_jump_target",
    "visible_tool_run_jump_targets",
]
