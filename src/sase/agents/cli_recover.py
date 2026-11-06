"""``sase agent recover`` — preview or resolve a held hijack."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.text import Text

from sase.agents._recover_render import (
    RECOVER_JSON_SCHEMA_VERSION,
    default_result_message,
    dry_run_envelope,
    error_envelope,
    menu_envelope,
    render_recovery_menu,
    result_envelope,
)
from sase.agent.hijack.preview import (
    HijackContinuationPrompt,
    HijackRecoveryRefusal,
    RecoveryPreview,
    build_hijack_continuation_prompt,
    hijack_recovery_preview,
    validate_hijack_continuation_prompt,
)
from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import (
    RESULT_ALREADY_RESOLVED,
    RESULT_ALREADY_RESOLVING,
    RESULT_ERROR,
    RESULT_LAUNCHED,
    RESULT_QUEUED,
    RESULT_REFUSED,
    RESULT_UNCERTAIN,
    RecoveryResult,
)
from sase.agent.hijack.recover_release import RELEASE_ACTIONS, recover_release_action
from sase.agent.hijack.recover_target import RecoveryRefusal, resolve_effective_target

PreviewFn = Callable[[object], RecoveryPreview]
RecoverFn = Callable[..., RecoveryResult]


def handle_agents_recover(
    args: argparse.Namespace,
    *,
    preview_fn: PreviewFn | None = None,
    recover_fn: RecoverFn | None = None,
    release_fn: RecoverFn | None = None,
    console: Console | None = None,
    err_console: Console | None = None,
) -> int:
    """Render the read-only menu or run one recovery resolution."""
    name = str(args.name)
    action = getattr(args, "action", None)
    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))
    model = getattr(args, "model", None)
    prompt_path = getattr(args, "prompt_file", None)
    discard_without_snapshot = bool(getattr(args, "discard_without_snapshot", False))
    out = console or Console()
    err = err_console or Console(stderr=True)
    load_preview = preview_fn or hijack_recovery_preview
    recover = recover_fn or recover_hijacked_agent
    release = release_fn or recover_release_action

    try:
        _validate_options(
            action,
            dry_run=dry_run,
            model=model,
            prompt_path=prompt_path,
            discard_without_snapshot=discard_without_snapshot,
        )
        prompt = _read_prompt_file(prompt_path) if prompt_path else None
    except (OSError, UnicodeError, ValueError) as exc:
        return _report_input_error(
            name,
            str(exc),
            as_json=as_json,
            err=err,
            action=action,
        )

    try:
        preview = load_preview(name)
    except HijackRecoveryRefusal as exc:
        return _report_error(
            name,
            str(exc),
            code=exc.code,
            exit_code=2,
            as_json=as_json,
            err=err,
            mode="menu" if action is None else "recovery",
            action=action,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports operational errors
        return _report_error(
            name,
            f"Could not preview hijack recovery: {exc}",
            code="preview_error",
            exit_code=1,
            as_json=as_json,
            err=err,
            mode="menu" if action is None else "recovery",
            action=action,
        )

    if action is None:
        if as_json:
            print(json.dumps(menu_envelope(name, preview), indent=2, sort_keys=True))
        else:
            out.print(render_recovery_menu(preview))
        return 0

    if str(action) in RELEASE_ACTIONS:
        menu_action = "edit" if prompt is not None else str(action)
        row = preview.action(menu_action)
        if row is None:
            return _report_error(
                name,
                f"Recovery action {action!r} is not available in this version",
                code="unsupported_action",
                exit_code=2,
                as_json=as_json,
                err=err,
                mode="recovery",
                action=action,
                preview=preview,
            )
        if not row.available:
            return _report_error(
                name,
                f"Recovery action {menu_action!r} is unavailable"
                + (f": {row.reason}" if row.reason else ""),
                code="action_unavailable",
                exit_code=2,
                as_json=as_json,
                err=err,
                mode="recovery",
                action=action,
                preview=preview,
            )
        try:
            result = release(
                name,
                action=str(action),
                prompt=prompt,
                discard_without_snapshot=discard_without_snapshot,
                expected_hijack_id=preview.hijack_id,
                expected_revision=preview.revision,
            )
        except Exception as exc:
            return _report_error(
                name,
                f"Recovery operation failed: {exc}",
                code="operation_error",
                exit_code=1,
                as_json=as_json,
                err=err,
                mode="recovery",
                action=action,
                preview=preview,
            )
        return _report_result(
            name, str(action), result, as_json=as_json, out=out, err=err
        )

    row = preview.action(str(action))
    if row is None:
        return _report_error(
            name,
            f"Recovery action {action!r} is not available in this version",
            code="unsupported_action",
            exit_code=2,
            as_json=as_json,
            err=err,
            mode="dry_run" if dry_run else "recovery",
            action=action,
            preview=preview,
        )

    if dry_run:
        try:
            target = resolve_effective_target(
                action=str(action),
                record=preview._record,
                preview_action={
                    "available": row.available,
                    "reason": row.reason,
                    "target": row.target,
                },
                model_override=model,
                prompt_text=prompt,
            )
            prepared = _preflight_prompt(
                name,
                str(action),
                prompt,
                target.concrete_target,
            )
        except (HijackRecoveryRefusal, RecoveryRefusal) as exc:
            return _report_error(
                name,
                str(exc),
                code=getattr(exc, "code", "recovery_refused"),
                exit_code=2,
                as_json=as_json,
                err=err,
                mode="dry_run",
                action=action,
                preview=preview,
            )
        except Exception as exc:  # noqa: BLE001 - dry-run is still a CLI boundary
            return _report_error(
                name,
                f"Could not prepare a recovery preview: {exc}",
                code="preview_error",
                exit_code=1,
                as_json=as_json,
                err=err,
                mode="dry_run",
                action=action,
                preview=preview,
            )
        envelope = dry_run_envelope(
            name,
            preview,
            action=str(action),
            target=target.concrete_target,
            model_changed=target.model_changed,
            prepared=prepared,
            prompt_supplied=prompt is not None,
        )
        if as_json:
            print(json.dumps(envelope, indent=2, sort_keys=True))
        else:
            out.print(render_recovery_menu(preview, selected_action=str(action)))
            out.print(
                Text(
                    f"Dry run · {action} → {target.concrete_target} · nothing launched",
                    style="bold #87D7FF",
                )
            )
        return 0

    try:
        result = recover(
            name,
            action=str(action),
            model=model,
            prompt=prompt,
            expected_hijack_id=preview.hijack_id,
            expected_revision=preview.revision,
        )
    except Exception as exc:  # noqa: BLE001 - executor exceptions are operation errors
        return _report_error(
            name,
            f"Recovery operation failed: {exc}",
            code="operation_error",
            exit_code=1,
            as_json=as_json,
            err=err,
            mode="recovery",
            action=action,
            preview=preview,
        )

    return _report_result(name, str(action), result, as_json=as_json, out=out, err=err)


def _report_result(
    name: str,
    action: str,
    result: RecoveryResult,
    *,
    as_json: bool,
    out: Console,
    err: Console,
) -> int:
    """Render one recovery result with the shared exit contract."""
    exit_code = recovery_exit_code(result)
    message = result.message or default_result_message(result)
    if as_json:
        print(
            json.dumps(
                result_envelope(
                    name, action, result, exit_code=exit_code, message=message
                ),
                indent=2,
                sort_keys=True,
            )
        )
    elif exit_code == 0:
        out.print(Text(message, style="bold #FF5FAF"))
    else:
        err.print(Text(message, style="bold yellow" if exit_code == 2 else "bold red"))
    return exit_code


def _validate_options(
    action: object,
    *,
    dry_run: bool,
    model: object,
    prompt_path: object,
    discard_without_snapshot: bool,
) -> None:
    if action is None and (
        dry_run
        or model is not None
        or prompt_path is not None
        or discard_without_snapshot
    ):
        raise ValueError(
            "--dry-run, --model, --prompt-file, and --discard-without-snapshot "
            "require --action"
        )
    if dry_run and action is None:
        raise ValueError("--dry-run requires --action so it can preview one action")
    if dry_run and action in {"dismiss", "restart"}:
        raise ValueError(
            "--dry-run is supported only with keep-work actions "
            "(--action continue or --action escalate)"
        )
    if prompt_path and action not in {"continue", "restart"}:
        raise ValueError(
            "--prompt-file is supported only with --action continue or --action restart"
        )
    if model is not None and action not in {"continue", "escalate"}:
        raise ValueError("--model requires --action continue or --action escalate")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("--model requires a non-empty concrete model target")
    if discard_without_snapshot and action not in {"dismiss", "restart"}:
        raise ValueError(
            "--discard-without-snapshot is supported only with --action restart "
            "or --action dismiss"
        )


def _read_prompt_file(path_value: object) -> str:
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("--prompt-file requires a path")
    try:
        prompt = Path(path_value).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read prompt file {path_value!r}: {exc}") from exc
    if not prompt.strip():
        raise ValueError(f"Prompt file {path_value!r} is empty")
    return prompt


def _preflight_prompt(
    name: str,
    action: str,
    prompt: str | None,
    target: str,
) -> HijackContinuationPrompt:
    if prompt is not None:
        return validate_hijack_continuation_prompt(
            name, prompt=prompt, model_target=target
        )
    if action == "continue" or action == "escalate":
        return build_hijack_continuation_prompt(name, model_target=target)
    raise HijackRecoveryRefusal("unsupported_action", f"Unsupported action {action!r}")


def recovery_exit_code(result: RecoveryResult) -> int:
    """Map the shared recovery result kinds to the public CLI exit contract."""
    if result.kind in {RESULT_LAUNCHED, RESULT_QUEUED, RESULT_ALREADY_RESOLVED}:
        return 0
    if result.kind in {RESULT_REFUSED, RESULT_ALREADY_RESOLVING}:
        return 2
    if result.kind in {RESULT_ERROR, RESULT_UNCERTAIN}:
        return 1
    return 1


def _report_input_error(
    name: str,
    message: str,
    *,
    as_json: bool,
    err: Console,
    action: object,
) -> int:
    return _report_error(
        name,
        message,
        code="invalid_input",
        exit_code=2,
        as_json=as_json,
        err=err,
        mode="recovery" if action is not None else "menu",
        action=action,
    )


def _report_error(
    name: str,
    message: str,
    *,
    code: str,
    exit_code: int,
    as_json: bool,
    err: Console,
    mode: str,
    action: object,
    preview: RecoveryPreview | None = None,
) -> int:
    if as_json:
        print(
            json.dumps(
                error_envelope(
                    name,
                    message,
                    code=code,
                    mode=mode,
                    action=action,
                    preview=preview,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(Text(message, style="bold yellow" if exit_code == 2 else "bold red"))
    return exit_code


__all__ = [
    "RECOVER_JSON_SCHEMA_VERSION",
    "handle_agents_recover",
    "recovery_exit_code",
    "render_recovery_menu",
]
