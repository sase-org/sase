# Integration APIs

SASE exposes a small set of Python helpers for external plugins, chat clients, mobile clients, and editor integrations.
These APIs live under `sase.integrations` when they are meant for integration-facing use, or under the subsystem package
when they are already part of an existing provider contract. Externally consumed public symbols use
`# symvision: <repo-uri>` pragmas so unused-code tooling validates them against the tracked files of the consuming
repository.

For editor setup and user-facing behavior, start with the [editor integration guide](editor.md). This page focuses on
the integration-facing Python and bridge contracts.

## ChangeSpec XPrompt Tags

`sase.integrations.changespec_tags.list_changespec_xprompt_tags()` returns copyable VCS xprompt references for active
ChangeSpecs. A ChangeSpec is SASE's stored record for a change list or pull request, and an xprompt tag is the
`#workflow:target` reference that launches an agent in that workspace. This helper is intended for plugins and editors
that need to show a picker of targets such as `#gh:my_change` or `#git:local_branch`.

```python
from sase.integrations.changespec_tags import list_changespec_xprompt_tags

listing = list_changespec_xprompt_tags(project="sase")
for entry in listing.entries:
    print(entry.project, entry.name, entry.status, entry.workflow_type, entry.tag)

if listing.skipped:
    print("Some ChangeSpecs could not be tagged:", listing.skipped)
```

The optional `project` argument is an exact project-name filter. Terminal ChangeSpecs are excluded after normalizing
workspace/status suffixes, so `Submitted`, `Archived`, and `Reverted` entries are not returned. Results are sorted
deterministically by project, ChangeSpec name, and normalized status.

The helper uses the same enabled-project default as normal ChangeSpec discovery. Disabled projects are omitted from the
broad list. The mobile helper bridge wraps explicit disabled-project tag requests with a partial-success warning telling
the caller to enable the project before launching new work.

Each entry in `listing.entries` has:

| Field           | Description                                                        |
| --------------- | ------------------------------------------------------------------ |
| `project`       | Parsed project basename                                            |
| `name`          | ChangeSpec `NAME`                                                  |
| `status`        | Normalized non-terminal status                                     |
| `workflow_type` | Detected registered workspace workflow type, such as `git` or `gh` |
| `tag`           | Copyable xprompt target in `#{workflow_type}:{name}` form          |

If workspace workflow detection fails for an entry, that ChangeSpec is omitted and a human-readable message is appended
to `listing.skipped`. This lets callers still show the rest of the list while surfacing degraded entries.

Source: `src/sase/integrations/changespec_tags.py`

## Agent Status Groups

`sase.integrations.agent_status_groups` exposes the same status-bucketing semantics used by the ACE Agents tab for
external chat or editor surfaces that want a compact running-agent summary.

```python
from sase.agent.running import list_all_agents
from sase.integrations.agent_status_groups import group_agent_statuses, status_bucket_header

for group in group_agent_statuses(list_all_agents()):
    print(status_bucket_header(group.bucket, len(group.agents)))
    for agent in group.agents:
        print(" ", agent.name, agent.status)
```

Buckets are emitted in ACE display order and empty buckets are omitted:

Each returned `AgentStatusGroup` contains the bucket label and the running-agent records assigned to that bucket.

| Bucket    | Meaning                                                               |
| --------- | --------------------------------------------------------------------- |
| `Stopped` | User-facing blockers such as `PLAN` and `QUESTION`.                   |
| `Failed`  | Terminal failure statuses (`FAILED...`).                              |
| `Running` | Active execution, including `PLAN APPROVED` and unrecognized actives. |
| `Waiting` | `WAITING` agents with timer/dependency progress.                      |
| `Done`    | Terminal success/plan handoff states.                                 |

Source: `src/sase/integrations/agent_status_groups.py`, `src/sase/agent/status_buckets.py`

## Agent List Entries

`sase.integrations.agent_list_entries.agent_list_entries()` returns a richer presentation-neutral projection for
surfaces that need more than the compact `sase agent list -j` schema. It is intended for plugins, chat clients, and
future UI surfaces that want one row model for running and recent agents without importing ACE internals.

```python
from sase.integrations.agent_list_entries import agent_list_entries

for entry in agent_list_entries(include_recent=True, project="sase"):
    print(entry.status_glyph, entry.name, entry.status_bucket, entry.provider_badge)
    if entry.wait.has_wait:
        print("waiting for", entry.wait.wait_for, entry.wait.remaining_seconds)
```

By default the helper returns active agents. `include_recent=True` includes recently completed `DONE` and `FAILED` rows
using the same cap as `sase agent list -a`; `project` filters by exact project key after projection. Each
`AgentListEntry` includes the basic CLI fields plus status bucket/glyph, provider and VCS display labels, retry and wait
metadata, family role, parent, tag, bead and ChangeSpec names, direct-child counts, output variables, artifact and
commit counts, and error text when available. The nested wait/retry/children objects are frozen dataclasses, not raw
JSON; bridge commands should convert them into their own wire shape.

Source: `src/sase/integrations/agent_list_entries.py`, `src/sase/integrations/provider_badges.py`

## Mobile Notification Bridge

`sase.integrations.mobile_notifications` is the stable host-side facade used by the Rust mobile gateway to expose the
local notification inbox to mobile clients. External callers should import from this facade only; the
`sase.integrations._mobile_notification_*` modules hold the split implementation and are internal.

```python
from sase.integrations.mobile_notifications import (
    build_mobile_attachment_manifests,
    execute_mobile_custom_gate_action,
    execute_mobile_hitl_action,
    execute_mobile_plan_action,
    execute_mobile_question_action,
    read_mobile_notification_snapshot,
    resolve_mobile_notification_detail,
)

snapshot = read_mobile_notification_snapshot(unread_only=True, limit=25)
if snapshot.rows:
    detail = resolve_mobile_notification_detail(snapshot.rows[0].id)
else:
    detail = None

if detail:
    attachments = build_mobile_attachment_manifests(detail)
    print(detail.action, detail.action_state, [item.display_name for item in attachments])

result = execute_mobile_plan_action("abcdef12", "approve", commit_plan=True, run_coder=False)
print(result.notification_id, result.response_file)

hitl_result = execute_mobile_hitl_action("12345678", "continue")
question_result = execute_mobile_question_action("87654321", "answer", custom_answer="Use the default.")
gate_result = execute_mobile_custom_gate_action(
    "c0ffee12",
    "proceed",
    extra_ids=("audit", "verify"),
    feedback="Approved from mobile",
)
print(hitl_result.message, question_result.message, gate_result.message)
```

Snapshot reads project notifications into mobile-safe rows with display paths, host paths, action state, read/dismissed
state, mute/snooze state, and priority counts. Detail reads include dismissed and silent rows so clients can rebuild
local state after an event-stream resync. Action helpers resolve exact IDs or unique prefixes, write the corresponding
response JSON once, and run best-effort host side effects. The facade supports plan approvals, workflow
human-in-the-loop actions, user-question answers, and custom gates. Custom-gate details project each choice's id, label,
icon, feedback mode, and ordered add-ons; submissions carry only the choice id, selected add-on ids, and feedback and
then run through the same hash-verified executor as ACE and Telegram. Action failures raise `MobilePlanActionError` with
deterministic `code` and `target` fields for duplicate, stale, ambiguous, unsupported, missing, and invalid requests.

Source: `src/sase/integrations/mobile_notifications.py`

## Notification Transport Registration

`sase.notifications.pending_actions` is the shared host store for actionable notifications (plan and launch approvals,
custom gates, human-in-the-loop, and user questions). Notification transports such as the sase-telegram plugin register
the message they sent for an action so cross-surface cleanup can later dismiss it. After delivering an actionable
notification, a transport calls `merge_transport_record` to attach its transport-owned data (e.g. `chat_id` and
`message_id`) to the existing action entry:

```python
from sase.notifications.pending_actions import merge_transport_record

merge_transport_record(
    notification.id,
    "telegram",
    {"chat_id": chat_id, "message_id": message_id},
)
```

The record is keyed by full notification id or unique prefix and replaces any prior record for the same transport. When
an action is resolved outside the transport — for example an auto-approved `%auto` plan, or a plan handled in the TUI,
CLI, or mobile bridge — core marks the entry `already_handled`. Transports read the store with their legacy records
merged in and remove the inline keyboard for any handled, stale, or missing-target action they still hold. The call is
best-effort from the transport's point of view: a failure must not block the legacy callback path.

Source: `src/sase/notifications/pending_actions.py`

## Mobile Agent And Helper Bridges

`sase.integrations.mobile_agents` and `sase.integrations.mobile_helpers` are stable facades for the workstation-hosted
mobile gateway bridge commands. The Rust gateway invokes them through fixed JSON-over-stdin operations rather than
exposing a generic shell, cwd, environment, or filesystem API to mobile clients.

Agent bridge operations cover `list-agents`, `resume-options`, `launch-text`, `launch-image`, `kill-agent`, and
`retry-agent`. Launch requests may name a known SASE project or use normal SASE prompt refs for VCS context; Android and
other mobile clients must not send host paths. Image launches store uploads under SASE-owned gateway state, then inject
the saved path into the agent prompt. Launch, kill, retry, upload, and per-device project context metadata lives under
`<sase_home>/mobile_gateway/`.

Helper bridge operations cover `changespec-tags`, `xprompt-catalog`, `beads-list`, `beads-show`, `update-start`, and
`update-status`. ChangeSpec, xprompt, and bead helpers are read-only. The only mutating helper operation is
`update-start`, which starts the built-in SASE update worker and reports status through structured polling. Bead helper
reads are project-scoped rather than active-checkout-scoped: for each requested project they read one canonical store,
`sdd/beads/` in in-tree mode, the primary workspace's `.sase/sdd/beads/` clone in local/legacy separate-repo mode, or
`beads/` in the primary `--plans` clone for split storage. Normal `sase bead` commands launched from a numbered
workspace can still write that workspace's own sidecar clone. `events/**` is canonical and `issues.jsonl` is a
compatibility projection; helper reads do not merge numbered sibling workspaces or legacy bead stores. The structured
xprompt catalog includes `definition_path` when the source can be resolved to a real file, so mobile and editor clients
can offer jump-to-definition without reverse-engineering display paths.

All-known helper reads are lifecycle-aware and enumerate enabled projects by default. Disabled projects are left out of
broad ChangeSpec tag, xprompt catalog, and bead lists. Explicit ChangeSpec tag and xprompt catalog requests for an
disabled project report warnings in the structured `result.warnings` / `result.skipped` fields where the bridge can
still return a partial result. Explicit bead requests resolve the requested project's canonical bead store directly; the
lifecycle filter only applies to the all-known bead list.

Bridge commands read a JSON object from stdin and write a compact JSON object to stdout:

```bash
printf '{"schema_version":1,"project":"sase","limit":20}\n' | sase mobile helper-bridge changespec-tags
printf '{"schema_version":1,"project":"sase","limit":20}\n' | sase mobile agent-bridge list-agents
```

External callers should import from these facade modules only. The `_mobile_agent_*` and `_mobile_helper_*` modules are
private split implementations kept small for testability and should not be imported by plugins or clients. The public
HTTP route contract is documented in [`docs/mobile_gateway.md`](mobile_gateway.md).

Source: `src/sase/integrations/mobile_agents.py`, `src/sase/integrations/mobile_helpers.py`

## Editor Helper Bridge

`sase.integrations.editor_helpers` exposes an editor-branded helper bridge over the same fixed JSON operations used by
the mobile helper facade. The current ChangeSpecI surface is:

```bash
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge xprompt-catalog
printf '{"schema_version":1,"project":"sase"}\n' | sase editor helper-bridge snippet-catalog
```

The `xprompt-catalog` operation returns the structured xprompt catalog, including insertion metadata, typed inputs,
source display fields, and `definition_path` for entries backed by a resolvable file. The `snippet-catalog` operation
returns the composed ACE snippet registry from xprompt snippets plus user snippets configured under `ace.snippets`.
Editor integrations should use this bridge or `sase lsp` instead of importing private catalog modules directly.

Source: `src/sase/integrations/editor_helpers.py`, `src/sase/integrations/xprompt_lsp.py`

## Chat Update Worker

Chat integrations that need to update a SASE install can call
`sase.integrations.chat_install.start_chat_install_worker()`. The helper starts a detached worker process and returns a
chat-safe result object instead of blocking the chat request on the full update. Poll with `read_chat_install_status()`
when `start_chat_install_worker()` returns a `job_id`.

```python
from sase.integrations.chat_install import read_chat_install_status, start_chat_install_worker

result = start_chat_install_worker()
print(result.status, result.message)
if result.log_path:
    print(result.log_path)

if result.job_id:
    status = read_chat_install_status(result.job_id)
    print(status.status, status.message)
```

The worker sequence is:

1. Acquire `~/.sase/chat_install/install.lock`; if another worker owns it, return `already_running`.
2. Run `sase update --json` with `chat_install.timeout_seconds`.
3. Parse the update JSON best-effort for a completion message such as `Already up to date.` or a package summary.
4. If axe is not running afterward, start it, retrying up to `chat_install.restart_attempts`.
5. Write the completion record for polling clients.

`start_chat_install_worker()` returns `ChatInstallLaunchResult` with one of these launch statuses: `already_running`,
`launched`, or `launch_failed`. `read_chat_install_status()` returns `running`, `succeeded`, `failed`, or `not_found`.
Worker logs live under `~/.sase/chat_install/logs/`. Configuration fields are documented in
[`docs/configuration.md`](configuration.md#chat_install). The API, config key, and state paths keep the `chat_install`
name for compatibility, but chat integrations should present this workflow to users as an update.

Source: `src/sase/integrations/chat_install.py`
