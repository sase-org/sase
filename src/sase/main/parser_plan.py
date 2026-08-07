"""Argument parser definition for the ``sase plan`` command group."""

import argparse

from sase.main.parser_bead import nonnegative_int
from sase.main.parser_bead_common import wrap_width
from sase.main.plan_search_handler import plan_date_arg
from sase.markdown_width import markdown_print_width
from sase.plan_approval_choices import PLAN_APPROVAL_CLI_KINDS

_TARGET_KINDS = ("auto", "bead", "name", "path", "proposal", "ref")


def register_plan_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'plan' subcommand parser."""
    plan_parser = subparsers.add_parser(
        "plan",
        help="Review, approve, reject, propose, search, show, and validate implementation plans",
        description=(
            "Review the plan pipeline, approve or reject pending proposals from "
            "the ChangeSpec, inspect SDD prompt/plan links, submit a new plan "
            "for review, search SDD and machine-local plans, show one plan's "
            "details, or strictly validate one plan file.\n\n"
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
            "  sase plan search auth --format json\n"
            "  sase plan show abcdef12\n"
            "  sase plan validate sase_plan_feature.md --explain"
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
        default=None,
        help=(
            "Approval kind (default: authored plan tier): approve runs coder "
            "without committing an SDD plan; tale commits to sdd/plans with "
            "tier tale; epic commits there with tier epic; commit records the "
            "plan without launching coder"
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
    links_parser = plan_subparsers.add_parser(
        "links",
        help="List, refresh, repair, or validate SDD plan links",
        description=(
            "Inspect bidirectional artifact links between SDD prompts and "
            "plans, or reconcile projected plan provenance headers. With no "
            "subcommand, `sase plan links` defaults to `sase plan links list`."
        ),
        epilog=(
            "examples:\n"
            "  sase plan links\n"
            "  sase plan links list --json\n"
            "  sase plan links refresh --write\n"
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
        help="List SDD artifact links",
        description=(
            "Print every SDD prompt/plan artifact link and whether its "
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

    links_refresh_parser = links_subparsers.add_parser(
        "refresh",
        help="Reconcile projected plan provenance headers",
        description=(
            "Rebuild PARENT, BEAD, AGENTS, and COMMITS plan-header sections from "
            "durable state. The default is a read-only dry run; --write "
            "updates changed plans and commits them to the plans store in "
            "one batch."
        ),
        epilog=(
            "examples:\n"
            "  sase plan links refresh\n"
            "  sase plan links refresh --json\n"
            "  sase plan links refresh --plan plans:202607/example.md\n"
            "  sase plan links refresh --write"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    links_refresh_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable refresh report",
    )
    _add_links_path_arg(links_refresh_parser)
    links_refresh_parser.add_argument(
        "-P",
        "--plan",
        default=None,
        metavar="REF",
        help="Refresh only the plan named by REF",
    )
    links_refresh_parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Write and commit changed plan headers (default: dry run)",
    )

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
        help="Validate SDD artifact links",
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
            "  sase plan search --kind designs --source repo\n"
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
        action="append",
        metavar="KIND",
        help=(
            "Filter repo artifacts by plan tier, prompt, or configured "
            "document-sidecar role (repeatable)"
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

    show_parser = plan_subparsers.add_parser(
        "show",
        help="Show one plan's details",
        description=(
            "Resolve TARGET — an explicit path, a `plans:` reference or "
            "legacy marker path, a pending-approval id or unique prefix, a "
            "bare slug or `<shard>/<slug>`, or a bead id whose design points "
            "at a plan — to exactly one plan and render it as a colored, "
            "section-structured detail view matching the ACE TUI's PLAN "
            "lane. With no TARGET, show the sole visible pending plan "
            "proposal, exactly as `sase plan approve`/`reject` treat an "
            "omitted SELECTOR. In auto mode the ladder is tried in this "
            "order: path, ref, proposal, name, then bead; `-t/--target` "
            "forces one rung with no fallthrough."
        ),
        epilog=(
            "examples:\n"
            "  sase plan show\n"
            "  sase plan show abcdef12\n"
            "  sase plan show plans:202608/plan_show_command.md\n"
            "  sase plan show 202608/plan_show_command\n"
            "  sase plan show sase_plan_feature.md\n"
            "  sase plan show sase-64\n"
            "  sase plan show plans:202608/plan_show_command.md --format json\n"
            "  sase plan show plan_show_command --format raw > plan.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    show_parser.add_argument(
        "target",
        nargs="?",
        metavar="TARGET",
        help="The plan to show (default: the sole visible pending proposal)",
    )
    show_parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json", "raw"],
        default="full",
        help="Output format: compact, full, json, or raw (default: full)",
    )
    show_parser.add_argument(
        "-t",
        "--target",
        dest="target_kind",
        choices=_TARGET_KINDS,
        default="auto",
        help="Force one interpretation of TARGET instead of walking the "
        "ladder (default: auto)",
    )
    # Resolved at parser-build time, which is per-process and lazy per
    # subcommand, so `--help` reports the live configured width.
    default_wrap_width = markdown_print_width()
    show_parser.add_argument(
        "-w",
        "--wrap",
        metavar="WIDTH",
        type=wrap_width,
        default=default_wrap_width,
        help=(
            "Wrap goal, phase, and diagnostics prose at WIDTH columns: "
            f"integer >= 20, 'auto', 'none', or 0 (default: {default_wrap_width})"
        ),
    )

    validate_parser = plan_subparsers.add_parser(
        "validate",
        help="Validate one plan file using its authored tier",
        description=(
            "Strictly validate exactly one Markdown plan file against the "
            "frontmatter schema selected by its `tier:` property. The command "
            "is hermetic: it does not require an active project or agent run. "
            "All discovered problems are reported in one pass; failures "
            "include the expected schema and a minimal valid example."
        ),
        epilog=(
            "examples:\n"
            "  sase plan validate sase_plan_feature.md --explain\n"
            "  sase plan validate epic.md --json\n"
            "  sase plan validate plan.md --quiet"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    validate_parser.add_argument(
        "plan_file",
        metavar="PLAN_FILE",
        help="Path to the plan Markdown file",
    )
    validate_parser.add_argument(
        "-e",
        "--explain",
        action="store_true",
        help="Print tier-specific schema guidance before validation results",
    )
    validate_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable validation envelope",
    )
    validate_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print nothing for a valid plan in human output mode",
    )


def _add_links_path_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--path",
        default=None,
        help="SDD root or project root path (default: current project)",
    )
