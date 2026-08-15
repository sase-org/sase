"""``sase gate act`` -- run one repeatable non-terminal gate action headlessly.

An action never answers the gate, so this is also the supported way to inspect
a pending gate's world before deciding: run the declared ``run_command`` action
instead of running the bundle's command by hand, which the trust model forbids.
``edit_file`` actions open the resolved edit target in ``$EDITOR`` and report
whether the edit was accepted or is still an unaccepted draft.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any, NoReturn

from rich.console import Console
from rich.text import Text

from sase.editor_resolver import resolve_editor
from sase.notification_gates.cli_support import (
    EXIT_ERROR,
    EXIT_OK,
    GateCliError,
    JsonArgumentReader,
    ResolvedGateCliBundle,
    emit_json,
    report_gate_error,
    resolve_gate_cli_bundle,
)
from sase.notification_gates.edits import (
    accept_edited_origin,
    origin_draft_state,
    resolve_edit_path,
)
from sase.notification_gates.model_operations import (
    GateOperation,
    gate_operation_from_envelope,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.operations import execute_gate_operation
from sase.ops.cli import emit_operation_result, load_request
from sase.ops.names import GATE_ACT


def handle_gate_act(args: argparse.Namespace) -> NoReturn:
    """Run one declared action and report what it did."""
    try:
        payload = _act(args)
    except GateCliError as exc:
        message = f"sase gate act: {exc}"
        emit_operation_result(
            operation=GATE_ACT,
            success=False,
            message=message,
            error=message,
            payload={},
            args=args,
        )
        print(message, file=sys.stderr)
        sys.exit(EXIT_ERROR)
    except GateError as exc:
        message = f"gate act failed [{exc.code}] {exc.target}: {exc}"
        emit_operation_result(
            operation=GATE_ACT,
            success=False,
            message=message,
            error=message,
            payload={"code": exc.code, "target": exc.target},
            args=args,
        )
        sys.exit(report_gate_error("act", exc))
    except OSError as exc:
        message = f"sase gate act: cannot run action: {exc}"
        emit_operation_result(
            operation=GATE_ACT,
            success=False,
            message=message,
            error=message,
            payload={},
            args=args,
        )
        print(message, file=sys.stderr)
        sys.exit(EXIT_ERROR)

    emit_operation_result(
        operation=GATE_ACT,
        success=True,
        message=str(
            payload.get("summary") or payload.get("message") or "Gate action ran"
        ),
        payload=payload,
        args=args,
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_human_result(payload)
    sys.exit(EXIT_OK)


def _act(args: argparse.Namespace) -> dict[str, Any]:
    bundle = resolve_gate_cli_bundle(str(args.kind), str(args.id))
    operation_id = str(args.operation)
    operation = gate_operation_from_envelope(bundle.envelope, operation_id)
    if operation.kind == "edit_file":
        return _run_edit_action(bundle, operation)
    return _run_command_action(bundle, operation, args)


def _run_edit_action(
    bundle: ResolvedGateCliBundle, operation: GateOperation
) -> dict[str, Any]:
    """Open the action's edit target, then accept the edit or keep the draft."""
    target = resolve_edit_path(bundle.root, bundle.envelope, operation.id)
    editor = resolve_editor()
    if editor.status == "missing":
        raise GateCliError(
            "no editor is available; set $VISUAL or $EDITOR, or install nvim or vim"
        )
    try:
        completed = subprocess.run(  # noqa: S603 - argv from the resolved editor
            editor.argv_with_path(str(target.path)), check=False
        )
    except OSError as exc:
        raise GateCliError(f"cannot start {editor.command_string}: {exc}") from exc
    if completed.returncode != 0:
        raise GateCliError(
            f"{editor.command_string} exited with status {completed.returncode}; "
            "the edit was not accepted"
        )

    try:
        accept_edited_origin(bundle.root, operation.id)
    except GateError as exc:
        # A rejected draft is deliberately kept in the edit target, so the
        # message points the reviewer back at their own work rather than
        # reporting a discarded edit.
        raise GateCliError(
            f"edit rejected [{exc.code}] {exc.target}: {exc}\n"
            f"sase gate act: your draft is kept in {target.path}; "
            "re-run this action to fix it"
        ) from exc
    return {
        "accepted": True,
        "draft_state": origin_draft_state(bundle.root, operation.id),
        "edit_path": str(target.path),
        "kind": bundle.kind,
        "message": "edit accepted",
        "operation_id": operation.id,
        "operation_kind": operation.kind,
        "request_id": bundle.request_id,
        "resource_path": target.resource_path,
        "status": "accepted",
    }


def _run_command_action(
    bundle: ResolvedGateCliBundle,
    operation: GateOperation,
    args: argparse.Namespace,
) -> dict[str, Any]:
    request = load_request(GATE_ACT, args)
    raw_input = getattr(args, "input", None)
    input_data = (
        request.payload.get("input_data")
        if "input_data" in request.payload
        else (
            None
            if raw_input is None
            else JsonArgumentReader().read(str(raw_input), target="--input")
        )
    )
    result = execute_gate_operation(
        bundle.root,
        operation.id,
        input_data=input_data,
        source="cli",
    )
    return {
        "body": result.display.body,
        "display_format": result.display_format,
        "kind": bundle.kind,
        "operation_id": result.operation_id,
        "operation_kind": operation.kind,
        "refresh": result.display.refresh,
        "request_id": bundle.request_id,
        "result": result.result,
        "review_revision": result.review_revision,
        "status": "ran",
        "summary": result.display.summary,
    }


def _print_human_result(payload: dict[str, Any]) -> None:
    console = Console()
    header = Text()
    header.append("▶", style="bold cyan")
    header.append(f" Gate {payload['kind']}/{payload['request_id']} · action ")
    header.append(str(payload["operation_id"]), style="bold")
    console.print(header, soft_wrap=True)

    if payload["operation_kind"] == "edit_file":
        line = Text("  ", style="dim")
        line.append("edit accepted", style="bold green")
        line.append(f" · {payload['edit_path']}", style="dim")
        console.print(line, soft_wrap=True)
        console.print(
            Text("  The gate is still pending and answerable.", style="dim"),
            soft_wrap=True,
        )
        return

    summary = payload["summary"]
    if summary:
        console.print(Text(f"  {summary}", style="bold"), soft_wrap=True)
    body = payload["body"]
    if body and payload["display_format"] != "none":
        _print_body(console, str(body), str(payload["display_format"]))
    console.print(
        Text("  The gate is still pending and answerable.", style="dim"),
        soft_wrap=True,
    )


def _print_body(console: Console, body: str, display_format: str) -> None:
    if display_format == "markdown":
        from rich.markdown import Markdown

        console.print(Markdown(body))
        return
    if display_format == "json":
        from rich.syntax import Syntax

        console.print(Syntax(body, "json", background_color="default"))
        return
    console.print(body, soft_wrap=True, highlight=False)


__all__ = ["handle_gate_act"]
