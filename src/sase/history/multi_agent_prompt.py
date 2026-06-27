"""Persistence helpers for original multi-agent launch prompts."""

from pathlib import Path

from sase.core.paths import make_safe_filename, sharded_path

MULTI_AGENT_PROMPT_FILE_ENV = "SASE_MULTI_AGENT_PROMPT_FILE"
MULTI_AGENT_PROMPT_METADATA_LABEL = "PROMPT"


def _render_multi_agent_prompt_file(text: str) -> str:
    """Render the text persisted for a multi-agent launch prompt."""
    return text


def save_multi_agent_prompt_file(
    text: str,
    *,
    cl_name: str,
    timestamp: str,
) -> str:
    """Persist *text* and return a path shortened like chat history paths."""
    safe_cl_name = make_safe_filename(cl_name) or "prompt"
    filename = f"{safe_cl_name}-multiprompt-{timestamp}.md"
    file_path = sharded_path("multi_prompts", filename)
    Path(file_path).write_text(_render_multi_agent_prompt_file(text), encoding="utf-8")
    return file_path.replace(str(Path.home()), "~")
