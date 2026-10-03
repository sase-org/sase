"""Provider and macro discovery for generated skills."""

from pathlib import Path

from sase.llm_provider.registry import iter_plugins
from sase.macro.models import Macro


def all_providers() -> list[str]:
    """Return every registered provider name from ``sase_llm`` entry points."""
    return [name for name, _ in iter_plugins()]


def provider_context(provider: str) -> dict[str, str]:
    """Return the Jinja2 rendering context supplied by a provider plugin."""
    for name, plugin in iter_plugins():
        if name != provider:
            continue
        method = getattr(plugin, "llm_skill_template_context", None)
        if method is None:
            return {}
        return method() or {}
    return {}


def skill_deploy_subpaths(provider: str) -> list[str]:
    """Return the home-relative skill deployment directories for a provider."""
    primary: str | None = f".{provider}"
    additional: list[str] = []

    for name, plugin in iter_plugins():
        if name != provider:
            continue
        method = getattr(plugin, "llm_skill_deploy_subpath", None)
        if method is not None:
            subpath = method()
            primary = str(subpath) if subpath else None
        additional_method = getattr(
            plugin, "llm_additional_skill_deploy_subpaths", None
        )
        if additional_method is not None:
            subpaths = additional_method() or []
            if isinstance(subpaths, str):
                additional = [subpaths]
            else:
                additional = list(subpaths)
        break

    result: list[str] = []
    seen: set[str] = set()
    for subpath in [primary, *additional]:
        if subpath is None:
            continue
        normalized = str(subpath).strip("/")
        if not normalized or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result


def target_path_for_subpath(
    subpath: str,
    skill_name: str,
    *,
    use_chezmoi: bool,
    chezmoi_home: Path,
) -> Path:
    """Return the deployment path for one provider skill subpath."""
    if use_chezmoi:
        # Only the first path segment is a dotfile under chezmoi; nested
        # directories keep their plain names.
        parts = subpath.split("/")
        parts[0] = "dot_" + parts[0].removeprefix(".")
        return chezmoi_home / Path(*parts) / "skills" / skill_name / "SKILL.md"
    return Path.home() / subpath / "skills" / skill_name / "SKILL.md"


def select_skill_macros(*catalogs: dict[str, Macro]) -> list[Macro]:
    """Merge catalogs and return macros installable as provider skills.

    Only definitions loaded from a canonical skill source carry a
    ``skill_name``, so that is the selector: a truthy ``skill`` value anywhere
    else was already rejected at load time. Ordering follows the provider
    skill name, which is what every generated target is keyed by.
    """
    macros: dict[str, Macro] = {}
    for catalog in catalogs:
        macros.update(catalog)
    return sorted(
        (xp for xp in macros.values() if xp.skill and xp.skill_name),
        key=lambda xp: (xp.skill_name or "", xp.name),
    )
