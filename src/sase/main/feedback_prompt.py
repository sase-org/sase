"""Shared feedback-replan prompt assembly."""

from __future__ import annotations

from pathlib import Path

from sase.core.commit_finalizer_prompt_artifacts import (
    is_commit_finalizer_followup_prompt,
)
from sase.main.qa_markdown import QARound
from sase.main.qa_prompt import merge_qa_for_prompt

_ADDITIONAL_REQUIREMENTS_HEADING = "### Additional Requirements"


class _FeedbackPromptError(ValueError):
    """Raised when a feedback prompt cannot be assembled from artifacts."""


def assemble_feedback_replan_prompt(
    original_prompt: str,
    feedback_bullets: list[str],
    qa_rounds: list[QARound] | None = None,
) -> str:
    """Build the same feedback replan body the plan runner uses."""
    base = original_prompt
    if qa_rounds:
        base += "\n\n" + merge_qa_for_prompt(qa_rounds)
    reqs = "\n".join(f"- {fb}" for fb in feedback_bullets)
    return f"{base}\n\n{_ADDITIONAL_REQUIREMENTS_HEADING}\n\n{reqs}"


def _append_feedback_replan_prompt(existing_prompt: str, feedback: str) -> str:
    """Append one feedback item to an existing feedback-capable prompt."""
    base, existing_feedback = _split_feedback_replan_prompt(existing_prompt)
    return assemble_feedback_replan_prompt(base, [*existing_feedback, feedback])


def _assemble_feedback_replan_prompt_from_parent(parent: str, feedback: str) -> str:
    """Resolve *parent* and append *feedback* to its prompt artifacts."""
    parent = parent.strip()
    if not parent:
        raise _FeedbackPromptError("parent is required")

    from sase.agent.names import resolve_resume_agent_name

    agent = resolve_resume_agent_name(parent)
    if agent is None:
        raise _FeedbackPromptError(f"unknown parent agent: {parent}")

    artifacts_dir = Path(agent.artifacts_dir).expanduser()
    prompt = _read_feedback_parent_prompt(artifacts_dir)
    if prompt is None:
        raise _FeedbackPromptError(
            f"no prompt artifact found for parent agent {parent!r} at {artifacts_dir}"
        )
    return _append_feedback_replan_prompt(prompt, feedback)


def _read_feedback_parent_prompt(artifacts_dir: Path) -> str | None:
    """Read the prompt body to extend for ``#with_feedback``."""
    candidates = _feedback_prompt_candidates(artifacts_dir)
    for path in candidates:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def _split_feedback_replan_prompt(prompt: str) -> tuple[str, list[str]]:
    """Split a feedback prompt into base prompt and existing feedback bullets."""
    marker = f"\n\n{_ADDITIONAL_REQUIREMENTS_HEADING}\n\n"
    if marker not in prompt:
        return prompt, []

    base, requirements = prompt.rsplit(marker, 1)
    return base, _parse_feedback_bullets(requirements)


def _feedback_prompt_candidates(artifacts_dir: Path) -> list[Path]:
    followup = artifacts_dir / "followup_prompt.md"
    if followup.is_file():
        return [followup]

    prompt_files: list[Path] = []
    try:
        prompt_files = [
            path
            for path in artifacts_dir.glob("*_prompt.md")
            if path.is_file()
            and path.name != "followup_prompt.md"
            and not is_commit_finalizer_followup_prompt(path.name)
        ]
    except OSError:
        prompt_files = []

    prompt_files.sort(key=lambda path: _mtime_ns(path), reverse=True)
    raw_prompt = artifacts_dir / "raw_xprompt.md"
    if raw_prompt.is_file():
        prompt_files.append(raw_prompt)
    return prompt_files


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _parse_feedback_bullets(requirements: str) -> list[str]:
    bullets: list[str] = []
    current: list[str] = []
    for line in requirements.splitlines():
        if line.startswith("- "):
            if current:
                bullets.append("\n".join(current))
            current = [line[2:]]
            continue
        if current:
            current.append(line)
        elif line.strip():
            current = [line]
    if current:
        bullets.append("\n".join(current))
    return bullets


# Keep a same-file reference so symvision accepts this YAML-only entry point.
_FEEDBACK_XPROMPT_ENTRYPOINTS = (_assemble_feedback_replan_prompt_from_parent,)
