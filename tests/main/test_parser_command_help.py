"""Tests for non-root CLI parser help rendering."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented as _assert_metavar_option_documented,
)
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
        "persist-cleanup",
        "persist-directive",
        "prompts",
        "retire-v1",
        "revert",
        "show",
        "sync",
        "tribe",
    }

    help_commands = help_subcommand_rows(agents_parser.format_help(), expected_commands)

    assert help_commands == sorted(expected_commands)
    assert (
        "{archive,artifacts,index,kill,list,names,persist-cleanup,"
        "persist-directive,prompts,retire-v1,revert,show,sync,tribe}"
        in agents_parser.format_help()
    )


def test_agent_prompts_help_documents_group_and_validation_flags() -> None:
    prompts = parser_for(("sase", "agent", "prompts"))
    validate_help = flat_help(
        parser_for(("sase", "agent", "prompts", "validate")).format_help()
    )

    assert "{list,migrate,show,validate}" in prompts.format_help()
    assert "-j, --json" in validate_help
    _assert_metavar_option_documented(validate_help, "-m", "--month", "YYYYMM")
    _assert_metavar_option_documented(validate_help, "-p", "--project", "PROJECT")
    assert "-s, --show-warnings" in validate_help


def test_axe_ensure_help_documents_healing_and_watchdog() -> None:
    axe_parser = parser_for(("sase", "axe"))
    ensure_help = flat_help(parser_for(("sase", "axe", "ensure")).format_help())
    status_help = flat_help(parser_for(("sase", "axe", "status")).format_help())
    expected_commands = {
        "chop",
        "ensure",
        "lumberjack",
        "maintenance",
        "status",
        "start",
        "stop",
    }

    help_commands = help_subcommand_rows(axe_parser.format_help(), expected_commands)

    assert help_commands == sorted(expected_commands)
    assert (
        "{chop,ensure,lumberjack,maintenance,start,status,stop}"
        in axe_parser.format_help()
    )
    assert "Bare `sase axe ensure` starts a missing orchestrator" in ensure_help
    assert "{install,uninstall}" in ensure_help
    assert "sase axe ensure install" in ensure_help
    assert "sase axe ensure uninstall" in ensure_help
    assert "read-only, whole-system AXE health snapshot" in status_help
    assert "-j, --json" in status_help
    assert "machine-readable schema-version-1 status object" in status_help


def test_agent_tribe_help_uses_public_tribe_vocabulary() -> None:
    tribe_parser = parser_for(("sase", "agent", "tribe"))
    set_help = flat_help(parser_for(("sase", "agent", "tribe", "set")).format_help())
    args = create_parser().parse_args(
        ["agent", "tribe", "set", "--name", "worker", "--tribe", "review"]
    )

    assert "{list,set,unset}" in tribe_parser.format_help()
    _assert_metavar_option_documented(set_help, "-n", "--name", "NAME")
    _assert_metavar_option_documented(set_help, "-t", "--tribe", "TRIBE")
    assert "--tag" not in set_help
    assert args.tribe == "review"


def test_agent_show_takes_name_positionally(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase agent show`` takes NAME positionally; the old -n/--name is gone."""
    show_help = flat_help(parser_for(("sase", "agent", "show")).format_help())
    args = create_parser().parse_args(["agent", "show", "brisk-otter"])

    assert args.name == "brisk-otter"
    assert "usage: sase agent show [-h] NAME" in show_help
    assert "-n" not in show_help
    assert "--name" not in show_help

    with pytest.raises(SystemExit) as missing_name:
        create_parser().parse_args(["agent", "show"])
    assert missing_name.value.code == 2
    assert "the following arguments are required: NAME" in capsys.readouterr().err

    with pytest.raises(SystemExit) as old_option_form:
        create_parser().parse_args(["agent", "show", "-n", "brisk-otter"])
    assert old_option_form.value.code == 2
    assert "unrecognized arguments: -n" in capsys.readouterr().err


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


def test_pipe_help_documents_prompt_flags_and_turn_warning() -> None:
    """``sase pipe --help`` states that the command ends this turn."""
    pipe_help = flat_help(parser_for(("sase", "pipe")).format_help())
    args = create_parser().parse_args(["pipe", "continue the work", "-n", "review"])

    assert "This ends your turn" in pipe_help
    assert "-f, --fresh" in pipe_help
    assert "-j, --json" in pipe_help
    assert "-m, --model" in pipe_help
    assert "-n, --name" in pipe_help
    assert "-r, --reason" in pipe_help
    assert args.prompt == "continue the work"
    assert args.name == "review"


def test_memory_help_marks_primary_command_and_init_alias() -> None:
    """Memory help text points users to the new primary command surface."""
    memory_help = flat_help(parser_for(("sase", "memory")).format_help())
    memory_init_help = flat_help(parser_for(("sase", "memory", "init")).format_help())
    memory_list_help = flat_help(parser_for(("sase", "memory", "list")).format_help())
    memory_read_help = flat_help(parser_for(("sase", "memory", "read")).format_help())
    memory_show_help = flat_help(parser_for(("sase", "memory", "show")).format_help())
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
    assert "{agent-docs,init,list,log,read,review,show,write}" in memory_help
    assert "sase memory show generated_skills.md" in memory_help
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
    assert "falling back to ~/sase/memory/" in memory_read_help
    assert "flat note name such as generated_skills.md" in memory_read_help
    assert "--reason REASON" in memory_read_help
    assert "Need generated skill context" in memory_read_help
    assert "Identical to `sase memory show`" in memory_read_help
    assert "-f, --format" in memory_show_help
    assert "records no audit event" in memory_show_help
    assert "must use" in memory_show_help
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
    skills_init_help = flat_help(parser_for(("sase", "skill", "init")).format_help())
    skills_log_help = flat_help(parser_for(("sase", "skill", "log")).format_help())
    skills_use_help = flat_help(parser_for(("sase", "skill", "use")).format_help())
    init_skills_help = flat_help(parser_for(("sase", "init", "skills")).format_help())

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
    assert "-y, --yes" in skills_init_help
    assert "-y, --yes" in init_skills_help
    assert skills_init_help.index("--provider PROVIDER") < skills_init_help.index(
        "--yes"
    )
    assert init_skills_help.index("--provider PROVIDER") < init_skills_help.index(
        "--yes"
    )


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
    _assert_metavar_option_documented(open_help, "-p", "--project", "PROJECT")
    _assert_metavar_option_documented(open_help, "-r", "--reason", "REASON")
    _assert_metavar_option_documented(open_help, "-w", "--workspace", "N")
    assert "defaults to the checkout that contains the current directory" in open_help
    assert "sase repo open chezmoi --reason" in open_help
    assert "another registered SASE project" in open_help
    assert "gh:owner/repo" in open_help
    assert "owner/repo is GitHub shorthand" in open_help
    assert "sase repo open dotdrop -r" in open_help
    assert "sase repo open gh:pallets/click -r" in open_help
    assert "sase repo open pallets/click -r" in open_help


def test_repo_init_help_documents_guarded_sidecar_creation() -> None:
    """``sase repo init --help`` exposes its guarded apply controls."""

    init_help = flat_help(parser_for(("sase", "repo", "init")).format_help())

    assert "usage: sase repo init" in init_help
    assert "-c, --check" in init_help
    assert "-d, --diff" in init_help
    assert "-C, --no-commit" in init_help
    assert "interactive, default-no y/yes confirmation" in init_help
    assert "sase repo init --diff --no-commit" in init_help


def test_repo_list_help_documents_scope_workspace_and_examples() -> None:
    """``sase repo list --help`` explains its project/workspace defaults."""

    list_help = flat_help(parser_for(("sase", "repo", "list")).format_help())

    assert "usage: sase repo list" in list_help
    assert "-a, --all" in list_help
    assert "-j, --json" in list_help
    _assert_metavar_option_documented(list_help, "-p", "--project", "PROJECT")
    _assert_metavar_option_documented(list_help, "-w", "--workspace", "N")
    assert "default to the checkout that contains the current directory" in list_help
    assert "sase repo list --workspace 12" in list_help
    assert "sase repo list --all" in list_help


def test_repo_log_help_documents_filters_lookup_and_examples() -> None:
    """``sase repo log --help`` exposes every audited-log filter."""

    log_help = flat_help(parser_for(("sase", "repo", "log")).format_help())

    assert "usage: sase repo log" in log_help
    _assert_metavar_option_documented(log_help, "-a", "--agent", "AGENT_NAME")
    _assert_metavar_option_documented(log_help, "-i", "--id", "OPEN_ID")
    assert "-j, --json" in log_help
    _assert_metavar_option_documented(log_help, "-p", "--project", "PROJECT")
    _assert_metavar_option_documented(log_help, "-r", "--repo", "REPO")
    _assert_metavar_option_documented(log_help, "-w", "--workspace", "N")
    assert "defaults to the checkout that contains the current directory" in log_help
    assert "sase repo log --repo sase-core" in log_help
    assert "sase repo log --id <open-id> --json" in log_help


def test_workspace_help_hides_deprecated_open_alias() -> None:
    """The compatibility parser remains addressable but is not advertised."""

    workspace_help = flat_help(parser_for(("sase", "workspace")).format_help())

    assert "{cleanup,list,migrate,path,repair}" in workspace_help
    assert "open ==SUPPRESS==" not in workspace_help
    assert "Prepare the workspace checkout and print its path" not in workspace_help
