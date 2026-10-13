"""Shared fixtures for new-project source-stage tests.

Public helpers live in this already-private module so the split test modules
can share them without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.project_onboarding import CandidateInputs, OwnerResult
from sase.workspace_provider import ParsedRepoRef, WorkflowMetadata


def parsed(workflow_type: str, ref: str) -> ParsedRepoRef:
    owner, name = ref.split("/", 1)
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=ref,
        identity_key=f"github.com/{ref}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"~/projects/github/{owner}/{name}/",
    )


def provider(workflow_type: str, display_name: str) -> WorkflowMetadata:
    return WorkflowMetadata(
        workflow_type=workflow_type,
        ref_pattern=r"^$",
        display_name=display_name,
        pre_allocated_env_prefix="",
    )


def inputs(
    *,
    owners: list[OwnerResult] | None = None,
    account: str = "bbugyi200",
) -> CandidateInputs:
    return CandidateInputs(
        workflow_type="gh",
        display="GitHub",
        account=account,
        owners=owners if owners is not None else [OwnerResult(name="sase-org")],
        remote=[
            {
                "identity_key": "github.com/sase-org/new",
                "ref": "sase-org/new",
                "display": "sase-org/new",
                "owner": "sase-org",
                "name": "new",
                "description": "A suggested repository",
                "visibility": "public",
                "pushed_at": "2026-10-11T14:00:00Z",
                "is_fork": False,
            },
            {
                "identity_key": "github.com/sase-org/fork",
                "ref": "sase-org/fork",
                "display": "sase-org/fork",
                "owner": "sase-org",
                "name": "fork",
                "description": "",
                "visibility": "public",
                "is_fork": True,
            },
            {
                "identity_key": "github.com/sase-org/hidden",
                "ref": "sase-org/hidden",
                "display": "sase-org/hidden",
                "owner": "sase-org",
                "name": "hidden",
                "description": "Already registered",
                "visibility": "private",
                "is_fork": False,
            },
        ],
        local=[
            {
                "identity_key": "github.com/sase-org/clone",
                "ref": "sase-org/clone",
                "display": "sase-org/clone",
                "owner": "sase-org",
                "name": "clone",
                "path": "/tmp/clone",
                "numbered_copy": False,
            }
        ],
        projects=[
            {
                "key": "old-project",
                "name": "old-project",
                "aliases": [],
                "state": "disabled",
                "identity_keys": ["github.com/sase-org/old"],
            },
            {
                "key": "existing-project",
                "name": "existing-project",
                "aliases": [],
                "state": "enabled",
                "identity_keys": ["github.com/sase-org/hidden"],
            },
        ],
        inventory=[
            {
                "identity_key": "github.com/sase-org/sase--plans",
                "kind": "sidecar",
                "project_key": "sase",
            }
        ],
        journals=[
            {
                "identity_key": "github.com/sase-org/forge",
                "ref": "sase-org/forge",
                "display": "sase-org/forge",
                "status": "failed",
                "stopped_at": "2026-10-11T14:00:00Z",
            }
        ],
        owned_namespaces=["sase-org", "bbugyi200"],
        sidecar_roles=["plans", "beads", "agents", "attachments", "research", "sdd"],
    )


class ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("host")


def tool_missing_inputs() -> CandidateInputs:
    candidate = inputs(
        owners=[
            OwnerResult(
                name="sase-org",
                status="error",
                error_kind="tool_missing",
                message="gh not found",
            )
        ]
    )
    candidate.remote = []
    candidate.local = []
    return candidate
