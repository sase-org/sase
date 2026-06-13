from __future__ import annotations

import argparse
import hashlib

from sase.history.prompt_store import PromptEntry, save_prompt_history
from sase.main.parser import create_parser


def _seed(*entries: PromptEntry) -> None:
    save_prompt_history(list(entries))


def _prompt_id(text: str) -> str:
    """Local re-implementation of the stable ``ph_<sha256[:12]>`` content ID."""
    return f"ph_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


def _entry(
    text: str,
    last_used: str,
    *,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=last_used,
        last_used=last_used,
        cancelled=cancelled,
    )


def _prompt_subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = create_parser()
    top = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    prompt_parser = top.choices["prompt"]
    prompt_sub = next(
        action
        for action in prompt_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(prompt_sub.choices)


def _run_ns(
    prompt_id: str,
    *,
    prefix: str | None = None,
    edit: bool = False,
    daemon: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(id=prompt_id, prefix=prefix, edit=edit, daemon=daemon)


def _select_ns(
    *,
    all_: bool = False,
    cancelled: bool = False,
    query: str | None = None,
    prefix: str | None = None,
    edit: bool = False,
    daemon: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        all=all_,
        cancelled=cancelled,
        query=query,
        prefix=prefix,
        edit=edit,
        daemon=daemon,
    )


def _prune_ns(
    *,
    keep: int | None = None,
    before: str | None = None,
    cancelled: bool = False,
    dry_run: bool = False,
    yes: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        keep=keep,
        before=before,
        cancelled=cancelled,
        dry_run=dry_run,
        yes=yes,
    )


def _export_ns(
    prompt_id: str,
    *,
    out: str | None = None,
    sdd: bool = False,
    force: bool = False,
    metadata: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=prompt_id, out=out, sdd=sdd, force=force, metadata=metadata
    )


def _save_ns(
    prompt_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    project: str | None = None,
    global_: bool = False,
    force: bool = False,
    tag: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=prompt_id,
        name=name,
        description=description,
        project=project,
        global_=global_,
        force=force,
        tag=tag,
    )
