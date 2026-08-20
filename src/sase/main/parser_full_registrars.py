"""Static registrar catalog loaded only when building the full CLI parser."""

from typing import Any

from sase.main.parser_ace import register_ace_parser, register_axe_parser
from sase.main.parser_agent import register_agent_parser
from sase.main.parser_agent_cli import register_agent_cli_parser
from sase.main.parser_artifact import register_artifact_parser
from sase.main.parser_bead import register_bead_parser
from sase.main.parser_chat import register_chat_parser
from sase.main.parser_commands import (
    register_comments_parser,
    register_config_parser,
    register_file_history_parser,
    register_file_parser,
    register_logs_parser,
    register_lsp_parser,
    register_notify_parser,
    register_path_parser,
    register_questions_parser,
    register_revive_log_parser,
    register_run_parser,
)
from sase.main.parser_patch import register_patch_parser
from sase.main.parser_commit import (
    register_commit_parser,
    register_restore_parser,
    register_revert_parser,
)
from sase.main.parser_completion import register_completion_parser
from sase.main.parser_core import register_core_parser
from sase.main.parser_doctor import register_doctor_parser
from sase.main.parser_editor import register_editor_parser
from sase.main.parser_file_hook import register_file_hook_parser
from sase.main.parser_flag import register_flag_parser
from sase.main.parser_gate import register_gate_parser
from sase.main.parser_glossary import register_glossary_parser
from sase.main.parser_init import register_init_parser
from sase.main.parser_launch import register_launch_parser
from sase.main.parser_memory import register_memory_parser
from sase.main.parser_mobile import register_mobile_parser
from sase.main.parser_monitor import register_monitor_parser
from sase.main.parser_plan import register_plan_parser
from sase.main.parser_pipe import register_pipe_parser
from sase.main.parser_plugin import register_plugin_parser
from sase.main.parser_proc import register_proc_parser
from sase.main.parser_project import register_project_parser
from sase.main.parser_prompt import register_prompt_parser
from sase.main.parser_repo import register_repo_parser
from sase.main.parser_repro import register_repro_parser
from sase.main.parser_skills import register_skills_parser
from sase.main.parser_snippet import register_snippet_parser
from sase.main.parser_stitch import register_stitch_parser
from sase.main.parser_telemetry import register_telemetry_parser
from sase.main.parser_tmux_agent import register_tmux_agent_parser
from sase.main.parser_update import register_update_parser
from sase.main.parser_validate import register_validate_parser
from sase.main.parser_var import register_var_parser
from sase.main.parser_version import register_version_parser
from sase.main.parser_workspace import register_workspace_parser
from sase.main.parser_xprompt import register_xprompt_parser


# This catalog gives static analysis a real view of each public registrar's
# consumer. Command names and routing remain authoritative in parser.py's lazy
# registry; this module is imported only for ``create_parser(only=None)``.
COMMAND_REGISTRARS_BY_NAME: dict[str, Any] = {
    registrar.__name__: registrar
    for registrar in (
        register_ace_parser,
        register_agent_parser,
        register_agent_cli_parser,
        register_artifact_parser,
        register_axe_parser,
        register_bead_parser,
        register_chat_parser,
        register_comments_parser,
        register_commit_parser,
        register_completion_parser,
        register_config_parser,
        register_core_parser,
        register_doctor_parser,
        register_editor_parser,
        register_file_parser,
        register_file_history_parser,
        register_file_hook_parser,
        register_flag_parser,
        register_gate_parser,
        register_glossary_parser,
        register_init_parser,
        register_launch_parser,
        register_logs_parser,
        register_lsp_parser,
        register_memory_parser,
        register_mobile_parser,
        register_monitor_parser,
        register_notify_parser,
        register_path_parser,
        register_patch_parser,
        register_plan_parser,
        register_pipe_parser,
        register_plugin_parser,
        register_proc_parser,
        register_project_parser,
        register_prompt_parser,
        register_questions_parser,
        register_repo_parser,
        register_repro_parser,
        register_restore_parser,
        register_revert_parser,
        register_revive_log_parser,
        register_run_parser,
        register_skills_parser,
        register_snippet_parser,
        register_stitch_parser,
        register_telemetry_parser,
        register_tmux_agent_parser,
        register_update_parser,
        register_validate_parser,
        register_var_parser,
        register_version_parser,
        register_workspace_parser,
        register_xprompt_parser,
    )
}
