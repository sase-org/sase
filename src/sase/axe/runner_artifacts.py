"""Artifact and metadata helpers shared by axe runners."""

import json
import logging
import os

from sase.ace.agent_tags import REVIEW_AGENT_TAG

logger = logging.getLogger(__name__)


def all_steps_hidden(artifacts_dir: str) -> bool:
    """Check if every step that actually ran in a workflow was hidden.

    Reads workflow_state.json from the artifacts directory and returns True
    when all steps that ran have ``hidden: true``. Skipped steps (e.g. due
    to an ``if`` condition evaluating to false) are not considered since they
    did not actually run. Returns False when the state file is missing,
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

    llm_provider = get_default_provider_name()
    try:
        provider = get_provider()
        model = provider.resolve_model_name()
    except Exception:
        model = None

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
    state that a ``%tribe:review`` launch would have produced.
    """
    _detect_and_write_agent_meta(artifacts_dir, project_file, tag=REVIEW_AGENT_TAG)

    from sase.ace.agent_tags import update_agent_tag
    from sase.ace.tui.models.agent import AgentType

    identity_suffix = raw_suffix
    if identity_suffix is None:
        identity_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
    update_agent_tag((AgentType.RUNNING, cl_name, identity_suffix), REVIEW_AGENT_TAG)


def publish_review_agent_env(
    artifacts_dir: str,
    *,
    cl_name: str,
    project_file: str,
) -> None:
    """Publish the shared agent phase and ChangeSpec environment.

    Standalone review runners do not pass through ``run_execution_loop``, so
    they must publish this environment themselves before invoking a provider.
    Embedded commit workflows remain responsible for publishing their own
    ``SASE_COMMIT_METHOD`` during prompt expansion.
    """
    from sase.axe.run_agent_exec_markers import publish_phase_env

    publish_phase_env(artifacts_dir)
    os.environ["SASE_AGENT_CL_NAME"] = cl_name
    os.environ["SASE_AGENT_PROJECT_FILE"] = project_file


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
