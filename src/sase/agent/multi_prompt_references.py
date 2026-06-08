"""Name planning and reference rewrites for multi-prompt launches."""

import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_PLANNED_AGENT_NAME_ENV = "SASE_AGENT_PLANNED_NAME"
_GENERATED_AGENT_NAME_ENV = "SASE_AGENT_GENERATED_NAME"


@dataclass(frozen=True)
class _PlannedNameReservation:
    name: str
    artifacts_dir: str


@dataclass(frozen=True)
class _TemplateGroup:
    """Token-sharing group for related agent-name templates."""

    key: str


def wait_for_agent_naming(artifacts_dir: str, timeout: float = 30) -> str | None:
    """Poll ``agent_meta.json`` for a ``name`` field.

    Returns the agent name when found, or ``None`` on timeout.
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with open(meta_path) as f:
                data = json.load(f)
            if data.get("name"):
                return data["name"]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return None


def extract_static_name_directive(prompt: str) -> str | None:
    """Return an explicit top-level ``%name`` value that is safe to reuse."""
    if "%" not in prompt:
        return None

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue

        value = ""
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                inner = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(inner)
                value = positional_args[0] if positional_args else ""
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            value = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )

        if value.startswith("!"):
            value = value[1:]
        if not value or "#" in value:
            return None
        return value
    return None


def has_bare_wait_directive(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``%wait``."""
    if "%" not in prompt:
        return False

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        return True
    return False


def rewrite_bare_wait_directives(prompt: str, agent_name: str) -> str:
    """Rewrite top-level bare ``%wait``/``%w`` directives to *agent_name*."""
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
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
            end = paren_end + 1 if paren_end is not None else match.end()
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        else:
            end = match.end()
        replacements.append((match.start(), end, f"%{raw_name}:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


_BARE_RESUME_RE = re.compile(r"#fork(?![A-Za-z0-9_])")
_RESUME_REF_RE = re.compile(
    r"#(?P<kind>fork|resume)(?![A-Za-z0-9_])"
    r"(?:"
    r":(?P<colon>`[^`]*`|[^\s,)]+)"
    r"|"
    r"(?P<open_paren>\()"
    r")"
)
_XPROMPT_REF_RE = re.compile(r"#([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)")


def has_bare_resume_reference(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``#fork``."""
    if "#fork" not in prompt:
        return False

    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    return any(
        _is_bare_resume_match(protected, match)
        for match in _BARE_RESUME_RE.finditer(protected)
    )


def rewrite_bare_resume_references(prompt: str, agent_name: str) -> str:
    """Rewrite top-level bare ``#fork`` references to *agent_name*."""
    if "#fork" not in prompt:
        return prompt

    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in _BARE_RESUME_RE.finditer(protected):
        if _is_bare_resume_match(protected, match):
            replacements.append((match.start(), match.end(), f"#fork:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _is_bare_resume_match(text: str, match: re.Match[str]) -> bool:
    if match.end() >= len(text):
        return True
    return text[match.end()] not in ":("


def _has_non_resume_xprompt_reference(prompt: str) -> bool:
    if "#" not in prompt:
        return False

    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    return any(
        match.group(1) not in {"fork", "resume"}
        for match in _XPROMPT_REF_RE.finditer(protected)
    )


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
            if _has_non_resume_xprompt_reference(prompt):
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
