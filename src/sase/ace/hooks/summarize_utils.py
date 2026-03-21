"""Utility functions for summarizing files."""

import json

from sase.xprompt.output_validation import extract_structured_content
from sase.xprompt.workflow_runner import execute_workflow


def get_file_summary(
    target_file: str,
    usage: str,
    fallback: str = "Operation completed",
    artifacts_dir: str | None = None,
) -> str:
    """Get a summary of a file, with fallback on failure.

    This is a convenience wrapper around execute_workflow for use in
    contexts where a summary is optional and a fallback is acceptable.

    Args:
        target_file: Path to the file to summarize.
        usage: Description of how the summary will be used.
        fallback: Fallback text to use if summarization fails.
        artifacts_dir: Optional directory to save prompt artifacts.

    Returns:
        The summary (<=20 words) or fallback text.
    """
    try:
        result = execute_workflow(
            "summarize",
            positional_args=[],
            named_args={"target_file": target_file, "usage": usage},
            artifacts_dir=artifacts_dir,
            silent=True,
        )
        if result.response_text:
            data, _ = extract_structured_content(result.response_text)
            if isinstance(data, str):
                data = json.loads(data)
            summary = data.get("summary", "")
            if summary:
                return summary
    except Exception:
        pass
    return fallback
