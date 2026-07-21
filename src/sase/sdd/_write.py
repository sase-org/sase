"""SDD prompt, plan, and Q&A file writes."""

from pathlib import Path

from sase.sdd._paths import get_yyyymm
from sase.sdd.artifact_links import (
    SddArtifactLinkType,
    stable_sdd_reference,
    update_source_aware_artifact_link,
)

_QA_HEADER = "### Questions and Answers"


def sdd_link_path(sdd_dir: Path, path: Path) -> str:
    """Return the stable relative path used as an artifact-link label."""
    return stable_sdd_reference(sdd_dir, path)


def write_sdd_spec(
    sdd_dir: Path,
    plan_name: str,
    prompt_content: str,
    *,
    plans_root: Path | None = None,
    yyyymm: str | None = None,
) -> tuple[Path, Path]:
    """Write only the prompt snapshot for a future canonical plan.

    Returns ``(prompt_path, plan_path)`` so callers can record the canonical
    plan destination without taking ownership of writing the plan itself.
    """
    yyyymm = get_yyyymm() if yyyymm is None else yyyymm
    plans_dir = (sdd_dir / "plans" if plans_root is None else plans_root) / yyyymm
    prompts_dir = plans_dir / "prompts"
    prompt_path = prompts_dir / f"{plan_name}.md"
    plan_path = plans_dir / f"{plan_name}.md"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        update_source_aware_artifact_link(
            prompt_content,
            sdd_dir,
            prompt_path,
            plan_path,
            SddArtifactLinkType.PLAN,
            label_prefix="../",
            remove_legacy=True,
        ),
        encoding="utf-8",
    )
    return prompt_path, plan_path


def write_sdd_files(
    sdd_dir: Path,
    plan_name: str,
    prompt_content: str,
    plan_file: str,
    *,
    plan_tier: str = "tale",
    plans_root: Path | None = None,
    yyyymm: str | None = None,
) -> tuple[Path, Path]:
    """Write plans/<YYYYMM>/prompts/<name>.md and its paired plan.

    Returns (prompt_path, plan_path).
    """
    from sase.sdd.plan_tiers import normalize_plan_tier

    tier = normalize_plan_tier(plan_tier)
    if tier is None:
        raise ValueError(
            f"invalid SDD plan tier {plan_tier!r}; expected 'tale' or 'epic'"
        )

    yyyymm = get_yyyymm() if yyyymm is None else yyyymm
    plans_dir = (sdd_dir / "plans" if plans_root is None else plans_root) / yyyymm
    prompt_path = plans_dir / "prompts" / f"{plan_name}.md"
    plan_path = plans_dir / f"{plan_name}.md"
    from sase.sdd.frontmatter import set_frontmatter_fields

    plan_content: str | None = None
    plan_source = Path(plan_file)
    if plan_source.exists():
        from sase.file_references import format_with_prettier
        from sase.llm_provider._plan_utils import add_create_time_frontmatter
        from sase.sdd.committed_plan_validation import validate_plan_for_commit

        plan_content = plan_source.read_text(encoding="utf-8")
        plan_content = format_with_prettier(plan_content)
        plan_content = add_create_time_frontmatter(plan_content)
        plan_content = set_frontmatter_fields(plan_content, {"tier": tier})
        plan_content = update_source_aware_artifact_link(
            plan_content,
            sdd_dir,
            plan_path,
            prompt_path,
            SddArtifactLinkType.PROMPT,
            remove_legacy=True,
        )
        validate_plan_for_commit(
            plan_content,
            tier=tier,
            path=plan_path,
            yyyymm=yyyymm,
        )

    prompt_path, plan_path = write_sdd_spec(
        sdd_dir,
        plan_name,
        prompt_content,
        plans_root=plans_root,
        yyyymm=yyyymm,
    )

    if plan_content is not None:
        plan_path.write_text(plan_content, encoding="utf-8")

    return prompt_path, plan_path


def strip_qa_block(text: str) -> str:
    """Remove existing ``### Questions and Answers`` block(s) from ``text``."""
    end_marker = "%xprompts_enabled:true"
    start_marker = "%xprompts_enabled:false"
    while _QA_HEADER in text:
        idx = text.find(_QA_HEADER)
        wrapper_start = text.rfind(start_marker, 0, idx)
        wrapper_end = -1
        if wrapper_start != -1:
            between = text[wrapper_start + len(start_marker) : idx]
            if between.strip() != "":
                wrapper_start = -1
            else:
                wrapper_end = text.find(end_marker, idx)
                if wrapper_end == -1:
                    wrapper_start = -1

        if wrapper_start != -1:
            block_start = wrapper_start
            block_end = wrapper_end + len(end_marker)
        else:
            block_start = idx
            block_end = len(text)

        while block_start > 0 and text[block_start - 1] in ("\n", " ", "\t"):
            block_start -= 1
        text = text[:block_start] + text[block_end:]
    return text


def set_prompt_qa(prompt_path: Path, qa_markdown: str) -> None:
    """Replace (or insert) the Q&A section in an SDD prompt snapshot.

    Any pre-existing ``### Questions and Answers`` block is stripped first, so
    the snapshot ends up with exactly one merged block matching the follow-up
    agent's prompt.

    No-op if the prompt file doesn't exist.
    """
    if not prompt_path.exists():
        return
    existing = prompt_path.read_text(encoding="utf-8")
    stripped = strip_qa_block(existing).rstrip("\n")
    prompt_path.write_text(stripped + "\n\n" + qa_markdown + "\n", encoding="utf-8")


def update_prompt_with_qa(prompt_path: Path, qa_markdown: str) -> None:
    """Replace the Q&A section in an existing prompt snapshot."""
    set_prompt_qa(prompt_path, qa_markdown)


def update_spec_with_qa(spec_path: Path, qa_markdown: str) -> None:
    """Replace Q&A in an SDD prompt snapshot.

    Compatibility wrapper for callers still using the old ``spec`` terminology.
    """
    set_prompt_qa(spec_path, qa_markdown)
