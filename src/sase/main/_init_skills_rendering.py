"""Rendering and change planning for generated provider skills."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import jinja2
import yaml  # type: ignore[import-untyped]

from sase.main.init_plan import InitOperation
from sase.markdown_width import markdown_print_width, prettier_markdown_argv
from sase.mdtemplates import render_markdown_template
from sase.xprompt.models import XPrompt


# Skill planning runs inside ``sase doctor`` (config.init), which promises
# bounded checks. A hung prettier shim must degrade to unformatted output.
_PRETTIER_TIMEOUT_SECONDS = 10.0
_PRETTIER_COMMENT_RE = re.compile(r"^<!-- prettier-ignore[^\n]*-->\n?", re.MULTILINE)
_YAML_BLOCK_INDENT = "  "
_SKILL_FRAME_TEMPLATE_FILENAME = "SKILL.frame.template.md"
_SKILL_FRAME_TEMPLATE_VARS = frozenset(
    {"frontmatter", "log_skill_use", "skill_name", "body"}
)


class SkillFrameTemplateError(ValueError):
    """Raised when the packaged generated-skill frame cannot be rendered."""


@dataclass(frozen=True)
class RenderedSkillTarget:
    """One generated skill file target."""

    path: Path
    content: str
    provider: str
    skill_name: str


@dataclass(frozen=True)
class _RawRenderedSkillTarget:
    """One generated skill file target before Markdown formatting."""

    path: Path
    content: str
    provider: str
    skill_name: str


def _render_skill(
    body: str, description: str, context: dict[str, str]
) -> tuple[str, str]:
    """Render a skill body and description through Jinja2."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    rendered_body = env.from_string(body).render(context)
    rendered_desc = env.from_string(description).render(context)
    # Strip prettier-ignore comments (template metadata, not skill content).
    rendered_body = _PRETTIER_COMMENT_RE.sub("", rendered_body)
    # Collapse resulting triple+ blank lines and strip leading blanks.
    rendered_body = re.sub(r"\n{3,}", "\n\n", rendered_body)
    rendered_body = rendered_body.lstrip("\n")
    return rendered_body, rendered_desc


def _validate_skill_frame(content: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return "rendered skill frame must begin with YAML frontmatter"
    try:
        close_index = lines[1:].index("---") + 1
    except ValueError:
        return "rendered skill frame must contain a closing frontmatter delimiter"
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:close_index]))
    except yaml.YAMLError as exc:
        return f"rendered skill frame has invalid YAML frontmatter: {exc}"
    if not isinstance(frontmatter, dict):
        return "rendered skill frame frontmatter must be a YAML mapping"
    missing = [key for key in ("name", "description") if key not in frontmatter]
    if missing:
        return "rendered skill frame frontmatter must contain " + ", ".join(missing)
    return None


def _build_output(
    name: str, description: str, body: str, log_skill_use: bool = True
) -> str:
    """Build final ``SKILL.md`` content with frontmatter and audit directive."""
    width = markdown_print_width()
    if "\n" in description.strip():
        header = f"---\nname: {name}\ndescription: |\n"
        for line in description.strip().splitlines():
            header += f"  {line}\n"
        header += "---"
    elif len(f"description: {description}") > width:
        wrapped = textwrap.fill(description, width=width - len(_YAML_BLOCK_INDENT))
        indented = textwrap.indent(wrapped, _YAML_BLOCK_INDENT)
        frontmatter = f"name: {name}\ndescription:\n{indented}"
        try:
            parsed = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("description") == description:
            header = f"---\n{frontmatter}\n---"
        else:
            header = f"---\nname: {name}\ndescription: >-\n{indented}\n---"
    else:
        header = f"---\nname: {name}\ndescription: {description}\n---"
    content, render_error = render_markdown_template(
        package="sase.xprompts",
        filename=f"skills/{_SKILL_FRAME_TEMPLATE_FILENAME}",
        required_variables=_SKILL_FRAME_TEMPLATE_VARS,
        context={
            "frontmatter": header,
            "log_skill_use": log_skill_use,
            "skill_name": name,
            "body": body,
        },
    )
    if render_error is not None or content is None:
        raise SkillFrameTemplateError(
            render_error or "failed to render generated skill frame"
        )
    if not content.endswith("\n"):
        content += "\n"
    validation_error = _validate_skill_frame(content)
    if validation_error is not None:
        raise SkillFrameTemplateError(
            f"packaged {_SKILL_FRAME_TEMPLATE_FILENAME}: {validation_error}"
        )
    return content


def _unescape_prettier_underscores(text: str) -> str:
    """Apply the post-Prettier underscore unescaping used by generated skills."""
    while r"\_" in text:
        text = text.replace(r"\_", "_")
    return text


def format_skill_output(output: str, *, use_prettier: bool) -> str:
    """Format generated skill Markdown with the same path used by apply."""
    if not use_prettier:
        return output

    from sase.file_references import format_with_prettier

    return format_with_prettier(output)


def format_unique_skill_outputs_batch(outputs: Sequence[str]) -> list[str]:
    """Format unique generated skill Markdown bodies with one Prettier command."""
    if not outputs:
        return []

    with tempfile.TemporaryDirectory(prefix="sase-init-skills-") as temp_dir:
        temp_path = Path(temp_dir)
        paths: list[Path] = []
        for index, output in enumerate(outputs):
            path = temp_path / f"skill-{index}.md"
            path.write_text(output, encoding="utf-8")
            paths.append(path)

        subprocess.run(
            [
                *prettier_markdown_argv(),
                "--write",
                *(str(path) for path in paths),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=_PRETTIER_TIMEOUT_SECONDS,
        )
        return [
            _unescape_prettier_underscores(path.read_text(encoding="utf-8"))
            for path in paths
        ]


def format_skill_outputs(
    outputs: Sequence[str],
    *,
    use_prettier: bool,
    batch_formatter: Callable[[list[str]], list[str]],
    single_formatter: Callable[[str], str],
) -> list[str]:
    """Format generated skill Markdown once per unique raw output."""
    raw_outputs = list(outputs)
    if not use_prettier or not raw_outputs:
        return raw_outputs

    unique_outputs: list[str] = []
    unique_indexes: dict[str, int] = {}
    for output in raw_outputs:
        if output in unique_indexes:
            continue
        unique_indexes[output] = len(unique_outputs)
        unique_outputs.append(output)

    try:
        formatted_unique_outputs = batch_formatter(unique_outputs)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        formatted_unique_outputs = [
            single_formatter(output) for output in unique_outputs
        ]

    return [formatted_unique_outputs[unique_indexes[output]] for output in raw_outputs]


def render_skill_targets(
    skill_xprompts: list[XPrompt],
    *,
    provider_filter: str | None,
    use_chezmoi: bool,
    get_target_providers: Callable[[bool | list[str]], list[str]],
    get_provider_context: Callable[[str], dict[str, str]],
    get_target_paths: Callable[[str, str, bool], list[Path]],
    format_outputs: Callable[[Sequence[str]], list[str]],
) -> list[RenderedSkillTarget]:
    """Render every selected skill/provider target without writing files."""
    raw_targets: list[_RawRenderedSkillTarget] = []

    for xprompt in skill_xprompts:
        name = xprompt.name
        description = xprompt.description or ""
        skill_field = xprompt.skill
        if not skill_field:
            continue

        target_providers = get_target_providers(skill_field)
        if provider_filter:
            target_providers = [p for p in target_providers if p == provider_filter]

        for provider in target_providers:
            context = get_provider_context(provider)
            rendered_body, rendered_desc = _render_skill(
                xprompt.content, description, context
            )
            output = _build_output(
                name,
                rendered_desc.strip(),
                rendered_body,
                log_skill_use=xprompt.log_skill_use,
            )
            for target in get_target_paths(provider, name, use_chezmoi):
                raw_targets.append(
                    _RawRenderedSkillTarget(
                        path=target,
                        content=output,
                        provider=provider,
                        skill_name=name,
                    )
                )

    formatted_outputs = format_outputs([target.content for target in raw_targets])
    return [
        RenderedSkillTarget(
            path=target.path,
            content=content,
            provider=target.provider,
            skill_name=target.skill_name,
        )
        for target, content in zip(raw_targets, formatted_outputs, strict=True)
    ]


def planned_skill_operation(
    target: RenderedSkillTarget,
) -> tuple[InitOperation, str] | None:
    """Return planned operation/detail for a skill target, or ``None``."""
    detail = f"{target.provider}/{target.skill_name}"
    if not target.path.exists():
        return "create", detail
    try:
        existing = target.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "overwrite", detail
    if existing == target.content:
        return None
    return "overwrite", detail


def summarize_skill_actions(operations: Sequence[InitOperation]) -> str:
    """Return a compact summary for generated skill actions."""
    if not operations:
        return "provider skill files are current"
    operation_set = set(operations)
    count = len(operations)
    noun = "provider skill file" if count == 1 else "provider skill files"
    if operation_set == {"create"}:
        return f"create {count} {noun}"
    if operation_set == {"overwrite"}:
        return f"overwrite {count} {noun}"
    return f"refresh {count} {noun}"
