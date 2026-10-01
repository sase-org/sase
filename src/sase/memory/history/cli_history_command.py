"""Command entry point, pager, and feed handling for history CLI."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Literal

from rich.console import Console

from sase.memory.cli_common import (
    MemoryCliProjectError,
    resolve_memory_cli_project,
)
from sase.memory.history._cli_history_common import (
    at_to_version,
    emit_json,
    parse_date_bound,
)
from sase.memory.history.cli_history_timeline import handle_selectors
from sase.memory.history.render_text import render_feed
from sase.memory.history.scopes import HistoryScopeError, map_deployed_home_path
from sase.memory.history.service import (
    HistoryAmbiguityError,
    HistoryNotFoundError,
    HistoryService,
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
        if requested is None:
            output_format = "pager" if sys.stdout.isatty() else "text"
        else:
            output_format = requested
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
        handle_selectors(
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
            revision, _ = at_to_version(
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
    since = parse_date_bound(since_raw, end_of_day=False) if since_raw else None
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
    since = parse_date_bound(since_raw, end_of_day=False) if since_raw else None
    try:
        feed = service.feed(
            scopes, since=since, limit=limit, include_hidden=include_hidden
        )
    except Exception as exc:
        raise HistoryScopeError(f"cannot build history feed: {exc}") from exc
    if output_format == "json":
        emit_json(console, feed)
        return
    label = " + ".join(scope.scope_key for scope in scopes)
    render_feed(console, feed, label, now_epoch=now_epoch)


__all__ = ["handle_memory_history_command"]
