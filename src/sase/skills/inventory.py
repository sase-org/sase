"""Read-only inventory for generated SASE skill files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.main import init_skills_handler
from sase.main._init_skills_manifest import (
    ManagedSkillFile,
    plan_skill_manifest_ownership,
    retired_skill_files_with_drift,
)
from sase.xprompt.models import XPrompt

SkillTargetStatus = Literal["current", "stale", "missing", "retired"]
AppliedSkillTargetStatus = Literal[
    "current", "stale", "missing", "source_missing", "retired"
]
SkillDeployMode = Literal["home", "chezmoi"]


@dataclass(frozen=True)
class SkillTargetEntry:
    """One rendered provider skill target and its on-disk status."""

    path: Path
    provider: str
    skill_name: str
    status: SkillTargetStatus
    home_path: Path | None = None


@dataclass(frozen=True)
class SkillSourceEntry:
    """One installable xprompt skill source.

    ``name`` is the provider-visible skill name (``foo``); ``reference_name``
    is the canonical xprompt reference that expands it (``skill/foo``).
    """

    name: str
    reference_name: str
    description: str
    source_path: str
    providers: tuple[str, ...]
    targets: tuple[SkillTargetEntry, ...]

    @property
    def current_count(self) -> int:
        return _count_status(self.targets, "current")

    @property
    def stale_count(self) -> int:
        return _count_status(self.targets, "stale")

    @property
    def missing_count(self) -> int:
        return _count_status(self.targets, "missing")

    @property
    def retired_count(self) -> int:
        return _count_status(self.targets, "retired")


@dataclass(frozen=True)
class SkillsInventory:
    """Summary of generated skill sources and targets."""

    sources: tuple[SkillSourceEntry, ...]
    deploy_mode: SkillDeployMode
    provider_filter: str | None = None
    prettier_available: bool = True
    placement_errors: tuple[str, ...] = ()

    @property
    def use_chezmoi(self) -> bool:
        return self.deploy_mode == "chezmoi"

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def provider_count(self) -> int:
        return len(
            {provider for source in self.sources for provider in source.providers}
        )

    @property
    def target_count(self) -> int:
        return sum(len(source.targets) for source in self.sources)

    @property
    def current_count(self) -> int:
        return self._status_count("current")

    @property
    def stale_count(self) -> int:
        return self._status_count("stale")

    @property
    def missing_count(self) -> int:
        return self._status_count("missing")

    @property
    def retired_count(self) -> int:
        return self._status_count("retired")

    @property
    def drift_targets(self) -> tuple[SkillTargetEntry, ...]:
        return tuple(
            target
            for source in self.sources
            for target in source.targets
            if target.status != "current"
        )

    def _status_count(self, status: SkillTargetStatus) -> int:
        return sum(_count_status(source.targets, status) for source in self.sources)


@dataclass(frozen=True)
class AppliedSkillTargetEntry:
    """One chezmoi source skill target compared with its live home target."""

    source_path: Path
    home_path: Path
    provider: str
    skill_name: str
    status: AppliedSkillTargetStatus
    source_status: SkillTargetStatus


@dataclass(frozen=True)
class AppliedSkillsInventory:
    """Summary of live home skill targets derived from chezmoi sources."""

    targets: tuple[AppliedSkillTargetEntry, ...]
    provider_filter: str | None = None
    prettier_available: bool = True

    @property
    def target_count(self) -> int:
        return len(self.targets)

    @property
    def current_count(self) -> int:
        return self._status_count("current")

    @property
    def stale_count(self) -> int:
        return self._status_count("stale")

    @property
    def missing_count(self) -> int:
        return self._status_count("missing")

    @property
    def source_missing_count(self) -> int:
        return self._status_count("source_missing")

    @property
    def retired_count(self) -> int:
        return self._status_count("retired")

    @property
    def drift_targets(self) -> tuple[AppliedSkillTargetEntry, ...]:
        return tuple(target for target in self.targets if target.status != "current")

    def _status_count(self, status: AppliedSkillTargetStatus) -> int:
        return sum(1 for target in self.targets if target.status == status)


def build_skills_inventory(
    *,
    provider_filter: str | None = None,
    use_chezmoi: bool | None = None,
    use_prettier: bool | None = None,
) -> SkillsInventory:
    """Build a read-only inventory of generated skill targets."""
    if use_chezmoi is None:
        use_chezmoi = init_skills_handler.get_use_chezmoi()
    if use_prettier is None:
        use_prettier = init_skills_handler.prettier_available()

    xprompts, placement_errors = init_skills_handler.load_skill_sources()
    retired_entries: tuple[ManagedSkillFile, ...] = ()
    if use_chezmoi:
        deployment_targets = init_skills_handler.render_skill_deployment_targets(
            xprompts,
            provider_filter=provider_filter,
            use_prettier=use_prettier,
        )
        rendered_targets = [target.source_target() for target in deployment_targets]
        ownership_plan, _ownership_error = plan_skill_manifest_ownership(
            deployment_targets,
            chezmoi_home=init_skills_handler.CHEZMOI_HOME,
            home_root=Path.home(),
            provider_filter=provider_filter,
            registered_providers=init_skills_handler.registered_provider_names(),
        )
        if ownership_plan is not None:
            retired_entries = retired_skill_files_with_drift(
                ownership_plan.retired_entries,
                chezmoi_home=init_skills_handler.CHEZMOI_HOME,
                home_root=Path.home(),
            )
    else:
        rendered_targets = init_skills_handler.render_skill_targets(
            xprompts,
            provider_filter=provider_filter,
            use_chezmoi=use_chezmoi,
            use_prettier=use_prettier,
        )

    targets_by_skill: dict[str, list[SkillTargetEntry]] = {}
    for rendered in rendered_targets:
        targets_by_skill.setdefault(rendered.skill_name, []).append(
            SkillTargetEntry(
                path=rendered.path,
                provider=rendered.provider,
                skill_name=rendered.skill_name,
                status=_target_status(rendered),
            )
        )
    for entry in retired_entries:
        targets_by_skill.setdefault(entry.skill_name, []).append(
            SkillTargetEntry(
                path=entry.source_path(init_skills_handler.CHEZMOI_HOME),
                home_path=entry.home_path(Path.home()),
                provider=entry.provider,
                skill_name=entry.skill_name,
                status="retired",
            )
        )

    current_sources = [
        _source_entry(
            xprompt,
            provider_filter=provider_filter,
            targets=tuple(targets_by_skill.get(xprompt.skill_name or xprompt.name, ())),
        )
        for xprompt in xprompts
    ]
    current_names = {source.name for source in current_sources}
    retired_sources_by_name: dict[str, SkillSourceEntry] = {}
    for entry in retired_entries:
        if (
            entry.skill_name in current_names
            or entry.skill_name in retired_sources_by_name
        ):
            continue
        retired_sources_by_name[entry.skill_name] = _retired_source_entry(
            entry,
            targets_by_skill[entry.skill_name],
        )
    sources = tuple(
        sorted(
            [*current_sources, *retired_sources_by_name.values()],
            key=lambda source: source.name,
        )
    )
    return SkillsInventory(
        sources=sources,
        deploy_mode="chezmoi" if use_chezmoi else "home",
        provider_filter=provider_filter,
        prettier_available=use_prettier,
        placement_errors=placement_errors,
    )


def build_applied_skills_inventory(
    *,
    provider_filter: str | None = None,
    use_prettier: bool | None = None,
) -> AppliedSkillsInventory:
    """Build a read-only inventory comparing chezmoi skill sources to home."""
    if use_prettier is None:
        use_prettier = init_skills_handler.prettier_available()

    xprompts, _placement_errors = init_skills_handler.load_skill_sources()
    deployment_targets = init_skills_handler.render_skill_deployment_targets(
        xprompts,
        provider_filter=provider_filter,
        use_prettier=use_prettier,
    )
    ownership_plan, _ownership_error = plan_skill_manifest_ownership(
        deployment_targets,
        chezmoi_home=init_skills_handler.CHEZMOI_HOME,
        home_root=Path.home(),
        provider_filter=provider_filter,
        registered_providers=init_skills_handler.registered_provider_names(),
    )
    retired_entries: tuple[ManagedSkillFile, ...] = ()
    if ownership_plan is not None:
        retired_entries = retired_skill_files_with_drift(
            ownership_plan.retired_entries,
            chezmoi_home=init_skills_handler.CHEZMOI_HOME,
            home_root=Path.home(),
        )

    targets = [
        AppliedSkillTargetEntry(
            source_path=target.source_path,
            home_path=target.home_path,
            provider=target.provider,
            skill_name=target.skill_name,
            status=_applied_target_status(target.source_path, target.home_path),
            source_status=_target_status(target.source_target()),
        )
        for target in deployment_targets
    ]
    targets.extend(
        AppliedSkillTargetEntry(
            source_path=entry.source_path(init_skills_handler.CHEZMOI_HOME),
            home_path=entry.home_path(Path.home()),
            provider=entry.provider,
            skill_name=entry.skill_name,
            status="retired",
            source_status="retired",
        )
        for entry in retired_entries
    )
    return AppliedSkillsInventory(
        targets=tuple(targets),
        provider_filter=provider_filter,
        prettier_available=use_prettier,
    )


def _source_entry(
    xprompt: XPrompt,
    *,
    provider_filter: str | None,
    targets: tuple[SkillTargetEntry, ...],
) -> SkillSourceEntry:
    providers = _providers_for_source(xprompt, provider_filter=provider_filter)
    return SkillSourceEntry(
        name=xprompt.skill_name or xprompt.name,
        reference_name=xprompt.name,
        description=xprompt.description or "",
        source_path=xprompt.source_path or "-",
        providers=providers,
        targets=targets,
    )


def _retired_source_entry(
    entry: ManagedSkillFile,
    targets: list[SkillTargetEntry],
) -> SkillSourceEntry:
    return SkillSourceEntry(
        name=entry.skill_name,
        reference_name=f"skill/{entry.skill_name}",
        description="Retired generated skill",
        source_path=entry.source_relpath,
        providers=(entry.provider,),
        targets=tuple(targets),
    )


def _providers_for_source(
    xprompt: XPrompt, *, provider_filter: str | None
) -> tuple[str, ...]:
    skill_field = xprompt.skill
    if not skill_field:
        return ()

    providers = init_skills_handler.get_skill_target_providers(skill_field)
    if provider_filter:
        providers = [provider for provider in providers if provider == provider_filter]
    return tuple(dict.fromkeys(providers))


def _target_status(
    target: init_skills_handler.RenderedSkillTarget,
) -> SkillTargetStatus:
    planned = init_skills_handler.planned_skill_operation(target)
    if planned is None:
        return "current"

    operation, _ = planned
    if operation == "create":
        return "missing"
    return "stale"


def _applied_target_status(
    source_path: Path,
    home_path: Path,
) -> AppliedSkillTargetStatus:
    source_text = _read_text(source_path)
    if source_text is None:
        return "source_missing" if not source_path.exists() else "stale"

    home_text = _read_text(home_path)
    if home_text is None:
        return "missing" if not home_path.exists() else "stale"

    if home_text == source_text:
        return "current"
    return "stale"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _count_status(
    targets: tuple[SkillTargetEntry, ...], status: SkillTargetStatus
) -> int:
    return sum(1 for target in targets if target.status == status)
