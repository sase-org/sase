"""Tests for non-root CLI parser help rendering."""

from __future__ import annotations

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_agents_help_renders_sorted_subcommands() -> None:
    """A formerly unsorted help view renders its user-facing rows sorted."""
    agents_parser = parser_for(("sase", "agent"))
    expected_commands = {
        "archive",
        "artifacts",
        "index",
        "kill",
        "list",
        "names",
        "show",
        "tag",
    }

    help_commands = help_subcommand_rows(agents_parser.format_help(), expected_commands)

    assert help_commands == sorted(expected_commands)
    assert (
        "{archive,artifacts,index,kill,list,names,show,tag}"
        in agents_parser.format_help()
    )


def test_run_help_shows_prompt_positional_and_beginner_examples() -> None:
    """``sase run --help`` advertises the prompt and first-run examples."""
    run_help = parser_for(("sase", "run")).format_help()
    args = create_parser().parse_args(["run", "hello"])

    assert "usage: sase run [-h] [PROMPT]" in run_help
    assert "PROMPT" in run_help
    assert (
        'sase run "#git:home summarize what this repository does; do not change files"'
        in run_help
    )
    assert 'sase run "#fork(agent_name) follow up on the previous result"' in run_help
    assert "sase chat list" in run_help
    assert "--daemon" not in run_help
    assert "--resume" not in run_help
    assert args.prompt == "hello"


def test_memory_help_marks_primary_command_and_init_alias() -> None:
    """Memory help text points users to the new primary command surface."""
    memory_help = flat_help(parser_for(("sase", "memory")).format_help())
    memory_init_help = flat_help(parser_for(("sase", "memory", "init")).format_help())
    memory_list_help = flat_help(parser_for(("sase", "memory", "list")).format_help())
    memory_read_help = flat_help(parser_for(("sase", "memory", "read")).format_help())
    memory_write_help = flat_help(parser_for(("sase", "memory", "write")).format_help())
    memory_review_help = flat_help(
        parser_for(("sase", "memory", "review")).format_help()
    )
    memory_log_help = flat_help(parser_for(("sase", "memory", "log")).format_help())
    init_alias_help = flat_help(parser_for(("sase", "init", "memory")).format_help())
    agent_docs_help = flat_help(
        parser_for(("sase", "memory", "agent-docs")).format_help()
    )
    agent_docs_list_help = flat_help(
        parser_for(("sase", "memory", "agent-docs", "list")).format_help()
    )

    assert "`sase memory list`" in memory_help
    assert "{agent-docs,init,list,log,read,review,write}" in memory_help
    assert "`sase memory agent-docs list`" in agent_docs_help
    assert "provider instruction shim status" in agent_docs_list_help
    assert "sase memory read generated_skills.md --reason" in memory_help
    assert "sase memory write --title" in memory_help
    assert "sase memory review --list" in memory_help
    assert "sase memory review mem-20260523-142233-a1b2c3d4 --edit" in memory_help
    assert "sase memory log --include proposals" in memory_help
    assert "sase memory log --path generated_skills.md" in memory_help
    assert "sase memory log --id <read-id>" in memory_help
    assert "loaded, referenced, available, and missing memory files" in memory_help
    assert "`sase init memory` is a compatibility alias" in memory_init_help
    assert "-M, --enable-project-memory" in memory_init_help
    assert "is_sase_managed: true" in memory_init_help
    assert "managed project memory" in memory_init_help
    assert "generated-change source edits" in memory_init_help
    assert "generated-change source edits" in init_alias_help
    assert "loaded @ references" in memory_list_help
    assert "referenced-only plain memory paths" in memory_list_help
    assert "long-term memory markdown file" in memory_read_help
    assert "falling back to ~/memory/" in memory_read_help
    assert "flat note name such as generated_skills.md" in memory_read_help
    assert "--reason REASON" in memory_read_help
    assert "Need generated skill context" in memory_read_help
    assert "--evidence EVIDENCE" in memory_write_help
    assert "--manual-author NAME" in memory_write_help
    assert "--notify" in memory_write_help
    assert "never modifies canonical memory files" in memory_write_help
    assert "--approve" in memory_review_help
    assert "--reject" in memory_review_help
    assert "--edited-file PATH" in memory_review_help
    assert "--path MEMORY_PATH" in memory_log_help
    assert "--agent AGENT_NAME" in memory_log_help
    assert "--id READ_ID" in memory_log_help
    assert "--include KIND" in memory_log_help
    assert "sase memory log --id <read-id>" in memory_log_help
    assert "Compatibility alias for `sase memory init`" in init_alias_help
    assert "-M, --enable-project-memory" in init_alias_help
    assert "is_sase_managed: true" in init_alias_help


def test_skills_help_documents_log_command() -> None:
    """Skills help text documents list/init/log/use and public log aliases."""
    skills_help = flat_help(parser_for(("sase", "skill")).format_help())
    skills_log_help = flat_help(parser_for(("sase", "skill", "log")).format_help())
    skills_use_help = flat_help(parser_for(("sase", "skill", "use")).format_help())

    assert "`sase skill list`" in skills_help
    assert "{init,list,log,use}" in skills_help
    assert "sase skill log --runtime codex" in skills_help
    assert "sase skill use sase_plan --reason" in skills_help
    assert "--agent AGENT_NAME" in skills_log_help
    assert "-a AGENT_NAME" in skills_log_help
    assert "--id USE_ID" in skills_log_help
    assert "-i USE_ID" in skills_log_help
    assert "--json" in skills_log_help
    assert "-j" in skills_log_help
    assert "--runtime RUNTIME" in skills_log_help
    assert "-R RUNTIME" in skills_log_help
    assert "--skill SKILL_NAME" in skills_log_help
    assert "-s SKILL_NAME" in skills_log_help
    assert "sase skill log --id <use-id>" in skills_log_help
    assert "--reason REASON" in skills_use_help


def test_workspace_open_help_requires_reason() -> None:
    """``sase workspace open --help`` advertises the required reason flag."""
    open_help = flat_help(parser_for(("sase", "workspace", "open")).format_help())

    # The required option appears without brackets in the usage line.
    assert "-r REASON" in open_help
    assert "--reason REASON" in open_help
    assert "Non-empty reason for opening and preparing the workspace" in open_help


def test_repo_open_help_documents_inference_and_required_reason() -> None:
    """``sase repo open --help`` exposes the audited, repo-first UX."""

    open_help = flat_help(parser_for(("sase", "repo", "open")).format_help())

    assert "usage: sase repo open" in open_help
    assert "REPO" in open_help
    assert "-p PROJECT, --project PROJECT" in open_help
    assert "-r REASON, --reason REASON" in open_help
    assert "-w N, --workspace N" in open_help
    assert "defaults to the checkout that contains the current directory" in open_help
    assert "sase repo open chezmoi --reason" in open_help
    assert "another registered SASE project" in open_help
    assert "gh:owner/repo" in open_help
    assert "owner/repo is GitHub shorthand" in open_help
    assert "sase repo open dotdrop -r" in open_help
    assert "sase repo open gh:pallets/click -r" in open_help
    assert "sase repo open pallets/click -r" in open_help


def test_repo_list_help_documents_scope_workspace_and_examples() -> None:
    """``sase repo list --help`` explains its project/workspace defaults."""

    list_help = flat_help(parser_for(("sase", "repo", "list")).format_help())

    assert "usage: sase repo list" in list_help
    assert "-a, --all" in list_help
    assert "-j, --json" in list_help
    assert "-p PROJECT, --project PROJECT" in list_help
    assert "-w N, --workspace N" in list_help
    assert "default to the checkout that contains the current directory" in list_help
    assert "sase repo list --workspace 12" in list_help
    assert "sase repo list --all" in list_help


def test_repo_log_help_documents_filters_lookup_and_examples() -> None:
    """``sase repo log --help`` exposes every audited-log filter."""

    log_help = flat_help(parser_for(("sase", "repo", "log")).format_help())

    assert "usage: sase repo log" in log_help
    assert "-a AGENT_NAME, --agent AGENT_NAME" in log_help
    assert "-i OPEN_ID, --id OPEN_ID" in log_help
    assert "-j, --json" in log_help
    assert "-p PROJECT, --project PROJECT" in log_help
    assert "-r REPO, --repo REPO" in log_help
    assert "-w N, --workspace N" in log_help
    assert "defaults to the checkout that contains the current directory" in log_help
    assert "sase repo log --repo sase-core" in log_help
    assert "sase repo log --id <open-id> --json" in log_help


def test_workspace_help_hides_deprecated_open_alias() -> None:
    """The compatibility parser remains addressable but is not advertised."""

    workspace_help = flat_help(parser_for(("sase", "workspace")).format_help())

    assert "{cleanup,list,migrate,path,repair}" in workspace_help
    assert "open ==SUPPRESS==" not in workspace_help
    assert "Prepare the workspace checkout and print its path" not in workspace_help
