"""Planned-name allocation for multi-prompt launches."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.agent.multi_prompt_reference_resume import (
    _RESUME_REF_RE,
    has_non_resume_xprompt_reference,
)
from sase.core.agent_tribe import parse_tribe_reference
from sase.core.machine_hood_facade import MachineHoodIdentity

if TYPE_CHECKING:
    from sase.agent.names import AgentNameNamespaceReservationIndex


@dataclass(frozen=True)
class _PlannedNameReservation:
    name: str
    artifacts_dir: str


@dataclass(frozen=True)
class _TemplateGroup:
    """Token-sharing group for related agent-name templates."""

    key: str


class PlannedNameAllocator:
    """Allocate parent-side names and resolve template references."""

    def __init__(self) -> None:
        self._machine_identity = MachineHoodIdentity.current()
        self._template_reserved: set[str] | None = None
        self._template_index: AgentNameNamespaceReservationIndex | None = None
        self._template_latest: dict[str, str] = {}
        self._template_group_tokens: dict[str, str] = {}
        self._template_group_names: dict[str, set[str]] = {}
        self._template_group_namespaces: dict[str, set[str]] = {}
        self._planned_reservations: list[_PlannedNameReservation] = []
        self._committed_reservations: set[_PlannedNameReservation] = set()

    def rewrite_template_references(self, prompt: str) -> str:
        """Resolve template wait/resume refs against this launch's plan."""
        prompt = self._rewrite_template_wait_directives(prompt)
        return self._rewrite_template_resume_references(prompt)

    def rewrite_indexed_references(self, prompt: str) -> str:
        """Compatibility alias for legacy indexed-template call sites."""
        return self.rewrite_template_references(prompt)

    def planned_name_for_prompt(
        self,
        prompt: str,
        *,
        artifacts_dir: str | Path | None = None,
        template_group: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Return ``(name, env_value)`` for a prompt, if safely knowable."""
        explicit_name = extract_static_name_directive(prompt)
        if explicit_name is not None:
            from sase.agent.names import is_agent_name_template

            if is_agent_name_template(explicit_name):
                name = self._allocate_template_name(
                    explicit_name,
                    artifacts_dir=artifacts_dir,
                    template_group=template_group,
                )
                return name, name
            from sase.core.machine_hood_facade import qualify_local_agent_name

            return (
                qualify_local_agent_name(explicit_name, self._machine_identity),
                None,
            )

        from sase.agent.names import (
            resume_agent_name_template,
            single_wait_agent_name,
            sole_resume_agent_name,
            wait_agent_name_template,
        )

        resume_target = sole_resume_agent_name(prompt)
        if resume_target is not None:
            if has_non_resume_xprompt_reference(prompt):
                return None, None
            template = resume_agent_name_template(resume_target)
            name = self._allocate_template_name(
                template,
                artifacts_dir=artifacts_dir,
                template_group=template,
            )
            return name, name

        if "#" in prompt and has_non_resume_xprompt_reference(prompt):
            return None, None

        wait_target = single_wait_agent_name(prompt)
        if wait_target is not None and parse_tribe_reference(wait_target) is None:
            template = wait_agent_name_template(wait_target)
            name = self._allocate_template_name(
                template,
                artifacts_dir=artifacts_dir,
                template_group=template,
            )
            return name, name

        name = self._allocate_template_name("@", artifacts_dir=artifacts_dir)
        return name, name

    def planned_names_for_template_group(
        self,
        templates: Sequence[str],
        *,
        artifacts_dirs: Sequence[str | Path | None] | None = None,
        template_group: str | None = None,
    ) -> list[str]:
        """Allocate one shared token across a known group of templates."""
        if not templates:
            return []
        if artifacts_dirs is None:
            artifacts_dirs = [None] * len(templates)
        if len(artifacts_dirs) != len(templates):
            raise ValueError("artifacts_dirs must match templates length")

        from sase.agent.names import (
            agent_name_allocation_lock,
            agent_name_template_namespace_template,
            get_reserved_agent_names,
            iter_agent_name_template_tokens,
        )

        group = _normalize_template_group(template_group, templates[0])
        with agent_name_allocation_lock():
            if self._template_reserved is None:
                self._template_reserved = get_reserved_agent_names()
                self._template_index = None
            index = self._template_reservation_index()
            self._ensure_unique_group_render_shapes(templates)
            templates_with_namespaces = [
                (template, agent_name_template_namespace_template(template))
                for template in templates
            ]

            existing_token = self._template_group_tokens.get(group.key)
            if existing_token is not None:
                candidates = _template_candidates(
                    templates_with_namespaces,
                    existing_token,
                    self._machine_identity,
                )
                candidate_names = [name for name, _ in candidates]
                namespaces = [namespace for _, namespace in candidates]
                if self._template_candidates_available(
                    candidates, group
                ) and self._reserve_planned_template_names(
                    candidate_names,
                    namespaces,
                    artifacts_dirs,
                    group,
                ):
                    self._record_template_group_names(group, candidates)
                    for template, candidate in zip(
                        templates,
                        candidate_names,
                        strict=True,
                    ):
                        self._template_latest[template] = candidate
                    return candidate_names
                index.update_names(candidate_names)

            for token in iter_agent_name_template_tokens():
                candidates = _template_candidates(
                    templates_with_namespaces,
                    token,
                    self._machine_identity,
                )
                candidate_names = [name for name, _ in candidates]
                namespaces = [namespace for _, namespace in candidates]
                if not self._template_candidates_available(candidates, group):
                    continue
                if not self._reserve_planned_template_names(
                    candidate_names,
                    namespaces,
                    artifacts_dirs,
                    group,
                ):
                    index.update_names(candidate_names)
                    continue
                self._record_template_group_names(group, candidates)
                self._template_group_tokens[group.key] = token
                for template, candidate in zip(
                    templates,
                    candidate_names,
                    strict=True,
                ):
                    self._template_latest[template] = candidate
                return candidate_names
        raise AssertionError("unreachable")

    def _rewrite_template_wait_directives(self, prompt: str) -> str:
        if "%" not in prompt:
            return prompt

        from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
        from sase.xprompt._disabled_regions import (
            protect_disabled_regions,
            unprotect_disabled_regions,
        )
        from sase.xprompt._fenced_blocks import (
            protect_fenced_blocks,
            unprotect_fenced_blocks,
        )
        from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

        fenced: list[str] = []
        protected = protect_fenced_blocks(prompt, fenced)
        disabled: list[str] = []
        protected = protect_disabled_regions(protected, disabled)

        replacements: list[tuple[int, int, str]] = []
        for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
            raw_name = match.group(1)
            if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
                continue

            colon_arg = match.group(3)
            if colon_arg is not None:
                resolved_args = self._resolve_template_arg_list(
                    _unquote_backtick_arg(colon_arg).split(",")
                )
                if resolved_args is None:
                    continue
                replacements.append(
                    (
                        match.start(),
                        match.end(),
                        f"%{raw_name}:{','.join(resolved_args)}",
                    )
                )
                continue

            if match.group(2) is None:
                continue

            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is None:
                continue
            inner = protected[paren_start + 1 : paren_end]
            positional_args, _ = parse_args(inner)
            resolved_args = self._resolve_template_arg_list(list(positional_args))
            if resolved_args is None:
                continue
            replacements.append(
                (
                    match.start(),
                    paren_end + 1,
                    f"%{raw_name}({','.join(resolved_args)})",
                )
            )

        rewritten = protected
        for start, end, value in reversed(replacements):
            rewritten = rewritten[:start] + value + rewritten[end:]
        rewritten = unprotect_disabled_regions(rewritten, disabled)
        return unprotect_fenced_blocks(rewritten, fenced)

    def _rewrite_template_resume_references(self, prompt: str) -> str:
        if "#fork" not in prompt and "#resume" not in prompt:
            return prompt

        from sase.xprompt._disabled_regions import (
            protect_disabled_regions,
            unprotect_disabled_regions,
        )
        from sase.xprompt._fenced_blocks import (
            protect_fenced_blocks,
            unprotect_fenced_blocks,
        )
        from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

        fenced: list[str] = []
        protected = protect_fenced_blocks(prompt, fenced)
        disabled: list[str] = []
        protected = protect_disabled_regions(protected, disabled)

        replacements: list[tuple[int, int, str]] = []
        for match in _RESUME_REF_RE.finditer(protected):
            kind = match.group("kind")
            colon = match.group("colon")
            if colon is not None:
                if colon.startswith("`") and colon.endswith("`"):
                    colon_args = [_unquote_backtick_arg(colon)]
                else:
                    colon_args, _ = parse_args(colon, preserve_empty_args=True)
                resolved_args = self._resolve_template_arg_list(colon_args)
                if resolved_args is not None:
                    replacements.append(
                        (
                            match.start(),
                            match.end(),
                            f"#{kind}:{','.join(resolved_args)}",
                        )
                    )
                continue

            if match.group("open_paren") is None:
                continue
            paren_start = match.end("open_paren") - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is None:
                continue
            inner = protected[paren_start + 1 : paren_end]
            positional_args, _ = parse_args(inner, preserve_empty_args=True)
            if not positional_args:
                continue
            resolved_args = self._resolve_template_arg_list(positional_args)
            if resolved_args is not None:
                replacements.append(
                    (
                        match.start(),
                        paren_end + 1,
                        f"#{kind}({','.join(resolved_args)})",
                    )
                )

        rewritten = protected
        for start, end, value in reversed(replacements):
            rewritten = rewritten[:start] + value + rewritten[end:]
        rewritten = unprotect_disabled_regions(rewritten, disabled)
        return unprotect_fenced_blocks(rewritten, fenced)

    def _resolve_template_arg_list(self, args: list[str]) -> list[str] | None:
        resolved: list[str] = []
        changed = False
        for arg in args:
            value = self._resolve_template_arg(arg)
            if value is None:
                resolved.append(arg)
            else:
                resolved.append(value)
                changed = True
        return resolved if changed else None

    def _resolve_template_arg(self, arg: str) -> str | None:
        from sase.agent.names import is_agent_name_template

        if parse_tribe_reference(arg) is not None:
            return None
        if not is_agent_name_template(arg):
            return None
        return self._latest_template_name(arg)

    def mark_template_reservation_committed(
        self, name: str | None, artifacts_dir: str | Path | None
    ) -> None:
        """Mark a planned reservation as owned by a spawned child."""
        if name is None or artifacts_dir is None:
            return
        from sase.core.machine_hood_facade import qualify_local_agent_name

        reservation = _PlannedNameReservation(
            name=qualify_local_agent_name(name, self._machine_identity),
            artifacts_dir=str(Path(artifacts_dir).expanduser().resolve(strict=False)),
        )
        if reservation in self._planned_reservations:
            self._committed_reservations.add(reservation)

    def mark_indexed_reservation_committed(
        self, name: str | None, artifacts_dir: str | Path | None
    ) -> None:
        """Compatibility alias for legacy indexed-template call sites."""
        self.mark_template_reservation_committed(name, artifacts_dir)

    def release_uncommitted_template_reservations(self) -> None:
        """Release planned reservations whose child never spawned."""
        from sase.agent.names import release_planned_registered_name

        for reservation in list(self._planned_reservations):
            if reservation in self._committed_reservations:
                continue
            release_planned_registered_name(reservation.name, reservation.artifacts_dir)
        self._planned_reservations = [
            reservation
            for reservation in self._planned_reservations
            if reservation in self._committed_reservations
        ]

    def release_uncommitted_indexed_reservations(self) -> None:
        """Compatibility alias for legacy indexed-template call sites."""
        self.release_uncommitted_template_reservations()

    def _reserve_planned_name(
        self,
        name: str,
        artifacts_dir: str | Path | None,
    ) -> bool:
        """Reserve a planned name for a not-yet-started child when possible."""
        if artifacts_dir is None:
            return True

        from sase.agent.names import NameCollisionError, reserve_registered_name
        from sase.core.machine_hood_facade import qualify_local_agent_name

        name = qualify_local_agent_name(name, self._machine_identity)
        artifacts_path = Path(artifacts_dir).expanduser().resolve(strict=False)
        try:
            reserve_registered_name(name, artifacts_path)
        except NameCollisionError:
            return False
        self._planned_reservations.append(
            _PlannedNameReservation(name=name, artifacts_dir=str(artifacts_path))
        )
        return True

    def _reserve_planned_names(
        self,
        names: Sequence[str],
        artifacts_dirs: Sequence[str | Path | None],
    ) -> bool:
        reservation_start = len(self._planned_reservations)
        for name, artifacts_dir in zip(names, artifacts_dirs, strict=True):
            if self._reserve_planned_name(name, artifacts_dir):
                continue
            self._release_planned_reservations_from(reservation_start)
            return False
        return True

    def _reserve_planned_template_names(
        self,
        names: Sequence[str],
        namespaces: Sequence[str],
        artifacts_dirs: Sequence[str | Path | None],
        group: _TemplateGroup,
    ) -> bool:
        materialized: list[tuple[str, str, Path]] = []
        for name, namespace, artifacts_dir in zip(
            names,
            namespaces,
            artifacts_dirs,
            strict=True,
        ):
            if artifacts_dir is None:
                continue
            materialized.append(
                (
                    name,
                    namespace,
                    Path(artifacts_dir).expanduser().resolve(strict=False),
                )
            )
        if not materialized:
            return True

        from sase.agent.names import (
            NameCollisionError,
            reserve_registered_template_names,
        )

        try:
            reserve_registered_template_names(
                materialized,
                allowed_existing_names=self._template_group_names.get(group.key, set()),
            )
        except NameCollisionError:
            return False

        for name, _, artifacts_path in materialized:
            self._planned_reservations.append(
                _PlannedNameReservation(
                    name=name,
                    artifacts_dir=str(artifacts_path),
                )
            )
        return True

    def _release_planned_reservations_from(self, start: int) -> None:
        from sase.agent.names import release_planned_registered_name

        for reservation in self._planned_reservations[start:]:
            release_planned_registered_name(reservation.name, reservation.artifacts_dir)
        del self._planned_reservations[start:]

    def _allocate_template_name(
        self,
        template: str,
        *,
        artifacts_dir: str | Path | None = None,
        template_group: str | None = None,
    ) -> str:
        from sase.agent.names import (
            agent_name_allocation_lock,
            agent_name_template_namespace_template,
            get_reserved_agent_names,
            iter_agent_name_template_tokens,
        )

        group = _normalize_template_group(template_group, template)
        with agent_name_allocation_lock():
            if self._template_reserved is None:
                self._template_reserved = get_reserved_agent_names()
                self._template_index = None
            index = self._template_reservation_index()
            namespace_template = agent_name_template_namespace_template(template)

            existing_token = self._template_group_tokens.get(group.key)
            if existing_token is not None:
                candidate, namespace = _durable_template_candidate(
                    template,
                    namespace_template,
                    existing_token,
                    self._machine_identity,
                )
                if self._template_candidate_available(
                    candidate, namespace, group
                ) and self._reserve_planned_template_names(
                    [candidate],
                    [namespace],
                    [artifacts_dir],
                    group,
                ):
                    self._record_template_group_names(group, [(candidate, namespace)])
                    self._template_latest[template] = candidate
                    return candidate
                index.add_name(candidate)

            for token in iter_agent_name_template_tokens():
                candidate, namespace = _durable_template_candidate(
                    template,
                    namespace_template,
                    token,
                    self._machine_identity,
                )
                if not self._template_candidate_available(candidate, namespace, group):
                    continue
                if not self._reserve_planned_template_names(
                    [candidate],
                    [namespace],
                    [artifacts_dir],
                    group,
                ):
                    index.add_name(candidate)
                    continue
                self._record_template_group_names(group, [(candidate, namespace)])
                self._template_group_tokens[group.key] = token
                self._template_latest[template] = candidate
                return candidate
        raise AssertionError("unreachable")

    def _template_reservation_index(self) -> AgentNameNamespaceReservationIndex:
        from sase.agent.names import AgentNameNamespaceReservationIndex

        if self._template_reserved is None:
            from sase.agent.names import get_reserved_agent_names

            self._template_reserved = get_reserved_agent_names()
            self._template_index = None
        if self._template_index is None:
            from sase.agent.names import get_reserved_clan_names

            self._template_index = (
                AgentNameNamespaceReservationIndex.from_registry_names(
                    self._template_reserved,
                    namespace_containers=get_reserved_clan_names(),
                )
            )
        return self._template_index

    def _template_candidate_available(
        self,
        name: str,
        namespace: str,
        group: _TemplateGroup,
    ) -> bool:
        return self._template_reservation_index().candidate_available(
            name,
            namespace,
            owned_namespaces=self._template_group_namespaces.get(group.key, set()),
        )

    def _template_candidates_available(
        self,
        candidates: Sequence[tuple[str, str]],
        group: _TemplateGroup,
    ) -> bool:
        names = [name for name, _ in candidates]
        if len(set(names)) != len(names):
            return False
        return all(
            self._template_candidate_available(name, namespace, group)
            for name, namespace in candidates
        )

    def _record_template_group_names(
        self,
        group: _TemplateGroup,
        candidates: Sequence[tuple[str, str]],
    ) -> None:
        names = self._template_group_names.setdefault(group.key, set())
        namespaces = self._template_group_namespaces.setdefault(group.key, set())
        index = self._template_reservation_index()
        for name, namespace in candidates:
            names.add(name)
            namespaces.add(namespace)
            if self._template_reserved is not None:
                self._template_reserved.add(name)
            index.add_name(name)

    def _ensure_unique_group_render_shapes(self, templates: Sequence[str]) -> None:
        from sase.agent.names import render_agent_name_template

        sample = [render_agent_name_template(template, "0") for template in templates]
        if len(set(sample)) != len(sample):
            raise ValueError(
                "template group rendered duplicate concrete names; "
                "split duplicate templates into separate groups"
            )

    def _latest_template_name(self, template: str) -> str:
        from sase.agent.names import (
            AgentNameTemplateNotFoundError,
            latest_agent_name_template,
        )

        planned = self._template_latest.get(template)
        if planned is not None:
            return planned

        latest = latest_agent_name_template(
            template,
            names=self._template_reserved_names(),
        )
        if latest is None:
            raise AgentNameTemplateNotFoundError(template)
        return latest

    def _template_reserved_names(self) -> set[str]:
        if self._template_reserved is None:
            from sase.agent.names import get_reserved_agent_names

            self._template_reserved = get_reserved_agent_names()
        return self._template_reserved


def _unquote_backtick_arg(arg: str) -> str:
    if arg.startswith("`") and arg.endswith("`"):
        return arg[1:-1]
    return arg


def _template_candidates(
    templates_with_namespaces: Sequence[tuple[str, str]],
    token: str,
    identity: MachineHoodIdentity,
) -> list[tuple[str, str]]:
    return [
        _durable_template_candidate(
            template,
            namespace_template,
            token,
            identity,
        )
        for template, namespace_template in templates_with_namespaces
    ]


def _durable_template_candidate(
    template: str,
    namespace_template: str,
    token: str,
    identity: MachineHoodIdentity,
) -> tuple[str, str]:
    from sase.agent.names import render_agent_name_template
    from sase.core.machine_hood_facade import qualify_local_agent_name

    return (
        qualify_local_agent_name(
            render_agent_name_template(template, token),
            identity,
        ),
        qualify_local_agent_name(
            render_agent_name_template(namespace_template, token),
            identity,
        ),
    )


def _normalize_template_group(
    group: _TemplateGroup | str | None,
    template: str,
) -> _TemplateGroup:
    if isinstance(group, _TemplateGroup):
        return group
    if group is not None:
        return _TemplateGroup(str(group))
    return _TemplateGroup(_template_group_key(template))


def _template_group_key(template: str) -> str:
    from sase.agent.names import agent_name_template_base

    base = agent_name_template_base(template)
    return base.rsplit(".", 1)[0] if "." in base else base
