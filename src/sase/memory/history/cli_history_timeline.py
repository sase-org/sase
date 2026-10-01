"""Per-selector timeline, version, and diff handling for history CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.memory.history._cli_history_common import (
    at_to_version,
    emit_json,
    parse_date_bound,
)
from sase.memory.history.cli_history_selectors import translate_history_selector
from sase.memory.history.render_text import (
    render_diff,
    render_timeline,
    render_version,
    short_display_for_subject_id,
)
from sase.memory.history.scopes import HistoryScopeError, map_deployed_home_path
from sase.memory.history.service import HistoryNotFoundError, HistoryService


def _historical_notice(
    raw: str, core_selector: str, resolved: dict[str, Any]
) -> str | None:
    """Notice when a selector used a historical name or alias."""
    subject = dict(resolved.get("subject", {}))
    if subject.get("kind") == "instructions":
        return None
    current = _current_subject_path(subject)
    if current is None:
        return None
    current_base = current.rsplit("/", 1)[-1]
    raw_base = raw.rsplit("/", 1)[-1].removeprefix("~/")
    core_base = core_selector.rsplit("/", 1)[-1]
    if raw_base != current_base and core_base != current_base:
        return f"{raw} is now {current}"
    return None


def _current_subject_path(subject: dict[str, Any]) -> str | None:
    """Return the subject's current path from its newest committed row."""
    versions = subject.get("versions", ())
    if isinstance(versions, (list, tuple)):
        for row in versions:
            if not isinstance(row, dict):
                continue
            if bool(row.get("diverged", False)):
                continue
            path = row.get("path")
            if path:
                return str(path)
    paths = list(subject.get("paths", ()))
    if not paths:
        return None
    return str(paths[-1])


def _latest_committed(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    include_hidden: bool,
) -> str:
    """Return the newest committed version selector (``-d`` default)."""
    timeline = service.timeline(scope, core_selector, include_hidden=True)
    ordinals = [int(v.get("ordinal", 0) or 0) for v in timeline.get("versions", ())]
    committed = [o for o in ordinals if o > 0]
    if not committed:
        raise HistoryNotFoundError(
            f"no committed versions of {core_selector!r} to diff"
        )
    newest = max(committed)
    if newest <= 1:
        return f"v{newest}"
    return f"v{newest}"


def _ordinal_of(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    target: str,
    include_hidden: bool,
) -> int | None:
    """Resolve a target version string to its committed ordinal."""
    if target.startswith("v") and target[1:].isdigit():
        return int(target[1:])
    if target.isdigit():
        return int(target)
    if target in ("now",) or target.startswith("~"):
        timeline = service.timeline(scope, core_selector, include_hidden=True)
        ordinals = [int(v.get("ordinal", 0) or 0) for v in timeline.get("versions", ())]
        committed = [o for o in ordinals if o > 0]
        return max(committed) if committed else None
    try:
        version = service.version(scope, core_selector, target, include_body=False)
        return int(dict(version.get("version", {})).get("ordinal", 0) or 0)
    except Exception:
        return None


def _compare_json(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    target: str,
    *,
    include_hidden: bool,
) -> Any:
    """Return the unchanged compare wire for a target version."""
    ordinal = _ordinal_of(service, scope, core_selector, target, include_hidden)
    if ordinal is None or ordinal <= 1:
        return service.version(scope, core_selector, target, include_body=True)
    return service.compare(
        scope, core_selector, f"v{ordinal - 1}", core_selector, target
    )


def _selector_json(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    at: str | None,
    *,
    show_diff: bool,
    include_hidden: bool,
) -> Any:
    """Return the unchanged Rust wire for one selector."""
    if at is not None:
        version_arg, _ = at_to_version(
            service, scope, core_selector, at, include_hidden=include_hidden
        )
        if show_diff:
            return _compare_json(
                service,
                scope,
                core_selector,
                version_arg,
                include_hidden=include_hidden,
            )
        return service.version(scope, core_selector, version_arg, include_body=True)
    if show_diff:
        target = _latest_committed(service, scope, core_selector, include_hidden)
        return _compare_json(
            service,
            scope,
            core_selector,
            target,
            include_hidden=include_hidden,
        )
    return service.timeline(scope, core_selector, include_hidden=include_hidden)


def _render_single(
    console: Console,
    service: HistoryService,
    scope: Any,
    core_selector: str,
    display: str,
    *,
    at: str,
    show_diff: bool,
    now_epoch: int,
    plain: bool,
    include_hidden: bool,
) -> None:
    """Render one version body or one version-to-version diff."""
    version_arg, date_notice = at_to_version(
        service, scope, core_selector, at, include_hidden=include_hidden
    )
    if date_notice:
        console.print(f"note: {date_notice}", style="dim")
    if not show_diff:
        try:
            response = service.version(
                scope, core_selector, version_arg, include_body=True
            )
        except Exception as exc:
            raise HistoryScopeError(
                f"cannot read version {at!r} of {core_selector!r}: {exc}"
            ) from exc
        render_version(console, response, display, scope.scope_key, now_epoch=now_epoch)
        return
    ordinal = _ordinal_of(service, scope, core_selector, version_arg, include_hidden)
    if ordinal is None or ordinal <= 1:
        try:
            response = service.version(
                scope, core_selector, version_arg, include_body=True
            )
        except Exception as exc:
            raise HistoryScopeError(
                f"cannot read version {at!r} of {core_selector!r}: {exc}"
            ) from exc
        console.print("(created: showing the full version)", style="dim")
        render_version(console, response, display, scope.scope_key, now_epoch=now_epoch)
        return
    base_arg = f"v{ordinal - 1}"
    try:
        comparison = service.compare(
            scope, core_selector, base_arg, core_selector, version_arg
        )
        base_body = str(
            service.version(scope, core_selector, base_arg, include_body=True).get(
                "body", ""
            )
            or ""
        )
        target_body = str(
            service.version(scope, core_selector, version_arg, include_body=True).get(
                "body", ""
            )
            or ""
        )
    except Exception as exc:
        raise HistoryScopeError(
            f"cannot diff {base_arg}..{version_arg} of {core_selector!r}: {exc}"
        ) from exc
    render_diff(
        console,
        comparison,
        plain=plain,
        base_body=base_body,
        target_body=target_body,
    )


def handle_selectors(
    console: Console,
    service: HistoryService,
    scopes: list[Any],
    project_root: Path,
    selectors: list[str],
    args: argparse.Namespace,
    *,
    now_epoch: int,
    output_format: str,
) -> None:
    """Show one timeline, version, or diff per selector."""
    include_hidden = bool(getattr(args, "all", False))
    at = getattr(args, "at", None)
    show_diff = bool(getattr(args, "diff", False))
    limit = getattr(args, "limit", None)
    since_raw = getattr(args, "since", None)
    since = parse_date_bound(since_raw, end_of_day=False) if since_raw else None
    payloads: list[Any] = []
    for raw in selectors:
        deployed = None
        candidate_scopes = scopes
        core_selector = raw
        if raw.startswith("~/") or raw == "~":
            mapped = map_deployed_home_path(Path(raw))
            if mapped is None:
                raise HistoryNotFoundError(
                    f"history selector {raw!r} has no chezmoi source subject"
                )
            home_scopes = [s for s in scopes if s.scope_key == "home"]
            if not home_scopes:
                raise HistoryScopeError(
                    f"history selector {raw!r} needs the home scope "
                    "(enable chezmoi or pass -S home)"
                )
            candidate_scopes = home_scopes
            core_selector = mapped
            deployed = raw
        else:
            project_scopes = [s for s in scopes if s.scope_kind == "project"]
            repo_root = (
                Path(project_scopes[0].repo_root) if project_scopes else project_root
            )
            core_selector = translate_history_selector(raw, repo_root)
        try:
            scope, resolved = service.resolve_in_scopes(candidate_scopes, core_selector)
        except Exception as exc:
            raise HistoryScopeError(
                f"cannot resolve history selector {raw!r}: {exc}"
            ) from exc
        notice = _historical_notice(raw, core_selector, resolved)
        if deployed is not None:
            notice = f"{deployed} maps to {core_selector}"
        subject = dict(resolved.get("subject", {}))
        subject_id = str(subject.get("id", core_selector))
        display = short_display_for_subject_id(subject_id)
        if output_format == "json":
            payloads.append(
                _selector_json(
                    service,
                    scope,
                    core_selector,
                    at,
                    show_diff=show_diff,
                    include_hidden=include_hidden,
                )
            )
            if notice and len(selectors) == 1:
                sys.stderr.write(f"note: {notice}\n")
            continue
        if notice:
            console.print(f"note: {notice}", style="dim")
        if at is not None or show_diff:
            _render_single(
                console,
                service,
                scope,
                core_selector,
                display,
                at=at
                or _latest_committed(service, scope, core_selector, include_hidden),
                show_diff=show_diff,
                now_epoch=now_epoch,
                plain=not console.is_terminal,
                include_hidden=include_hidden,
            )
            continue
        try:
            timeline = service.timeline(scope, core_selector, include_hidden=True)
        except Exception as exc:
            raise HistoryScopeError(
                f"cannot read history timeline for {raw!r}: {exc}"
            ) from exc
        versions = list(timeline.get("versions", ()))
        if since is not None:
            versions = [
                v
                for v in versions
                if int(v.get("ordinal", 0) or 0) == 0
                or int(v.get("committer_time", 0) or 0) >= since
            ]
            timeline = {**timeline, "versions": versions}
        if limit is not None:
            pseudo = [v for v in versions if int(v.get("ordinal", 0) or 0) == 0]
            committed = [v for v in versions if int(v.get("ordinal", 0) or 0) > 0]
            timeline = {**timeline, "versions": [*pseudo, *committed[:limit]]}
        render_timeline(
            console,
            timeline,
            display,
            scope.scope_key,
            now_epoch=now_epoch,
            include_hidden=include_hidden,
        )
    if output_format == "json":
        emit_json(console, payloads[0] if len(payloads) == 1 else payloads)


__all__ = ["handle_selectors"]
