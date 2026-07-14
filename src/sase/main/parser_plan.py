"""Argument parser definition for the ``sase plan`` command group."""

import argparse

from sase.main.parser_bead import nonnegative_int
from sase.main.plan_search_handler import plan_date_arg
from sase.plan_approval_choices import PLAN_APPROVAL_CLI_KINDS


def register_plan_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'plan' subcommand parser."""
    plan_parser = subparsers.add_parser(
        "plan",
        help="Review, approve, reject, propose, and search implementation plans",
        description=(
            "Review the plan pipeline, approve or reject pending proposals from "
            "the ChangeSpecI, inspect SDD prompt/plan links, submit a new plan "
            "for review, or search SDD and machine-local plans.\n\n"
            "With no subcommand, `sase plan` defaults to `sase plan list`."
        ),
        epilog=(
            "examples:\n"
            "  sase plan\n"
            "  sase plan list --json\n"
            "  sase plan approve abcdef12 --kind tale\n"
            "  sase plan links validate --show-warnings\n"
            "  sase plan reject abcdef12\n"
            "  sase plan propose sase_plan_feature.md\n"
            "  sase plan search auth --format json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    plan_subparsers = plan_parser.add_subparsers(
        dest="plan_subcommand",
        help="Plan subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )
    plan_parser.set_defaults(plan_subcommand="list")

    approve_parser = plan_subparsers.add_parser(
        "approve",
        help="Approve one pending plan proposal",
        description=(
            "Approve one pending PlanApproval notification by ID or unique "
            "prefix from `sase plan list`. If SELECTOR is omitted, exactly one "
            "pending proposal must exist."
        ),
        epilog=(
            "examples:\n"
            "  sase plan approve\n"
            "  sase plan approve abcdef12 --kind approve\n"
            "  sase plan approve abcdef12 --kind tale --prompt 'Focus tests'\n"
            "  sase plan approve abcdef12 --with tester\n"
            "  sase plan approve abcdef12 --kind commit"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    approve_parser.add_argument(
        "selector",
        nargs="?",
        metavar="SELECTOR",
        help="Notification id or unique prefix from `sase plan list`",
    )
    approve_parser.add_argument(
        "-k",
        "--kind",
        choices=PLAN_APPROVAL_CLI_KINDS,
        default="approve",
        help=(
            "Approval kind: approve runs coder without committing an SDD plan; "
            "tale commits to sdd/plans with tier tale; epic commits there "
            "with tier epic; commit "
            "records the plan without launching coder"
        ),
    )
    approve_parser.add_argument(
        "-m",
        "--model",
        help="Optional model for the follow-up agent",
    )
    approve_parser.add_argument(
        "-p",
        "--prompt",
        help="Optional extra prompt text for approve/tale coder follow-up",
    )
    approve_parser.add_argument(
        "-w",
        "--with",
        action="append",
        default=[],
        dest="with_members",
        metavar="ROLE",
        help="Run a custom family member for this approval (repeatable)",
    )
    approve_parser.add_argument(
        "-W",
        "--without",
        action="append",
        default=[],
        dest="without_members",
        metavar="ROLE",
        help="Skip a default custom family member for this approval (repeatable)",
    )

    links_parser = plan_subparsers.add_parser(
        "links",
        help="List, validate, or repair SDD prompt/plan links",
        description=(
            "Inspect bidirectional frontmatter links between SDD prompts and "
            "plans. With no subcommand, `sase plan links` defaults to "
            "`sase plan links list`."
        ),
        epilog=(
            "examples:\n"
            "  sase plan links\n"
            "  sase plan links list --json\n"
            "  sase plan links repair --write\n"
            "  sase plan links validate --show-warnings"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    links_subparsers = links_parser.add_subparsers(
        dest="plan_links_subcommand",
        help="Link subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )

    links_list_parser = links_subparsers.add_parser(
        "list",
        help="List SDD frontmatter links",
        description=(
            "Print every SDD prompt/plan frontmatter link and whether its "
            "reverse link is intact. This is also the default for bare "
            "`sase plan links`."
        ),
    )
    links_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    _add_links_path_arg(links_list_parser)

    links_repair_parser = links_subparsers.add_parser(
        "repair",
        help="Infer and repair bidirectional SDD links",
    )
    _add_links_path_arg(links_repair_parser)
    links_repair_parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Write inferred link fixes",
    )

    links_validate_parser = links_subparsers.add_parser(
        "validate",
        help="Validate SDD frontmatter links",
    )
    links_validate_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    _add_links_path_arg(links_validate_parser)
    links_validate_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print validation failures",
    )
    links_validate_parser.add_argument(
        "-W",
        "--show-warnings",
        action="store_true",
        help="Show warning-severity issues (hidden by default)",
    )
    links_validate_parser.add_argument(
        "-s",
        "--strict",
        action="store_true",
        help="Treat unpaired historical files as validation errors",
    )

    list_parser = plan_subparsers.add_parser(
        "list",
        help="List plan proposals and approval history",
        description=(
            "Show pending plan proposals plus approved and inferred rejected "
            "archived plans. Filter the displayed sections by status and "
            "control the amount of approval history shown. This is also the "
            "default for bare `sase plan`."
        ),
        epilog=(
            "examples:\n  sase plan\n  sase plan list\n  sase plan list --json\n"
            "  sase plan list --status approved --limit 25\n"
            "  sase plan list -s proposed\n"
            "  sase plan list -s rejected -n 0\n"
            "  sase plan list --tier epic"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print plan inventory as JSON",
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=10,
        help=(
            "Maximum approved and rejected rows shown per section; 0 = "
            "unlimited; pending proposals are always shown in full "
            "(default: 10)"
        ),
    )
    list_parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=("approved", "proposed", "rejected"),
        help="Show only these pipeline sections (repeatable; default: all)",
    )
    list_parser.add_argument(
        "-t",
        "--tier",
        action="append",
        choices=("tale", "epic"),
        help="Filter by plan-file tier: tale or epic (repeatable)",
    )

    propose_parser = plan_subparsers.add_parser(
        "propose",
        help="Submit a plan file for approval (used by /sase_plan skill)",
        description=(
            "Submit a Markdown plan file for user approval. This command is "
            "intended for SASE agent runs with SASE_AGENT and "
            "SASE_ARTIFACTS_DIR set."
        ),
        epilog=("example:\n  sase plan propose sase_plan_feature.md"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    propose_parser.add_argument(
        "plan_file",
        metavar="PLAN_FILE",
        help="Path to the plan .md file",
    )

    reject_parser = plan_subparsers.add_parser(
        "reject",
        help="Reject one pending plan proposal",
        description=(
            "Reject one pending PlanApproval notification by ID or unique "
            "prefix from `sase plan list`. If SELECTOR is omitted, exactly one "
            "pending proposal must exist. The rejection response is written "
            "first; SASE then attempts to user-kill the matching planner agent "
            "and dismiss its Agents-tab row, the same cleanup path used by "
            "the ACE TUI."
        ),
        epilog=("examples:\n  sase plan reject\n  sase plan reject abcdef12"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    reject_parser.add_argument(
        "selector",
        nargs="?",
        metavar="SELECTOR",
        help="Notification id or unique prefix from `sase plan list`",
    )

    search_parser = plan_subparsers.add_parser(
        "search",
        help="Search SDD and machine-local markdown plans",
        description=(
            "Find plan artifacts whose text contains a literal, "
            "case-insensitive query string, across plans in the resolved SDD "
            "store (the `repo` source, prioritized) and the machine-local "
            "`~/.sase/plans/` archive. The query is optional: omit it to "
            "browse and filter. SDD-store plans are surfaced above local "
            "plans on equal-relevance ties."
        ),
        epilog=(
            "examples:\n"
            "  sase plan search auth\n"
            "  sase plan search auth --format json\n"
            "  sase plan search --kind epic --since 14d --status wip\n"
            "  sase plan search auth --source repo --sort recent --limit 5"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    search_parser.add_argument(
        "query",
        nargs="?",
        help="Literal case-insensitive substring to match; omit to browse",
    )
    search_parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    search_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json", "markdown"],
        default="compact",
        help="Output format: compact, full, json, or markdown (default: compact)",
    )
    search_parser.add_argument(
        "-k",
        "--kind",
        choices=["tale", "epic", "prompt", "research"],
        action="append",
        help=(
            "Filter SDD-store artifacts by plan-file tier (tale or epic), "
            "prompt, or research kind (repeatable)"
        ),
    )
    search_parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=20,
        help="Maximum results to print; 0 means unlimited (default: 20)",
    )
    search_parser.add_argument(
        "-A",
        "--since",
        type=plan_date_arg,
        default=None,
        metavar="DATE",
        help="Only plans created on/after DATE "
        "(YYYY-MM-DD, YYYY-MM, YYYYMM, or relative 14d/2w/3m)",
    )
    search_parser.add_argument(
        "-o",
        "--source",
        choices=["all", "repo", "local"],
        default="all",
        help="Which corpus to scan: all, repo, or local (default: all)",
    )
    search_parser.add_argument(
        "-r",
        "--sort",
        choices=["relevance", "recent", "title"],
        default=None,
        help="Sort order: relevance, recent, or title "
        "(default: relevance with a query, else recent)",
    )
    search_parser.add_argument(
        "-s",
        "--status",
        choices=["wip", "done"],
        action="append",
        help="Filter by frontmatter status: wip or done (repeatable)",
    )
    search_parser.add_argument(
        "-B",
        "--until",
        type=plan_date_arg,
        default=None,
        metavar="DATE",
        help="Only plans created on/before DATE "
        "(YYYY-MM-DD, YYYY-MM, YYYYMM, or relative 14d/2w/3m)",
    )


def _add_links_path_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--path",
        default=None,
        help="SDD root or project root path (default: current project)",
    )
