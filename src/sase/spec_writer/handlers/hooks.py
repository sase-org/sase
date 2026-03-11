"""Hook handlers for spec write operations."""

from sase.ace.changespec import (
    HookEntry,
    HookStatusLine,
    changespec_lock,
    parse_project_file,
)
from sase.ace.hooks.mutations import apply_clear_hook_suffix, apply_hook_suffix_update
from sase.ace.hooks.persistence import write_hooks_unlocked
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def _dict_to_hook_status_line(d: dict) -> HookStatusLine:
    """Reconstruct a HookStatusLine from a dict."""
    return HookStatusLine(**d)


def _dict_to_hook_entry(d: dict) -> HookEntry:
    """Reconstruct a HookEntry from a dict."""
    d = dict(d)
    if d.get("status_lines") is not None:
        d["status_lines"] = [_dict_to_hook_status_line(sl) for sl in d["status_lines"]]
    return HookEntry(**d)


def _dicts_to_hooks(dicts: list[dict]) -> list[HookEntry]:
    """Reconstruct a list of HookEntry from a list of dicts."""
    return [_dict_to_hook_entry(d) for d in dicts]


def handle_set_hooks(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set the HOOKS field to the provided hooks list."""
    changespec_name = request.params["changespec_name"]
    hooks = _dicts_to_hooks(request.params["hooks"])

    with changespec_lock(request.project_file):
        write_hooks_unlocked(request.project_file, changespec_name, hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_merge_hooks(request: SpecWriteRequest) -> SpecWriteResponse:
    """Merge hook status updates with current disk state."""
    changespec_name = request.params["changespec_name"]
    hook_updates = {
        k: _dict_to_hook_entry(v) for k, v in request.params["hook_updates"].items()
    }

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_hooks: list[HookEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_hooks = list(cs.hooks) if cs.hooks else []
                break

        # Deduplicate by command name
        seen_commands: set[str] = set()
        deduped_hooks: list[HookEntry] = []
        for hook in current_hooks:
            if hook.command not in seen_commands:
                seen_commands.add(hook.command)
                deduped_hooks.append(hook)
        current_hooks = deduped_hooks

        # Merge: use updated version if available, otherwise keep disk version
        merged_hooks: list[HookEntry] = []
        for hook in current_hooks:
            if hook.command in hook_updates:
                merged_hooks.append(hook_updates[hook.command])
            else:
                merged_hooks.append(hook)

        write_hooks_unlocked(request.project_file, changespec_name, merged_hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_add_hook(request: SpecWriteRequest) -> SpecWriteResponse:
    """Add a single hook command to a ChangeSpec."""
    changespec_name = request.params["changespec_name"]
    hook_command = request.params["hook_command"]

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_hooks: list[HookEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_hooks = list(cs.hooks) if cs.hooks else []
                break

        existing_commands = {hook.command for hook in current_hooks}
        if hook_command in existing_commands:
            return SpecWriteResponse(request_id=request.request_id, success=True)

        current_hooks.append(HookEntry(command=hook_command))
        write_hooks_unlocked(request.project_file, changespec_name, current_hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_hook_suffix(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set a suffix on a status line of a specific hook."""
    changespec_name = request.params["changespec_name"]
    hook_command = request.params["hook_command"]
    suffix = request.params["suffix"]
    entry_id = request.params.get("entry_id")
    suffix_type = request.params.get("suffix_type")
    summary = request.params.get("summary")

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_hooks: list[HookEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_hooks = list(cs.hooks) if cs.hooks else []
                break
        if not current_hooks:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="No hooks found",
            )

        updated_hooks, was_updated = apply_hook_suffix_update(
            current_hooks, hook_command, suffix, entry_id, suffix_type, summary
        )
        if not was_updated:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Hook not updated",
            )
        write_hooks_unlocked(request.project_file, changespec_name, updated_hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_clear_hook_suffix(request: SpecWriteRequest) -> SpecWriteResponse:
    """Clear the suffix from the latest status line of a specific hook."""
    changespec_name = request.params["changespec_name"]
    hook_command = request.params["hook_command"]

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_hooks: list[HookEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_hooks = list(cs.hooks) if cs.hooks else []
                break
        if not current_hooks:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="No hooks found",
            )

        updated_hooks, was_cleared = apply_clear_hook_suffix(
            current_hooks, hook_command
        )
        if not was_cleared:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Hook suffix not cleared",
            )
        write_hooks_unlocked(request.project_file, changespec_name, updated_hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_update_hook_suffix_type(request: SpecWriteRequest) -> SpecWriteResponse:
    """Update the suffix_type of a specific hook status line."""
    changespec_name = request.params["changespec_name"]
    hook_command = request.params["hook_command"]
    commit_entry_num = request.params["commit_entry_num"]
    new_suffix_type = request.params["new_suffix_type"]

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_hooks: list[HookEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_hooks = list(cs.hooks) if cs.hooks else []
                break

        if not current_hooks:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="No hooks found",
            )

        updated_hooks: list[HookEntry] = []
        found = False

        for hook in current_hooks:
            if hook.command == hook_command and hook.status_lines:
                updated_status_lines: list[HookStatusLine] = []
                for sl in hook.status_lines:
                    if (
                        sl.commit_entry_num == commit_entry_num
                        and sl.suffix
                        and (sl.suffix_type == "error" or new_suffix_type == "plain")
                    ):
                        found = True
                        updated_status_lines.append(
                            HookStatusLine(
                                commit_entry_num=sl.commit_entry_num,
                                timestamp=sl.timestamp,
                                status=sl.status,
                                duration=sl.duration,
                                suffix=sl.suffix,
                                suffix_type=new_suffix_type,
                            )
                        )
                    else:
                        updated_status_lines.append(sl)
                updated_hooks.append(
                    HookEntry(command=hook.command, status_lines=updated_status_lines)
                )
            else:
                updated_hooks.append(hook)

        if not found:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Status line not found",
            )

        write_hooks_unlocked(request.project_file, changespec_name, updated_hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_rerun_delete_hooks(request: SpecWriteRequest) -> SpecWriteResponse:
    """Rerun/delete hooks by command string."""
    changespec_name = request.params["changespec_name"]
    commands_to_rerun = set(request.params["commands_to_rerun"])
    commands_to_delete = set(request.params["commands_to_delete"])
    entry_ids_to_clear = set(request.params["entry_ids_to_clear"])

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_hooks: list[HookEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_hooks = list(cs.hooks) if cs.hooks else []
                break

        updated_hooks: list[HookEntry] = []
        for hook in current_hooks:
            if hook.command in commands_to_delete:
                continue
            elif hook.command in commands_to_rerun:
                if hook.status_lines:
                    remaining_status_lines = [
                        sl
                        for sl in hook.status_lines
                        if sl.commit_entry_num not in entry_ids_to_clear
                    ]
                    updated_hooks.append(
                        HookEntry(
                            command=hook.command,
                            status_lines=(
                                remaining_status_lines
                                if remaining_status_lines
                                else None
                            ),
                        )
                    )
                else:
                    updated_hooks.append(hook)
            else:
                updated_hooks.append(hook)

        write_hooks_unlocked(request.project_file, changespec_name, updated_hooks)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_try_claim_hook_for_fix(request: SpecWriteRequest) -> SpecWriteResponse:
    """Atomically check eligibility and claim a hook for fix-hook workflow."""
    changespec_name = request.params["changespec_name"]
    hook_command = request.params["hook_command"]
    entry_id = request.params["entry_id"]
    claiming_suffix = request.params["claiming_suffix"]

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        cs = next((c for c in changespecs if c.name == changespec_name), None)
        if not cs or not cs.hooks:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="ChangeSpec or hooks not found",
            )

        current_hook = next((h for h in cs.hooks if h.command == hook_command), None)
        if not current_hook or not current_hook.status_lines:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Hook not found",
            )

        sl = current_hook.get_status_line_for_commit_entry(entry_id)
        if sl is None:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Status line not found",
            )
        if sl.status != "FAILED":
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Status is not FAILED",
            )
        if sl.suffix_type != "summarize_complete":
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Not ready for claiming",
            )
        if not sl.suffix:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="No suffix to claim",
            )

        existing_summary = sl.suffix

        updated_hooks: list[HookEntry] = []
        for hook in cs.hooks:
            if hook.command == hook_command and hook.status_lines:
                updated_status_lines: list[HookStatusLine] = []
                for status_line in hook.status_lines:
                    if status_line.commit_entry_num == entry_id:
                        updated_status_lines.append(
                            HookStatusLine(
                                commit_entry_num=status_line.commit_entry_num,
                                timestamp=status_line.timestamp,
                                status=status_line.status,
                                duration=status_line.duration,
                                suffix=claiming_suffix,
                                suffix_type="claiming_fix",
                                summary=existing_summary,
                            )
                        )
                    else:
                        updated_status_lines.append(status_line)
                updated_hooks.append(
                    HookEntry(
                        command=hook.command,
                        status_lines=updated_status_lines,
                    )
                )
            else:
                updated_hooks.append(hook)

        write_hooks_unlocked(request.project_file, changespec_name, updated_hooks)

    return SpecWriteResponse(
        request_id=request.request_id,
        success=True,
        result={"summary": existing_summary},
    )
