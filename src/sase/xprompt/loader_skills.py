"""Canonical skill-source discovery and the shared placement rules.

Every Python loader routes skill decisions through this module so it enforces
exactly the rules the native Rust catalog fallback enforces: a definition is a
skill only when it lives in a canonical ``skills/`` source *and* declares a
truthy ``skill`` value, and both halves of that rule are two-way. A skill
declaration found in an ordinary xprompt, workflow, or config source is
rejected with a migration diagnostic instead of being silently loaded, and a
non-skill definition found in a canonical skill source is rejected the same
way.

Accepted skills keep their declared name as the provider-visible
:attr:`~sase.xprompt.models.XPrompt.skill_name` and take the namespaced
``skill/<name>`` (or ``<project>/skill/<name>``) xprompt reference name, so
``#skill/foo`` expands what ``/foo`` invokes.
"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path, PurePosixPath

from sase.content_layout import (
    SkillPlacementIssue,
    resolve_skill_file_sources,
    skill_placement_issue,
    skill_reference_name,
)
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

from .load_issues import record_load_issue
from .models import XPrompt

log = logging.getLogger(__name__)

SKILL_FRAME_TEMPLATE_FILENAME = "SKILL.frame.template.md"
"""Packaged Jinja frame for generated ``SKILL.md`` files, not a skill source."""

_SASE_PACKAGE = "sase"
_SASE_PACKAGE_XPROMPTS_RESOURCE = ("xprompts",)
_SASE_PACKAGE_SKILLS_RESOURCE = ("xprompts", "skills")

SKILL_PLACEMENT_ISSUE_KIND = "skill_placement"
"""``XPromptLoadIssue.kind`` for definitions the placement rules rejected."""

_PLUGIN_XPROMPT_DESTINATION = "the plugin's xprompts/ resource directory"
_PLUGIN_SKILL_DESTINATION = "the plugin's skills/ resource directory"
_CONFIG_SKILL_DESTINATION = "a Markdown file in the scope's sase/skills/ directory"


def get_sase_package_skills_dir(package_root: Path | None = None) -> Path:
    """Return the packaged skill source directory.

    Bundled skills live at ``src/sase/xprompts/skills/`` inside the package, so
    ``importlib.resources`` resolves them for both wheel and editable
    installs.
    """
    candidate = (
        Path(package_root).joinpath(*_SASE_PACKAGE_SKILLS_RESOURCE)
        if package_root is not None
        else _sase_package_resource_dir(*_SASE_PACKAGE_SKILLS_RESOURCE)
    )
    if candidate.is_dir():
        return candidate

    log.warning(
        "Packaged skills directory not found via "
        "importlib.resources('sase/xprompts/skills')",
    )
    return candidate


def get_sase_package_skill_resource(filename: str) -> str:
    """Return a package-relative resource path for one bundled skill asset."""
    return PurePosixPath(*_SASE_PACKAGE_SKILLS_RESOURCE, filename).as_posix()


def _get_sase_package_xprompts_dir() -> Path:
    return _sase_package_resource_dir(*_SASE_PACKAGE_XPROMPTS_RESOURCE)


def _sase_package_resource_dir(*parts: str) -> Path:
    return Path(str(importlib.resources.files(_SASE_PACKAGE).joinpath(*parts)))


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve(strict=False) == right.expanduser().resolve(
            strict=False
        )
    except (OSError, RuntimeError, ValueError):
        return left == right


def _record_skill_placement_issue(issue: SkillPlacementIssue | None) -> bool:
    """Record *issue* as a load issue and report whether one was present."""
    if issue is None:
        return False
    record_load_issue(issue.source, issue.message, kind=SKILL_PLACEMENT_ISSUE_KIND)
    return True


def reject_misplaced_skill(
    xprompt: XPrompt,
    *,
    source: Path | str | None = None,
    migrate_to: Path | str | None = None,
) -> bool:
    """Return whether an ordinary source illegally declares ``skill:``.

    Callers loading non-skill sources use this to drop the definition. The
    diagnostic names the offending source and the exact move required, so a
    misplaced skill is reported rather than silently missing.
    """
    return _record_skill_placement_issue(
        skill_placement_issue(
            source if source is not None else (xprompt.source_path or xprompt.name),
            in_skill_source=False,
            declares_skill=bool(xprompt.skill),
            migrate_to=migrate_to,
        )
    )


def skill_destination_for_xprompt_dir(directory: Path) -> Path | None:
    """Return the canonical skill directory for the scope owning *directory*."""
    if _same_path(directory, _get_sase_package_xprompts_dir()):
        return get_sase_package_skills_dir()

    parent = directory.parent
    if parent == directory:
        return None
    return parent / "skills"


def _xprompt_destination_for_skill_dir(directory: Path) -> Path | None:
    if _same_path(directory, get_sase_package_skills_dir()):
        return _get_sase_package_xprompts_dir()

    parent = directory.parent
    if parent == directory:
        return None
    if directory.name != "skills" and parent.name == "skills":
        return parent.parent / "xprompts" / directory.name
    return parent / "xprompts"


def _as_skill(
    xprompt: XPrompt,
    *,
    source: Path | str | None = None,
    project: str | None = None,
    migrate_to: Path | str | None = None,
) -> XPrompt | None:
    """Return *xprompt* renamed as a skill, or ``None`` when it is not one.

    *project* namespaces the reference name for project-scoped sources; pass
    ``None`` for home, package, and plugin scopes.
    """
    located = source if source is not None else (xprompt.source_path or xprompt.name)
    if _record_skill_placement_issue(
        skill_placement_issue(
            located,
            in_skill_source=True,
            declares_skill=bool(xprompt.skill),
            migrate_to=migrate_to,
        )
    ):
        return None

    xprompt.skill_name = xprompt.name
    xprompt.name = skill_reference_name(xprompt.name, project or None)
    return xprompt


def _load_skills_from_dir(
    directory: Path,
    *,
    project: str | None = None,
    namespaced: bool = False,
) -> dict[str, XPrompt]:
    """Load one canonical skill directory into reference-name keyed skills."""
    from .loader_sources import load_xprompt_from_file

    if not directory.is_dir():
        return {}

    destination = _xprompt_destination_for_skill_dir(directory)
    namespace = project if namespaced else None
    skills: dict[str, XPrompt] = {}
    for md_file in sorted(directory.glob("*.md")):
        if not md_file.is_file() or md_file.name == SKILL_FRAME_TEMPLATE_FILENAME:
            continue
        xprompt = load_xprompt_from_file(md_file)
        if xprompt is None:
            continue
        skill = _as_skill(
            xprompt,
            source=md_file,
            project=namespace,
            migrate_to=destination,
        )
        if skill is not None:
            skills[skill.name] = skill
    return skills


def load_skills_from_package() -> dict[str, XPrompt]:
    """Load the skills bundled inside the ``sase`` package."""
    return _load_skills_from_dir(get_sase_package_skills_dir())


def load_skills_from_plugins() -> dict[str, XPrompt]:
    """Load skills from plugins' sibling ``skills/`` resource directories."""
    if is_plugin_disabled("XPROMPTS"):
        return {}

    from .loader_sources import load_plugin_markdown_xprompts

    skills: dict[str, XPrompt] = {}
    for module in discover_plugin_resources("sase_xprompts"):
        for source, xprompt in load_plugin_markdown_xprompts(module, "skills"):
            skill = _as_skill(
                xprompt,
                source=source,
                migrate_to=_PLUGIN_XPROMPT_DESTINATION,
            )
            if skill is not None:
                skills[skill.name] = skill
    return skills


def plugin_skill_destination() -> str:
    """Return the migration destination for a skill in a plugin xprompt dir."""
    return _PLUGIN_SKILL_DESTINATION


def config_skill_destination() -> str:
    """Return the migration destination for a config-defined skill.

    Config-defined xprompts can never be skills: a skill must be a Markdown
    file in a canonical skill directory so generation has a source to render.
    """
    return _CONFIG_SKILL_DESTINATION


def load_skills_from_files(
    project: str | None = None,
    *,
    project_root: Path | None = None,
) -> dict[str, XPrompt]:
    """Load skills from the canonical filesystem scopes, first source wins."""
    skills: dict[str, XPrompt] = {}
    sources = resolve_skill_file_sources(project_root=project_root, project=project)
    for source in reversed(sources):
        if source.path is None:
            continue
        skills.update(
            _load_skills_from_dir(
                source.path,
                project=project,
                namespaced=source.project_namespaced,
            )
        )
    return skills


def load_project_skills(workspace_dir: Path, project: str) -> dict[str, XPrompt]:
    """Load one registered project workspace's canonical skill sources."""
    skills: dict[str, XPrompt] = {}
    sources = resolve_skill_file_sources(project_root=workspace_dir, project=project)
    for source in reversed(sources):
        if source.path is None or source.scope != "project":
            continue
        skills.update(
            _load_skills_from_dir(
                source.path,
                project=project,
                namespaced=source.project_namespaced,
            )
        )
    return skills


__all__ = [
    "SKILL_FRAME_TEMPLATE_FILENAME",
    "SKILL_PLACEMENT_ISSUE_KIND",
    "config_skill_destination",
    "get_sase_package_skill_resource",
    "get_sase_package_skills_dir",
    "load_project_skills",
    "load_skills_from_files",
    "load_skills_from_package",
    "load_skills_from_plugins",
    "plugin_skill_destination",
    "reject_misplaced_skill",
    "skill_destination_for_xprompt_dir",
]
