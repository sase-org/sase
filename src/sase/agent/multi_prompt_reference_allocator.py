"""Planned-name allocation for multi-prompt launches."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.agent.multi_prompt_reference_resume import (
    _RESUME_REF_RE,
    has_non_resume_xprompt_reference,
)


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
        self._resume_reserved: dict[str, set[str]] = {}
        self._wait_reserved: dict[str, set[str]] = {}
        self._template_reserved: set[str] | None = None
        self._template_latest: dict[str, str] = {}
        self._template_group_tokens: dict[str, str] = {}
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
            return explicit_name, None

        from sase.agent.names import (
            active_resume_reserved_names,
            active_wait_reserved_names,
            allocate_resume_name,
            allocate_wait_name,
            first_resume_agent_name,
            single_wait_agent_name,
        )

        resume_target = first_resume_agent_name(prompt)
        if resume_target is not None:
            if has_non_resume_xprompt_reference(prompt):
                return None, None
            from sase.agent.names import agent_name_allocation_lock

            with agent_name_allocation_lock():
                reserved = self._resume_reserved.get(resume_target)
                if reserved is None:
                    reserved = active_resume_reserved_names(resume_target)
                    self._resume_reserved[resume_target] = reserved
                while True:
                    name = allocate_resume_name(resume_target, reserved=reserved)
                    if self._reserve_planned_name(name, artifacts_dir):
                        break
            return name, name

        if "#" in prompt:
            return None, None

        wait_target = single_wait_agent_name(prompt)
        if wait_target is not None:
            from sase.agent.names import agent_name_allocation_lock

            with agent_name_allocation_lock():
                reserved = self._wait_reserved.get(wait_target)
                if reserved is None:
                    reserved = active_wait_reserved_names(wait_target)
                    self._wait_reserved[wait_target] = reserved
                while True:
                    name = allocate_wait_name(wait_target, reserved=reserved)
                    if self._reserve_planned_name(name, artifacts_dir):
                        break
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
            get_reserved_agent_names,
            iter_agent_name_template_tokens,
            render_agent_name_template,
        )

        group = _normalize_template_group(template_group, templates[0])
        with agent_name_allocation_lock():
            if self._template_reserved is None:
                self._template_reserved = get_reserved_agent_names()
            reserved = self._template_reserved

            existing_token = self._template_group_tokens.get(group.key)
            if existing_token is not None:
                candidates = [
                    render_agent_name_template(template, existing_token)
                    for template in templates
                ]
                if (
                    len(set(candidates)) == len(candidates)
                    and not any(candidate in reserved for candidate in candidates)
                    and self._reserve_planned_names(candidates, artifacts_dirs)
                ):
                    reserved.update(candidates)
                    for template, candidate in zip(templates, candidates, strict=True):
                        self._template_latest[template] = candidate
                    return candidates
                reserved.update(candidates)

            for token in iter_agent_name_template_tokens():
                candidates = [
                    render_agent_name_template(template, token)
                    for template in templates
                ]
                if len(set(candidates)) != len(candidates):
                    continue
                if any(candidate in reserved for candidate in candidates):
                    continue
                if not self._reserve_planned_names(candidates, artifacts_dirs):
                    reserved.update(candidates)
                    continue
                reserved.update(candidates)
                self._template_group_tokens[group.key] = token
                for template, candidate in zip(templates, candidates, strict=True):
                    self._template_latest[template] = candidate
                return candidates
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
                resolved = self._resolve_template_arg(_unquote_backtick_arg(colon))
                if resolved is not None:
                    replacements.append(
                        (match.start(), match.end(), f"#{kind}:{resolved}")
                    )
                continue

            if match.group("open_paren") is None:
                continue
            paren_start = match.end("open_paren") - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is None:
                continue
            inner = protected[paren_start + 1 : paren_end]
            positional_args, _ = parse_args(inner)
            if not positional_args:
                continue
            resolved = self._resolve_template_arg(positional_args[0])
            if resolved is not None:
                replacements.append(
                    (match.start(), paren_end + 1, f"#{kind}:{resolved}")
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

        if not is_agent_name_template(arg):
            return None
        return self._latest_template_name(arg)

    def mark_template_reservation_committed(
        self, name: str | None, artifacts_dir: str | Path | None
    ) -> None:
        """Mark a planned reservation as owned by a spawned child."""
        if name is None or artifacts_dir is None:
            return
        reservation = _PlannedNameReservation(
            name=name,
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
            get_reserved_agent_names,
            iter_agent_name_template_tokens,
            render_agent_name_template,
        )

        group = _normalize_template_group(template_group, template)
        with agent_name_allocation_lock():
            if self._template_reserved is None:
                self._template_reserved = get_reserved_agent_names()
            reserved = self._template_reserved

            existing_token = self._template_group_tokens.get(group.key)
            if existing_token is not None:
                candidate = render_agent_name_template(template, existing_token)
                if candidate not in reserved and self._reserve_planned_name(
                    candidate, artifacts_dir
                ):
                    reserved.add(candidate)
                    self._template_latest[template] = candidate
                    return candidate
                reserved.add(candidate)

            for token in iter_agent_name_template_tokens():
                candidate = render_agent_name_template(template, token)
                if candidate in reserved:
                    continue
                if not self._reserve_planned_name(candidate, artifacts_dir):
                    reserved.add(candidate)
                    continue
                reserved.add(candidate)
                self._template_group_tokens[group.key] = token
                self._template_latest[template] = candidate
                return candidate
        raise AssertionError("unreachable")

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
