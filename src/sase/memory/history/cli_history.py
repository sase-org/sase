"""``sase memory history`` command: timelines, versions, diffs, and the feed.

With no selector the command shows the cross-file changes feed; with
one or more selectors it shows each subject's timeline. ``-A`` selects
one version (with its body), ``-d`` shows the change instead of the
body, and ``-f json`` emits the Rust wire unchanged for agents.

The command never writes a read-audit event: viewing history is not an
audited read (epic design ``plan:202609/memory_history.md`` D10).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any, Literal

from rich.console import Console

from sase.memory.cli_common import (
    MemoryCliProjectError,
    resolve_memory_cli_project,
)
from sase.memory.history.render_text import (
    render_diff,
    render_feed,
    render_timeline,
    render_version,
    short_display_for_subject_id,
)
from sase.memory.history.scopes import (
    HistoryScopeError,
    map_deployed_home_path,
)
from sase.memory.history.service import (
    HistoryAmbiguityError,
    HistoryNotFoundError,
    HistoryService,
)
from sase.memory.selector_models import (
    NoteSelector,
    StrandSelector,
    WebSelector,
    classify_selector,
)


def _project_root_for_args(args: argparse.Namespace) -> Path:
    """Resolve the project checkout root for the command."""
    project_ref = getattr(args, "project", None)
    if project_ref:
        try:
            resolved = resolve_memory_cli_project(project_ref)
        except MemoryCliProjectError as exc:
            raise HistoryScopeError(str(exc)) from exc
        if resolved is None:
            return Path.cwd()
        return resolved.project_root
    return Path.cwd()


def _translate_strand_selector(selector: StrandSelector, repo_root: Path) -> str:
    """Translate ``web:keyword`` to a repo-relative strand path."""
    from sase.memory.web.discovery import discover_memory_webs
    from sase.memory.web.lookup import (
        MemoryWebLookupError,
        resolve_memory_strand,
    )

    try:
        discovery = discover_memory_webs(repo_root)
    except Exception as exc:
        raise HistoryNotFoundError(
            f"history selector {selector.raw!r}: cannot discover memory webs: {exc}"
        ) from exc
    for web in discovery.webs:
        if web.slug != selector.web_slug:
            continue
        try:
            strand = resolve_memory_strand(web, selector.keyword)
        except MemoryWebLookupError:
            # Possibly a deleted strand: let core try its historical
            # path aliases before giving up.
            return f"{selector.web_slug}/{selector.keyword}.md"
        try:
            return strand.path.relative_to(repo_root).as_posix()
        except ValueError:
            return strand.relative_path
    raise HistoryNotFoundError(
        f"history selector {selector.raw!r}: unknown memory web {selector.web_slug!r}"
    )


def translate_history_selector(raw: str, repo_root: Path) -> str:
    """Translate a CLI selector to a core selector (shared with the pager)."""
    return _translate_selector(raw, repo_root)


def _translate_selector(raw: str, repo_root: Path) -> str:
    """Translate a CLI selector to a core selector.

    ``web:keyword`` selectors are resolved through strand keyword and
    alias lookup; everything else passes through to
    ``memory_history_resolve``, which owns historical paths and unique
    basenames.
    """
    classified = classify_selector(raw)
    if isinstance(classified, StrandSelector):
        return _translate_strand_selector(classified, repo_root)
    if isinstance(classified, WebSelector):
        return f"{classified.web_slug}.md"
    if isinstance(classified, NoteSelector):
        return classified.path
    raise HistoryScopeError(f"invalid history selector: {raw!r}")


def _parse_date_bound(value: str, *, end_of_day: bool) -> int:
    """Parse a ``YYYY-MM-DD`` (or full ISO) date to epoch seconds."""
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise HistoryScopeError(f"invalid date {value!r}: expected YYYY-MM-DD") from exc
    if len(value) == 10 and end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return int(parsed.timestamp())


def _at_to_version(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    at: str,
    *,
    include_hidden: bool,
) -> tuple[str, str | None]:
    """Translate ``-A/--at`` to a core version selector plus notice.

    Ordinals (``7``/``v7``), ``~N``, SHA prefixes, and ``now`` pass
    through. Dates select the latest version at or before that day.
    """
    if at == "now" or at.startswith("~") or at.startswith("v") or at.isdigit():
        return at, None
    # A bare date is YYYY-MM-DD; anything else goes to core as a SHA prefix.
    if len(at) == 10 and at[4] == "-" and at[7] == "-":
        bound = _parse_date_bound(at, end_of_day=True)
        timeline = service.timeline(scope, core_selector, include_hidden=True)
        versions = [
            v
            for v in timeline.get("versions", ())
            if int(v.get("ordinal", 0) or 0) > 0
            and int(v.get("committer_time", 0) or 0) <= bound
        ]
        if not versions:
            raise HistoryNotFoundError(
                f"no version of {core_selector!r} at or before {at}"
            )
        newest = max(versions, key=lambda v: int(v.get("ordinal", 0)))
        return f"v{newest.get('ordinal')}", (
            f"{core_selector} at {at} is v{newest.get('ordinal')}"
        )
    return at, None


def _historical_notice(
    raw: str, core_selector: str, resolved: dict[str, Any]
) -> str | None:
    """Notice when a selector used a historical name or alias."""
    subject = dict(resolved.get("subject", {}))
    paths = list(subject.get("paths", ()))
    if not paths:
        return None
    current = paths[-1]
    current_base = current.rsplit("/", 1)[-1]
    raw_base = raw.rsplit("/", 1)[-1].removeprefix("~/")
    core_base = core_selector.rsplit("/", 1)[-1]
    if raw_base != current_base and core_base != current_base:
        return f"{raw} is now {current}"
    return None


def _emit_json(console: Console, payload: Any) -> None:
    """Print a wire payload as deterministic JSON."""
    console.print_json(json.dumps(payload, sort_keys=True))


def _history_beta_enabled() -> bool:
    """Return whether the memory-history pager beta is on."""
    try:
        from sase.feature_flags import current_flags
        from sase.feature_flags.registry import FeatureFlag

        return bool(current_flags().enabled(FeatureFlag.memory_history))
    except Exception:
        return False


def handle_memory_history_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    service: HistoryService | None = None,
) -> None:
    """Render or serialize memory history for selectors or the feed."""
    active_console = console or Console()
    active_service = service or HistoryService()
    now_epoch = int(time.time())
    try:
        project_root = _project_root_for_args(args)
        scope_arg = getattr(args, "scope", None) or "all"
        scopes = active_service.scopes_for(scope_arg, project_root)
        requested = getattr(args, "format", None)
        beta_on = _history_beta_enabled()
        if requested is None:
            output_format = "pager" if (beta_on and sys.stdout.isatty()) else "text"
        else:
            output_format = requested
        if output_format == "pager" and not beta_on:
            print(
                "sase memory history -f pager needs the memory_history beta "
                "(disabled: ordinary pager behavior, text TTY default).",
                file=sys.stderr,
            )
            sys.exit(2)
        if output_format not in ("json", "text", "pager"):
            print(
                f"invalid --format {output_format!r}: expected json, pager, or text",
                file=sys.stderr,
            )
            sys.exit(2)
        if output_format == "pager" and getattr(args, "format", None) == "json":
            output_format = "json"
        if output_format == "pager":
            _handle_pager(
                active_service,
                scopes,
                project_root,
                list(getattr(args, "selectors", None) or ()),
                args,
            )
            return
        selectors = list(getattr(args, "selectors", None) or ())
        if not selectors:
            _handle_feed(
                active_console,
                active_service,
                scopes,
                args,
                now_epoch=now_epoch,
                output_format=output_format,
            )
            return
        _handle_selectors(
            active_console,
            active_service,
            scopes,
            project_root,
            selectors,
            args,
            now_epoch=now_epoch,
            output_format=output_format,
        )
    except (HistoryScopeError, HistoryNotFoundError, HistoryAmbiguityError) as exc:
        print(f"sase memory history: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_pager(
    service: HistoryService,
    scopes: list[Any],
    project_root: Path,
    selectors: list[str],
    args: argparse.Namespace,
) -> None:
    """Open selector history in the pager with per-selector scopes and pins."""
    from sase.memory.history.pager_provider import (
        build_history_document,
        selector_to_core_selector,
    )

    if not selectors:
        _handle_feed_pager(service, scopes, args)
        return
    requested_view = "diff" if bool(getattr(args, "diff", False)) else "read"
    sections: list[Any] = []
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
            core_selector = selector_to_core_selector(raw, repo_root)
        scope, _ = service.resolve_in_scopes(candidate_scopes, core_selector)
        at = getattr(args, "at", None)
        revision = at or "now"
        if at is not None:
            revision, _ = _at_to_version(
                service, scope, core_selector, at, include_hidden=True
            )
        document = build_history_document(
            scope=scope,
            subject=core_selector,
            initial_revision=revision,
            view=requested_view,
            service=service,
            title=deployed or raw,
        )
        sections.extend(document.sections)
    if not sections:
        raise HistoryNotFoundError("no history sections to page")
    from sase.pager.app import SasePager
    from sase.pager.document import PagerDocument, PagerOrigin

    pager_document = PagerDocument(
        sections=tuple(sections),
        title="memory history" if len(sections) > 1 else sections[0].title,
        origin=PagerOrigin.FILE,
    )
    SasePager(pager_document).run()


def _feed_query_bounds(
    args: argparse.Namespace,
) -> tuple[int | None, int | None, str | None]:
    """Return ``(since_epoch, limit, since_raw)`` for feed queries."""
    limit = getattr(args, "limit", None)
    since_raw = getattr(args, "since", None)
    since = _parse_date_bound(since_raw, end_of_day=False) if since_raw else None
    return since, limit, since_raw


def _handle_feed_pager(
    service: HistoryService,
    scopes: list[Any],
    args: argparse.Namespace,
) -> None:
    """Open the cross-file changes feed in the pager (one section per day)."""
    from sase.memory.history.feed_document import (
        build_feed_document,
        parse_feed_subject_target,
        resolve_feed_subject,
    )
    from sase.pager.app import SasePager

    since, limit, since_raw = _feed_query_bounds(args)
    show_all = bool(getattr(args, "all", False))
    window_label = f"since {since_raw}" if since_raw else None
    scopes_label = " + ".join(scope.scope_key for scope in scopes)
    scopes_by_key = {scope.scope_key: scope for scope in scopes}
    try:
        # Always include hidden changesets: regen-only groups collapse
        # client-side so their count line can expand in place, while
        # ``-a/--all`` pre-expands every group instead.
        feed = service.feed(scopes, since=since, limit=limit, include_hidden=True)
    except Exception as exc:
        raise HistoryScopeError(f"cannot build history feed: {exc}") from exc
    expanded: frozenset[str] | Literal["all"] = "all" if show_all else frozenset()
    result = build_feed_document(
        feed, scopes_label, window_label=window_label, expanded_regen=expanded
    )

    def _resolve_ref(ref: str, *, context: Any | None = None) -> Any | None:
        if parse_feed_subject_target(ref) is not None:
            from sase.pager.targets import LinkResolution

            target = resolve_feed_subject(service, scopes_by_key, ref)
            if target is None:
                return LinkResolution(
                    unresolved_message=f"{ref} could not be resolved.",
                    retryable=False,
                )
            return target
        from sase.pager.resolve import resolve_link

        return resolve_link(ref, context=context)

    def _refresh_document() -> Any | None:
        try:
            fresh = service.feed(scopes, since=since, limit=limit, include_hidden=True)
        except Exception:
            return None
        try:
            return build_feed_document(
                fresh,
                scopes_label,
                window_label=window_label,
                expanded_regen=expanded,
            ).document
        except Exception:
            return None

    SasePager(
        result.document,
        resolve_ref_fn=_resolve_ref,
        refresh_document_fn=_refresh_document,
    ).run()


def _handle_feed(
    console: Console,
    service: HistoryService,
    scopes: list[Any],
    args: argparse.Namespace,
    *,
    now_epoch: int,
    output_format: str,
) -> None:
    """Show the merged changes feed for the enabled scopes."""
    include_hidden = bool(getattr(args, "all", False))
    limit = getattr(args, "limit", None)
    since_raw = getattr(args, "since", None)
    since = _parse_date_bound(since_raw, end_of_day=False) if since_raw else None
    try:
        feed = service.feed(
            scopes, since=since, limit=limit, include_hidden=include_hidden
        )
    except Exception as exc:
        raise HistoryScopeError(f"cannot build history feed: {exc}") from exc
    if output_format == "json":
        _emit_json(console, feed)
        return
    label = " + ".join(scope.scope_key for scope in scopes)
    render_feed(console, feed, label, now_epoch=now_epoch)


def _handle_selectors(
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
    since = _parse_date_bound(since_raw, end_of_day=False) if since_raw else None
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
            core_selector = _translate_selector(raw, repo_root)
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
        _emit_json(console, payloads[0] if len(payloads) == 1 else payloads)


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
        version_arg, _ = _at_to_version(
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
    version_arg, date_notice = _at_to_version(
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


__all__ = ["handle_memory_history_command"]
