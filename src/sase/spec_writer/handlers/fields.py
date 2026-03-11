"""Field update handlers for spec write operations."""

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse
from sase.status_state_machine.field_updates import (
    apply_cl_update,
    apply_description_update,
    apply_parent_update,
    apply_status_update,
)


def handle_set_status(request: SpecWriteRequest) -> SpecWriteResponse:
    changespec_name = request.params["changespec_name"]
    new_status = request.params["new_status"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated = apply_status_update(lines, changespec_name, new_status)
        write_changespec_atomic(
            request.project_file,
            updated,
            f"Set STATUS to {new_status} for {changespec_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_cl(request: SpecWriteRequest) -> SpecWriteResponse:
    changespec_name = request.params["changespec_name"]
    new_cl = request.params.get("new_cl")

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated = apply_cl_update(lines, changespec_name, new_cl, request.project_file)
        commit_msg = (
            f"Set CL to {new_cl} for {changespec_name}"
            if new_cl
            else f"Remove CL for {changespec_name}"
        )
        write_changespec_atomic(request.project_file, updated, commit_msg)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_parent(request: SpecWriteRequest) -> SpecWriteResponse:
    changespec_name = request.params["changespec_name"]
    new_parent = request.params.get("new_parent")

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated = apply_parent_update(lines, changespec_name, new_parent)
        commit_msg = (
            f"Set PARENT to {new_parent} for {changespec_name}"
            if new_parent
            else f"Remove PARENT for {changespec_name}"
        )
        write_changespec_atomic(request.project_file, updated, commit_msg)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_description(request: SpecWriteRequest) -> SpecWriteResponse:
    changespec_name = request.params["changespec_name"]
    new_description = request.params["new_description"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated = apply_description_update(lines, changespec_name, new_description)
        write_changespec_atomic(
            request.project_file,
            updated,
            f"Set DESCRIPTION for {changespec_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_name(request: SpecWriteRequest) -> SpecWriteResponse:
    old_name = request.params["old_name"]
    new_name = request.params["new_name"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.startswith("NAME:"):
                current_name = line.split(":", 1)[1].strip()
                if current_name == old_name:
                    updated_lines.append(f"NAME: {new_name}\n")
                    continue
            updated_lines.append(line)

        write_changespec_atomic(
            request.project_file,
            "".join(updated_lines),
            f"Rename ChangeSpec {old_name} to {new_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_update_parent_references(request: SpecWriteRequest) -> SpecWriteResponse:
    old_name = request.params["old_name"]
    new_name = request.params["new_name"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.startswith("PARENT: "):
                current_parent = line[8:].strip()
                if current_parent == old_name:
                    updated_lines.append(f"PARENT: {new_name}\n")
                    continue
            updated_lines.append(line)

        write_changespec_atomic(
            request.project_file,
            "".join(updated_lines),
            f"Update PARENT references from {old_name} to {new_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)
