"""Postprocessing utilities for LLM responses.

Handles logging, chat history, audio notifications, and Rich display
after an LLM invocation completes (success or error).
"""

import os
from datetime import datetime

from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.core.time import get_timezone
from sase.output import print_prompt_and_response
from sase.artifacts import get_sase_log_file, run_bam_command

from .types import _MODEL_TIER_TO_LABEL, LoggingContext, ModelTier


def log_prompt_and_response(
    prompt: str,
    response: str,
    artifacts_dir: str,
    agent_type: str = "agent",
    iteration: int | None = None,
    workflow_tag: str | None = None,
) -> None:
    """Log a prompt and response to the workflow-specific sase.md file.

    Args:
        prompt: The prompt sent to the AI.
        response: The response received from the AI.
        artifacts_dir: Directory where the sase.md file should be stored.
        agent_type: Type of agent (e.g., "editor", "planner").
        iteration: Iteration number if applicable.
        workflow_tag: Workflow tag if available.
    """
    try:
        log_file = get_sase_log_file(artifacts_dir)
        timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")

        # Create header for this entry
        header_parts = [agent_type]
        if iteration is not None:
            header_parts.append(f"iteration {iteration}")
        if workflow_tag:
            header_parts.append(f"tag {workflow_tag}")

        header = " - ".join(header_parts)

        # Format the log entry
        log_entry = f"""
## {timestamp} - {header}

### PROMPT:
```
{prompt}
```

### RESPONSE:
```
{response}
```

---

"""

        # Append to the log file
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)

    except Exception as e:
        print(f"Warning: Failed to log prompt and response to sase.md: {e}")


def save_prompt_to_file(
    prompt: str,
    artifacts_dir: str,
    agent_type: str = "agent",
    iteration: int | None = None,
) -> None:
    """Save the prompt to a file in the artifacts directory before running the agent.

    Args:
        prompt: The prompt to save.
        artifacts_dir: Directory where the prompt file should be stored.
        agent_type: Type of agent (e.g., "editor", "planner").
        iteration: Iteration number if applicable.
    """
    try:
        # Build filename matching response file naming pattern
        if iteration is not None:
            filename = f"{agent_type}_iter_{iteration}_prompt.md"
        else:
            filename = f"{agent_type}_prompt.md"

        prompt_path = os.path.join(artifacts_dir, filename)
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
    except Exception as e:
        print(f"Warning: Failed to save prompt to file: {e}")


def postprocess_success(
    prompt: str,
    response: str,
    context: LoggingContext,
    model_tier: ModelTier,
    start_timestamp: str,
) -> None:
    """Handle postprocessing after a successful LLM invocation.

    Includes: audio notification, logging to sase.md, saving chat history.

    Args:
        prompt: The preprocessed prompt that was sent.
        response: The response text from the LLM.
        context: The logging context.
        model_tier: The model tier used.
        start_timestamp: Timestamp when the invocation started.
    """
    # Play audio notification (only if not suppressed)
    if not context.suppress_output:
        run_bam_command("Agent reply received", delay=0.2)

    # Log the prompt and response to sase.md
    if context.artifacts_dir:
        log_prompt_and_response(
            prompt=prompt,
            response=response,
            artifacts_dir=context.artifacts_dir,
            agent_type=context.agent_type,
            iteration=context.iteration,
            workflow_tag=context.workflow_tag,
        )

    # Save to central chat history (~/.sase/chats/) if workflow is set
    if context.workflow:
        try:
            _save_to_chat_history(
                prompt=prompt,
                response=response,
                context=context,
                start_timestamp=start_timestamp,
            )
        except Exception as e:
            print(f"Warning: Failed to save chat history: {e}")


def postprocess_error(
    prompt: str,
    error_content: str,
    context: LoggingContext,
    model_tier: ModelTier,
    start_timestamp: str,
) -> None:
    """Handle postprocessing after a failed LLM invocation.

    Includes: Rich error display, logging to sase.md, saving error chat history.

    Args:
        prompt: The preprocessed prompt that was sent.
        error_content: The error message/content.
        context: The logging context.
        model_tier: The model tier used.
        start_timestamp: Timestamp when the invocation started.
    """
    model_tier_label = _MODEL_TIER_TO_LABEL[model_tier]
    agent_type_with_tier = f"{context.agent_type} [{model_tier_label}]"

    # Print error using Rich formatting (only if not suppressed)
    if not context.suppress_output:
        print_prompt_and_response(
            prompt=prompt,
            response=error_content,
            agent_type=f"{agent_type_with_tier}_ERROR",
            iteration=context.iteration,
            show_prompt=True,
        )

    # Log the error to sase.md
    if context.artifacts_dir:
        log_prompt_and_response(
            prompt=prompt,
            response=error_content,
            artifacts_dir=context.artifacts_dir,
            agent_type=f"{context.agent_type}_ERROR",
            iteration=context.iteration,
            workflow_tag=context.workflow_tag,
        )

    # Save error to central chat history if workflow is set
    if context.workflow:
        _save_error_to_chat_history(
            prompt=prompt,
            error_content=error_content,
            context=context,
            start_timestamp=start_timestamp,
        )


def _save_to_chat_history(
    prompt: str,
    response: str,
    context: LoggingContext,
    start_timestamp: str,
) -> None:
    """Save prompt/response to central chat history."""
    chat_agent: str | None = None
    if context.agent_type:
        normalized_agent = context.agent_type.replace("-", "_")
        normalized_workflow = (context.workflow or "").replace("-", "_")
        if normalized_agent != normalized_workflow:
            chat_agent = context.agent_type

    extra = None
    if context.artifacts_dir:
        extra = format_extra_sections(context.artifacts_dir)

    save_chat_history(
        prompt=prompt,
        response=response,
        workflow=context.workflow or "",
        agent=chat_agent,
        timestamp=start_timestamp,
        extra_sections=extra,
        branch_or_workspace=context.branch_or_workspace,
    )


def _save_error_to_chat_history(
    prompt: str,
    error_content: str,
    context: LoggingContext,
    start_timestamp: str,
) -> None:
    """Save error to central chat history."""
    if context.agent_type:
        normalized_agent = context.agent_type.replace("-", "_")
        normalized_workflow = (context.workflow or "").replace("-", "_")
        if normalized_agent != normalized_workflow:
            chat_agent_error = f"{context.agent_type}_ERROR"
        else:
            chat_agent_error = "_ERROR"
    else:
        chat_agent_error = "_ERROR"

    extra = None
    if context.artifacts_dir:
        extra = format_extra_sections(context.artifacts_dir)

    save_chat_history(
        prompt=prompt,
        response=error_content,
        workflow=context.workflow or "",
        agent=chat_agent_error,
        timestamp=start_timestamp,
        extra_sections=extra,
        branch_or_workspace=context.branch_or_workspace,
    )
