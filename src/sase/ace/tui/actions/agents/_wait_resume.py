"""Compatibility façade for agent wait, fork, and resume actions."""

from ._fork_actions import AgentForkActionsMixin
from ._wait_actions import AgentWaitActionsMixin
from ._wait_helpers import (
    action_agent_prompt_name,
    fork_panel_keys,
    is_agent_family_root,
    is_coder_followup_suffix,
    prompt_wait_spec,
    resolve_agent_fork_scope,
    resolve_agent_vcs_tag,
    result_has_wait_spec,
    wait_candidate_from_completion,
    wait_modal_candidates,
    wait_spec_label,
)

_agent_prompt_name = action_agent_prompt_name
_fork_panel_keys = fork_panel_keys
_is_agent_family_root = is_agent_family_root
_is_coder_followup_suffix = is_coder_followup_suffix
_prompt_wait_spec = prompt_wait_spec
_resolve_agent_fork_scope = resolve_agent_fork_scope
_resolve_vcs_tag = resolve_agent_vcs_tag
_result_has_wait_spec = result_has_wait_spec
_wait_candidate_from_completion = wait_candidate_from_completion
_wait_modal_candidates = wait_modal_candidates
_wait_spec_label = wait_spec_label


class AgentWaitResumeMixin(AgentWaitActionsMixin, AgentForkActionsMixin):
    """Mixin combining agent wait, fork, and resume actions."""
