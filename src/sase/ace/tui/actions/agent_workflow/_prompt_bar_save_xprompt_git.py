"""Git commit/push helpers for prompt-bar xprompt saves."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import Any

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
)
from sase.ops.names import GIT_POST_WRITE
from sase.post_write_operations import (
    GitCommitPushResult,
    process_error_text,
    run_git_commit_push_sync,
)
from sase.xprompt.write_targets import (
    PostWriteActionKind,
    PostWriteActionOffer,
    WrittenFileKind,
    XPromptWriteTarget,
    build_post_write_action_offers,
    classify_written_file,
    write_target_for_written_path,
)


class PromptBarSaveXpromptGitMixin:
    """Offer and run commit/push tasks after saving prompts or snippets."""

    async def _offer_post_write_actions(
        self,
        target: XPromptWriteTarget,
        *,
        kind: WrittenFileKind,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
        refresh_config_on_success: bool = False,
    ) -> None:
        """Build and push the post-write action chooser off the event loop."""
        import asyncio

        offers = await asyncio.to_thread(
            build_post_write_action_offers,
            target,
            kind=kind,
            is_new=is_new,
            xprompt_name=xprompt_name,
            noun=noun,
            commit_type=commit_type,
        )
        self._push_post_write_actions(
            offers,
            target=target,
            noun=noun,
            refresh_config_on_success=refresh_config_on_success,
        )

    def _offer_git_commit(
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        """Compatibility wrapper for older save callers."""
        target = write_target_for_written_path(file_path)
        kind = classify_written_file(target.write_path, read_path=target.read_path)
        offers = build_post_write_action_offers(
            target,
            kind=kind,
            is_new=is_new,
            xprompt_name=xprompt_name,
            noun=noun,
            commit_type=commit_type,
        )
        self._push_post_write_actions(
            offers,
            target=target,
            noun=noun,
            refresh_config_on_success=noun == "snippet",
        )

    def _push_post_write_actions(
        self,
        offers: tuple[PostWriteActionOffer, ...],
        *,
        target: XPromptWriteTarget,
        noun: str,
        refresh_config_on_success: bool = False,
    ) -> None:
        """Push the post-write chooser for already-built offers."""
        if not offers:
            return
        from ...modals.post_write_actions_modal import PostWriteActionsModal

        by_kind = {offer.kind: offer for offer in offers}

        def _on_actions_selected(
            selected: tuple[PostWriteActionKind, ...] | None,
        ) -> None:
            if not selected:
                return
            selected_offers = tuple(
                by_kind[kind] for kind in selected if kind in by_kind
            )
            submit_post_write_action_sequence(
                self,
                self,
                selected_offers,
                noun=noun,
                refresh_config_on_success=refresh_config_on_success,
            )

        self.push_screen(  # type: ignore[attr-defined]
            PostWriteActionsModal(offers, subject=_post_write_subject(target, offers)),
            _on_actions_selected,
        )

    def _submit_xprompt_commit_task(
        self,
        *,
        git_root: str,
        file_path: str,
        rel_path: str,
        message: str,
        noun: str = "xprompt",
        refresh_config_on_success: bool = False,
    ) -> None:
        """Run the git commit/push flow through the durable proc queue."""

        def _on_complete(completion: TrackedProcCompletion[dict[str, object]]) -> None:
            if completion.success:
                self.notify(completion.message)  # type: ignore[attr-defined]
                if refresh_config_on_success:
                    refresh_config = getattr(
                        self,
                        "_request_prompt_catalog_config_refresh",
                        None,
                    )
                    if callable(refresh_config):
                        refresh_config(reason="snippet_commit_apply")
            else:
                self.notify(  # type: ignore[attr-defined]
                    completion.message,
                    severity="error",
                )
            payload = completion.payload if isinstance(completion.payload, dict) else {}
            if payload.get("index_lock_removed"):
                self.notify(  # type: ignore[attr-defined]
                    git_index_lock_retry_message(git_root),
                    severity="warning",
                )

        submit = getattr(self, "_submit_durable_proc", None)
        if not callable(submit):
            self.notify(  # type: ignore[attr-defined]
                f"Could not commit {noun}: proc queue unavailable.",
                severity="error",
            )
            return

        submit(
            sase_argv("stitch", "post-write", "commit-push", rel_path, "--json"),
            operation=GIT_POST_WRITE,
            request=durable_request_payload(
                commit_message=message,
                file_path=file_path,
                git_root=git_root,
            ),
            request_fingerprint=durable_fingerprint(
                GIT_POST_WRITE,
                "commit-push",
                git_root,
                rel_path,
            ),
            concurrency_keys=(f"{noun}-commit:{git_root}:{rel_path}",),
            label=f"commit {noun} {rel_path}",
            display_name=f"commit {noun} {rel_path}",
            cl_name=rel_path,
            project_file=git_root,
            cwd=git_root,
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )


def submit_post_write_action_sequence(
    notifier: Any,
    submit_owner: Any,
    offers: tuple[PostWriteActionOffer, ...],
    *,
    noun: str = "xprompt",
    refresh_config_on_success: bool = False,
) -> None:
    """Submit selected post-write actions as ordered tracked tasks."""
    pending = list(offers)

    def _finish_sequence() -> None:
        if not refresh_config_on_success:
            return
        refresh_config = getattr(
            notifier,
            "_request_prompt_catalog_config_refresh",
            None,
        )
        if callable(refresh_config):
            refresh_config(reason="snippet_commit_apply")

    def _submit_next() -> None:
        if not pending:
            _finish_sequence()
            return
        offer = pending.pop(0)
        _submit_post_write_action(
            notifier,
            submit_owner,
            offer,
            noun=noun,
            on_success=_submit_next,
        )

    _submit_next()


def _submit_post_write_action(
    notifier: Any,
    submit_owner: Any,
    offer: PostWriteActionOffer,
    *,
    noun: str,
    on_success: Callable[[], None],
) -> None:
    submit = getattr(submit_owner, "_submit_durable_proc", None)
    if not callable(submit):
        notifier.notify(
            f"Could not run {offer.label}: proc queue unavailable.",
            severity="error",
        )
        return

    def _on_complete(completion: TrackedProcCompletion[dict[str, object]]) -> None:
        notifier.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        payload = completion.payload if isinstance(completion.payload, dict) else {}
        if payload.get("index_lock_removed") and offer.git_root:
            notifier.notify(
                git_index_lock_retry_message(offer.git_root),
                severity="warning",
            )
        if completion.success:
            on_success()

    metadata = _post_write_task_metadata(offer, noun=noun)
    kind = _post_write_cli_kind(offer)
    request = _post_write_request_payload(offer)
    cl_name = str(metadata["cl_name"] or "")
    dedup_key = str(metadata["dedup_key"] or "")
    display_name = str(metadata["display_name"] or "")
    project_file = str(metadata["project_file"] or "")
    submit(
        sase_argv("stitch", "post-write", kind, cl_name, "--json"),
        operation=GIT_POST_WRITE,
        request=request,
        request_fingerprint=durable_fingerprint(
            GIT_POST_WRITE,
            kind,
            dedup_key,
        ),
        concurrency_keys=(dedup_key,),
        label=display_name,
        display_name=display_name,
        cl_name=cl_name,
        project_file=project_file,
        cwd=metadata["cwd"] or None,
        on_complete=_on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )


def _post_write_task_metadata(
    offer: PostWriteActionOffer,
    *,
    noun: str,
) -> dict[str, str | None]:
    if offer.kind is PostWriteActionKind.COMMIT_PUSH:
        git_root = offer.git_root or ""
        return {
            "cwd": git_root,
            "proc_type": f"{noun}-commit",
            "cl_name": offer.rel_path,
            "project_file": git_root,
            "display_name": f"commit {noun} {offer.rel_path}",
            "dedup_key": f"{noun}-commit:{git_root}:{offer.rel_path}",
            "duplicate_message": (
                f"Another {noun} commit is already running for {offer.rel_path}."
            ),
        }
    if offer.kind is PostWriteActionKind.APPLY_CHEZMOI:
        target = offer.apply_target or offer.file_path
        return {
            "cwd": offer.cwd,
            "proc_type": f"{noun}-chezmoi-apply",
            "cl_name": offer.rel_path,
            "project_file": target,
            "display_name": f"apply chezmoi {target}",
            "dedup_key": f"{noun}-chezmoi-apply:{target}",
            "duplicate_message": f"Another chezmoi apply is already running for {target}.",
        }
    if offer.kind is PostWriteActionKind.MEMORY_INIT:
        return {
            "cwd": offer.cwd,
            "proc_type": "xprompt-memory-init",
            "cl_name": offer.rel_path,
            "project_file": offer.file_path,
            "display_name": "run sase memory init",
            "dedup_key": "xprompt-memory-init",
            "duplicate_message": "Another sase memory init is already running.",
        }
    return {
        "cwd": offer.cwd,
        "proc_type": "xprompt-skill-init",
        "cl_name": offer.rel_path,
        "project_file": offer.file_path,
        "display_name": "run sase skill init",
        "dedup_key": "xprompt-skill-init",
        "duplicate_message": "Another sase skill init is already running.",
    }


def _post_write_cli_kind(offer: PostWriteActionOffer) -> str:
    if offer.kind is PostWriteActionKind.COMMIT_PUSH:
        return "commit-push"
    if offer.kind is PostWriteActionKind.APPLY_CHEZMOI:
        return "chezmoi-apply"
    return "command"


def _post_write_request_payload(offer: PostWriteActionOffer) -> dict[str, object]:
    if offer.kind is PostWriteActionKind.COMMIT_PUSH:
        return dict(
            durable_request_payload(
                commit_message=offer.commit_message,
                file_path=offer.file_path,
                git_root=offer.git_root,
            )
        )
    if offer.kind is PostWriteActionKind.APPLY_CHEZMOI:
        return dict(durable_request_payload(apply_target=offer.apply_target))
    return dict(
        durable_request_payload(
            command=list(offer.command or ()),
            cwd=offer.cwd,
        )
    )


def _post_write_subject(
    target: XPromptWriteTarget,
    offers: tuple[PostWriteActionOffer, ...],
) -> str:
    rel_path = offers[0].rel_path if offers else str(target.write_path)
    if target.via_chezmoi and target.apply_target is not None:
        return f"{rel_path}\nchezmoi source for {target.apply_target}"
    return rel_path


def git_index_lock_retry_message(git_root: str) -> str:
    repo_name = os.path.basename(os.path.normpath(git_root)) or git_root
    return f"Removed a stale git index.lock in {repo_name} and retried the commit."


__all__ = [
    "GitCommitPushResult",
    "PromptBarSaveXpromptGitMixin",
    "git_index_lock_retry_message",
    "run_git_commit_push_sync",
    "submit_post_write_action_sequence",
]
