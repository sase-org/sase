"""Real-pipeline Agent Hijack canary.

Launches through ``spawn_agent_subprocess`` so bootstrap, anonymous ``tmp_*``
workflow creation, and directive extraction all run for real. Fakey holds on a
barrier until the TUI loader sees RUNNING with an ``immediate`` decision, then
hijacks through ``submit_agent_hijack`` → ``sase agent persist-hijack``.
Continue uses ``sase agent recover``.
"""

from __future__ import annotations

from tests.fakey._agent_hijack_canary_scenarios import (
    test_anonymous_tmp_workflow_hijack_continue_same_workspace as test_anonymous_tmp_workflow_hijack_continue_same_workspace,
    test_session_hijack_chooses_running_member_one as test_session_hijack_chooses_running_member_one,
)
