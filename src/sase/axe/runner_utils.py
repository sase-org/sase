"""Shared utilities for axe runner scripts."""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from sase.ace.agent_tags import REVIEW_AGENT_TAG
from sase.ace.changespec import ChangeSpec, parse_project_file
from sase.vcs_provider import get_vcs_provider

logger = logging.getLogger(__name__)

# Global state for SIGTERM handler.
_killed_state: dict[str, object] = {"killed": False, "killed_at": None}


def was_killed() -> bool:
    """Check if the process received SIGTERM."""
    return bool(_killed_state["killed"])


def killed_at() -> float | None:
    """Return the wall-clock timestamp for the most recent SIGTERM."""
    value = _killed_state.get("killed_at")
    return value if isinstance(value, float) else None


def install_sigterm_handler(
    description: str = "process",
    *,
    soft: bool = False,
    on_signal: Callable[[], None] | None = None,
) -> None:
    """Install a SIGTERM handler that sets killed flag and exits gracefully.

    The handler uses sys.exit() instead of re-raising SIGTERM so that
    finally blocks run, ensuring workspace cleanup happens before exit.

    Args:
        description: What was killed (e.g., "agent", "mentor", "workflow").
        soft: When True, set the killed flag but don't call sys.exit().
            This allows the caller to detect the kill and handle it
            (e.g., check for marker files before deciding what to do).
        on_signal: Optional best-effort cleanup callback to run before exit.
    """

    def _handler(_signum: int, _frame: object) -> None:
        _killed_state["killed"] = True
        _killed_state["killed_at"] = time.time()
        print(f"\nReceived SIGTERM - {description} was killed", file=sys.stderr)
        if on_signal is not None:
            try:
                on_signal()
            except Exception:
                logger.exception("SIGTERM cleanup callback failed")
        if not soft:
            sys.exit(128 + signal.SIGTERM)

    signal.signal(signal.SIGTERM, _handler)


def reset_killed() -> None:
    """Clear the killed flag between follow-up loop iterations."""
    _killed_state["killed"] = False
    _killed_state["killed_at"] = None


# Minimum age before a leftover ``.git/index.lock`` is treated as abandoned.
# Comfortably longer than any normal index operation, so we never race a lock
# a live git process just created.
_STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS = 15.0


def git_index_lock_path(workspace_dir: str) -> Path | None:
    """Resolve the ``index.lock`` path for *workspace_dir*'s git dir, if any."""
    git_path = Path(workspace_dir) / ".git"
    if git_path.is_dir():
        return git_path / "index.lock"
    # Worktrees/submodules store ``.git`` as a file pointing at the real git
    # dir; ask git where the index lives instead of guessing.
    if not git_path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    git_dir = result.stdout.strip()
    if result.returncode != 0 or not git_dir:
        return None
    git_dir_path = Path(git_dir)
    if not git_dir_path.is_absolute():
        git_dir_path = Path(workspace_dir) / git_dir_path
    return git_dir_path / "index.lock"


def _clear_stale_git_index_lock(
    workspace_dir: str,
    *,
    min_age_seconds: float = _STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
) -> bool:
    """Remove an abandoned ``.git/index.lock`` from *workspace_dir*.

    Returns True only when a stale lock was removed. A missing lock, a lock
    younger than *min_age_seconds* (which could belong to a live git process),
    or any filesystem error is treated as a safe no-op.
    """
    lock_path = git_index_lock_path(workspace_dir)
    if lock_path is None:
        return False
    try:
        age_seconds = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        logger.debug("Could not stat git index lock %s", lock_path, exc_info=True)
        return False
    if age_seconds < min_age_seconds:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning(
            "Failed to remove stale git index lock %s", lock_path, exc_info=True
        )
        return False
    message = f"Removed stale git index lock ({age_seconds:.0f}s old): {lock_path}"
    print(message, file=sys.stderr)
    logger.warning(message)
    return True


def prepare_workspace(
    workspace_dir: str,
    cl_name: str,
    update_target: str,
    backup_suffix: str = "ace",
    project_basename: str = "",
) -> bool:
    """Clean and update workspace before running agent or workflow.

    Args:
        workspace_dir: The workspace directory.
        cl_name: Display name for the ChangeSpec/project (used for backup diff name).
        update_target: What to checkout (ChangeSpec branch or "p4head").
        backup_suffix: Suffix appended to cl_name for the backup diff name
            (e.g., "ace" produces "{cl_name}-ace").
        project_basename: Project basename for resolving changespec names to
            git branch names.

    Returns:
        True if successful, False otherwise.
    """
    from sase.workflows.commit_utils import run_sase_hg_clean

    # An index.lock left behind by a crashed or SIGTERM-killed git process
    # blocks every subsequent operation in this clone ("Another git process
    # seems to be running..."), which would fail the clean/checkout below. This
    # runs against a workspace we have exclusively claimed, so a lock old enough
    # to predate the claim is abandoned; clear it as git itself instructs.
    _clear_stale_git_index_lock(workspace_dir)

    # Clean workspace (saves any existing changes to a diff file)
    print("Cleaning workspace...")
    success, error = run_sase_hg_clean(workspace_dir, f"{cl_name}-{backup_suffix}")
    if not success:
        print(f"sase_hg_clean failed: {error}", file=sys.stderr)
        return False

    # Update workspace to target
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    provider = get_vcs_provider(workspace_dir)
    is_default_parent = update_target == VCS_DEFAULT_REVISION
    if is_default_parent:
        update_target = provider.get_default_parent_revision(workspace_dir)
    elif project_basename:
        update_target = provider.resolve_revision(
            update_target, project_basename, workspace_dir
        )
    print(f"Updating workspace to {update_target}...")
    checkout_ok, checkout_err = provider.checkout(update_target, workspace_dir)
    if not checkout_ok:
        print(f"sase_hg_update failed: {checkout_err}", file=sys.stderr)
        return False

    if is_default_parent:
        try:
            sync_ok, sync_err = provider.sync_workspace(workspace_dir)
        except NotImplementedError:
            sync_ok, sync_err = True, None
        if not sync_ok:
            print(f"sync_workspace failed: {sync_err}", file=sys.stderr)
            return False

    print("Workspace ready")
    return True


def all_steps_hidden(artifacts_dir: str) -> bool:
    """Check if every step that actually ran in a workflow was hidden.

    Reads workflow_state.json from the artifacts directory and returns True
    when all steps that ran have ``hidden: true``.  Skipped steps (e.g. due
    to an ``if`` condition evaluating to false) are not considered since they
    did not actually run.  Returns False when the state file is missing,
    unreadable, or contains at least one visible step that ran.
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        logger.debug(
            "all_steps_hidden: state file missing or unreadable: %s", state_path
        )
        return False
    steps = data.get("steps", [])
    if not steps:
        logger.debug("all_steps_hidden: no steps in %s", state_path)
        return False
    result = all(
        step.get("hidden", False) or step.get("status") == "skipped" for step in steps
    )
    logger.debug(
        "all_steps_hidden: %s — steps: %s",
        result,
        [(s.get("name"), s.get("status"), s.get("hidden")) for s in steps],
    )
    return result


def write_agent_meta(
    artifacts_dir: str,
    *,
    model: str | None = None,
    llm_provider: str | None = None,
    vcs_provider: str | None = None,
    tag: str | None = None,
) -> None:
    """Write agent_meta.json to an axe runner's artifacts directory.

    This provides model/VCS metadata so the Agents tab can display it
    for axe-spawned agents (mentor, fix-hook, crs, summarize-hook).

    Args:
        artifacts_dir: Path to the artifacts directory.
        model: Model name (e.g., "Gemini 3.5 Flash (High)").
        llm_provider: LLM provider name (e.g., "agy").
        vcs_provider: VCS provider display name (e.g., "Mercurial").
        tag: Optional Agents-tab grouping tag.
    """
    meta: dict[str, object] = {"pid": os.getpid()}
    if model:
        meta["model"] = model
    if llm_provider:
        meta["llm_provider"] = llm_provider
    if vcs_provider:
        meta["vcs_provider"] = vcs_provider
    if tag:
        meta["tag"] = tag

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        from sase.core.agent_artifact_index_lifecycle import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except Exception as e:
        print(f"Warning: Failed to write agent_meta.json: {e}")


def clear_agent_meta_tag(artifacts_dir: str) -> bool:
    """Remove the Agents-tab tag from an agent_meta.json file.

    Returns True when a ``tag`` field was removed and persisted. Missing,
    unreadable, malformed, or already-untagged metadata is treated as a safe
    no-op.
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        logger.debug(
            "clear_agent_meta_tag: metadata missing or unreadable: %s",
            meta_path,
        )
        return False

    if not isinstance(data, dict) or "tag" not in data:
        return False

    data.pop("tag", None)
    tmp_path = f"{meta_path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, meta_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        logger.debug(
            "clear_agent_meta_tag: failed to write %s",
            meta_path,
            exc_info=True,
        )
        return False

    try:
        from sase.core.agent_artifact_index_lifecycle import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except Exception:
        logger.debug(
            "clear_agent_meta_tag: failed to update artifact index for %s",
            artifacts_dir,
            exc_info=True,
        )
    return True


def _detect_and_write_agent_meta(
    artifacts_dir: str,
    project_file: str,
    *,
    tag: str | None = None,
) -> None:
    """Detect model/VCS metadata and write agent_meta.json.

    Convenience wrapper that detects the current LLM provider, model, and
    VCS provider from the project file, then writes agent_meta.json.

    Args:
        artifacts_dir: Path to the artifacts directory.
        project_file: Path to the project file (used for VCS detection).
        tag: Optional Agents-tab grouping tag.
    """
    from sase.llm_provider.registry import get_default_provider_name, get_provider
    from sase.workspace_provider import detect_workflow_type, get_display_name

    # Detect model and LLM provider
    llm_provider = get_default_provider_name()
    try:
        provider = get_provider()
        model = provider.resolve_model_name()
    except Exception:
        model = None

    # Detect VCS provider
    try:
        vcs_type = detect_workflow_type(project_file)
        vcs_provider = get_display_name(vcs_type)
    except (ValueError, Exception):
        vcs_provider = None

    write_agent_meta(
        artifacts_dir,
        model=model,
        llm_provider=llm_provider,
        vcs_provider=vcs_provider,
        tag=tag,
    )


def detect_write_and_persist_review_agent_meta(
    artifacts_dir: str,
    project_file: str,
    cl_name: str,
    *,
    raw_suffix: str | None = None,
) -> None:
    """Write review-tagged metadata and persist the tag for a runner identity.

    Specialized review runners (CRS, mentor, fix-hook) bypass the generic
    prompt directive parser, so they need to write the same observable tag
    state that a ``%group:review`` launch would have produced.
    """
    _detect_and_write_agent_meta(artifacts_dir, project_file, tag=REVIEW_AGENT_TAG)

    from sase.ace.agent_tags import update_agent_tag
    from sase.ace.tui.models.agent import AgentType

    identity_suffix = raw_suffix
    if identity_suffix is None:
        identity_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
    update_agent_tag((AgentType.RUNNING, cl_name, identity_suffix), REVIEW_AGENT_TAG)


def write_done_marker(
    artifacts_dir: str,
    cl_name: str,
    project_file: str,
    timestamp: str,
    exit_code: int,
    *,
    workspace_num: int | None = None,
    response_path: str | None = None,
    diff_path: str | None = None,
    error: str | None = None,
    traceback_str: str | None = None,
    output_path: str | None = None,
    hidden: bool = True,
) -> None:
    """Write a done.json marker to an axe runner's artifacts directory.

    Args:
        artifacts_dir: Path to the artifacts directory.
        cl_name: Name of the ChangeSpec.
        project_file: Path to the project file.
        timestamp: Timestamp in YYmmdd_HHMMSS format.
        exit_code: Exit code (0 for success).
        workspace_num: Optional workspace number.
        response_path: Optional path to the response/chat file.
        diff_path: Optional path to the diff file.
        error: Optional error summary string.
        traceback_str: Optional formatted traceback string.
        output_path: Optional path to the stdout/stderr output log.
        hidden: Whether the completed row should be hidden by default.
    """
    from sase.artifacts import convert_timestamp_to_artifacts_format

    artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    outcome = "completed" if exit_code == 0 else "failed"

    done_data: dict[str, object] = {
        "cl_name": cl_name,
        "project_file": project_file,
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "outcome": outcome,
    }
    if hidden:
        done_data["hidden"] = True
    if workspace_num is not None:
        done_data["workspace_num"] = workspace_num
    if response_path:
        done_data["response_path"] = response_path
    if diff_path:
        done_data["diff_path"] = diff_path
    if error:
        done_data["error"] = error
    if traceback_str:
        done_data["traceback"] = traceback_str
    if output_path:
        done_data["output_path"] = output_path

    done_path = os.path.join(artifacts_dir, "done.json")
    try:
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_data, f, indent=2)
        from sase.core.agent_artifact_index_lifecycle import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
        print(f"Done marker written to: {done_path}")
    except Exception as e:
        print(f"Warning: Failed to write done marker: {e}")


def read_agent_meta(artifacts_dir: str) -> dict[str, str | None]:
    """Read agent_meta.json and return model/provider info.

    Returns:
        Dict with ``model`` and ``llm_provider`` keys (values may be None).
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    result: dict[str, str | None] = {"model": None, "llm_provider": None}
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
        result["model"] = data.get("model")
        result["llm_provider"] = data.get("llm_provider")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return result


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
            ("ChangeSpec", cl_name),
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
    update_suffix_fn: Callable[[ChangeSpec, str, str | None, int], None],
) -> None:
    """Common finalization logic for axe runners.

    Args:
        project_file: Path to the project file.
        changespec_name: Name of the ChangeSpec.
        proposal_id: Proposal ID if successful, None otherwise.
        exit_code: Exit code (0 for success).
        update_suffix_fn: Callback to update the suffix (hook or comment).
            Receives (changespec, project_file, proposal_id, exit_code).
    """
    # Update suffix based on result
    try:
        changespecs = parse_project_file(project_file)
        for cs in changespecs:
            if cs.name == changespec_name:
                update_suffix_fn(cs, project_file, proposal_id, exit_code)
                break
    except Exception as e:
        print(f"Warning: Failed to update suffix: {e}")

    # Write completion marker
    print()
    print(f"===WORKFLOW_COMPLETE=== PROPOSAL_ID: {proposal_id} EXIT_CODE: {exit_code}")
