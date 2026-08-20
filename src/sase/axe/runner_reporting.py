"""Error reporting and finalization helpers shared by axe runners."""

import json
import os
from collections.abc import Callable, Mapping

from sase.ace.patch import Patch, parse_project_file


def _finalizer_verdict(artifacts_dir: str) -> str | None:
    result_path = os.path.join(artifacts_dir, "finalizer_result.json")
    if not os.path.exists(result_path):
        return None
    try:
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "result unreadable"

    if not isinstance(result, dict):
        return "result unreadable"

    status = str(result.get("status") or "unknown")
    instances = result.get("instances")
    if not isinstance(instances, list):
        return status

    labels: list[str] = []
    for item in instances:
        if not isinstance(item, dict):
            continue
        instance_id = str(item.get("instance_id") or "unknown")
        instance_status = str(item.get("status") or "unknown")
        labels.append(f"{instance_id}={instance_status}")
    if labels:
        return f"{status} [" + ", ".join(labels) + "]"
    return status


def _commit_finalizer_verdict(artifacts_dir: str) -> str:
    result_path = os.path.join(artifacts_dir, "commit_finalizer_result.json")
    try:
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
    except FileNotFoundError:
        return "result unavailable"
    except (json.JSONDecodeError, OSError):
        return "result unreadable"

    if not isinstance(result, dict):
        return "result unreadable"

    status = str(result.get("status") or "unknown")
    reason = str(result.get("reason") or "").strip()
    error = str(result.get("error") or "").strip()
    verdict = f"{status} ({reason})" if reason else status
    if error:
        verdict = f"{verdict}: {error}"
    return verdict


def _propose_step_verdict(propose_result: Mapping[str, object]) -> str:
    if not propose_result:
        return "skipped"

    success = propose_result.get("success")
    succeeded = success is True or (
        isinstance(success, str) and success.lower() == "true"
    )
    failed = success is False or (
        isinstance(success, str) and success.lower() == "false"
    )
    if succeeded:
        return "succeeded without a proposal ID"
    if failed:
        error = str(propose_result.get("error") or "").strip()
        return f"failed ({error})" if error else "failed"

    outcome = propose_result.get("outcome") or propose_result.get("status")
    if outcome:
        return str(outcome)
    return "did not return a successful proposal"


def build_no_proposal_error_summary(
    artifacts_dir: str,
    *,
    propose_result: Mapping[str, object] | None = None,
) -> str:
    """Explain why an otherwise-completed review run produced no proposal."""
    generic = _finalizer_verdict(artifacts_dir)
    if generic is None:
        details = [f"commit finalizer: {_commit_finalizer_verdict(artifacts_dir)}"]
    else:
        details = [f"finalizers: {generic}"]
    if propose_result is not None:
        details.append(f"propose step: {_propose_step_verdict(propose_result)}")
    return "Agent completed but no proposal was created — " + "; ".join(details)


def format_markdown_fenced_block(content: str, info: str = "") -> str:
    """Return a Markdown fenced block that cannot be closed by ``content``."""
    longest_backtick_run = 0
    current_run = 0
    for char in content:
        if char == "`":
            current_run += 1
            longest_backtick_run = max(longest_backtick_run, current_run)
        else:
            current_run = 0
    fence = "`" * max(3, longest_backtick_run + 1)
    info_suffix = info if info else ""
    if content.endswith("\n"):
        return f"{fence}{info_suffix}\n{content}{fence}"
    return f"{fence}{info_suffix}\n{content}\n{fence}"


def _read_submitted_xprompt_fallback(
    artifacts_dir: str,
    submitted_xprompt_path: str | None,
) -> str | None:
    paths = []
    if submitted_xprompt_path:
        paths.append(submitted_xprompt_path)
    paths.extend(
        [
            os.path.join(artifacts_dir, "submitted_xprompt.md"),
            os.path.join(artifacts_dir, "raw_xprompt.md"),
        ]
    )
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            continue
    return None


def _table_value(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value.replace("|", "\\|").replace("\n", "<br>")


def write_error_report(
    artifacts_dir: str,
    *,
    agent_model: str | None,
    agent_llm_provider: str | None,
    workflow_name: str,
    cl_name: str,
    duration: str,
    error_summary: str,
    error_traceback: str | None,
    submitted_xprompt: str | None = None,
    submitted_xprompt_path: str | None = None,
    workspace_dir: str | None = None,
    held_workspace_num: int | None = None,
    output_path: str | None = None,
    agent_name: str | None = None,
) -> str | None:
    """Write a formatted error report to the artifacts directory.

    Returns the file path, or None if writing failed.
    """
    try:
        from sase.llm_provider.registry import format_provider_model_label

        report_path = os.path.join(artifacts_dir, "error_report.md")
        label = format_provider_model_label(agent_llm_provider, agent_model)

        summary_rows = [
            ("Model", label),
            ("Workflow", workflow_name),
            ("Patch", cl_name),
            ("Duration", duration),
            ("Agent name", agent_name),
            ("Artifact directory", artifacts_dir),
            ("Workspace directory", workspace_dir),
            (
                "Held workspace",
                f"#{held_workspace_num}" if held_workspace_num is not None else None,
            ),
            ("Output log path", output_path),
        ]
        lines = [
            "# Agent Error Report",
            "",
            "## Summary",
            "",
            "| Field | Value |",
            "|-------|-------|",
        ]
        for field, value in summary_rows:
            table_value = _table_value(value)
            if table_value is not None:
                lines.append(f"| {field} | {table_value} |")

        if submitted_xprompt is None:
            submitted_xprompt = _read_submitted_xprompt_fallback(
                artifacts_dir, submitted_xprompt_path
            )

        if submitted_xprompt is not None:
            lines.extend(
                [
                    "",
                    "## Submitted XPrompt",
                    "",
                    format_markdown_fenced_block(submitted_xprompt, "markdown"),
                ]
            )

        lines.extend(
            [
                "",
                "## Error",
                "",
                format_markdown_fenced_block(error_summary),
            ]
        )

        if error_traceback:
            lines.extend(
                [
                    "",
                    "## Traceback",
                    "",
                    format_markdown_fenced_block(error_traceback.rstrip()),
                ]
            )

        if held_workspace_num is not None:
            lines.extend(
                [
                    "",
                    "## Workspace recovery",
                    "",
                    f"Workspace #{held_workspace_num} is held for this failed run. "
                    "Inspect or commit its changes, then dismiss the failed agent "
                    "in `sase ace` to release it.",
                ]
            )

        lines.append("")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path
    except Exception:
        return None


def finalize_axe_runner(
    project_file: str,
    changespec_name: str,
    proposal_id: str | None,
    exit_code: int,
    update_suffix_fn: Callable[[Patch, str, str | None, int], None],
) -> None:
    """Run common finalization logic for axe runners."""
    try:
        patches = parse_project_file(project_file)
        for cs in patches:
            if cs.name == changespec_name:
                update_suffix_fn(cs, project_file, proposal_id, exit_code)
                break
    except Exception as e:
        print(f"Warning: Failed to update suffix: {e}")

    print()
    print(f"===WORKFLOW_COMPLETE=== PROPOSAL_ID: {proposal_id} EXIT_CODE: {exit_code}")
