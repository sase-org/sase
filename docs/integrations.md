# Integration APIs

SASE exposes a small set of Python helpers for external plugins and editor integrations. These APIs live under
`sase.integrations` when they are meant for integration-facing use, or under the subsystem package when they are already
part of an existing provider contract. The public symbols are tracked in `public_api_methods.txt` so unused-code tooling
does not treat external consumers as dead code.

## ChangeSpec XPrompt Tags

`sase.integrations.changespec_tags.list_changespec_xprompt_tags()` returns copyable VCS xprompt references for active
ChangeSpecs. It is intended for plugins and editors that need to show a picker of targets such as `#gh:my_change` or
`#git:local_branch`.

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

Each returned `ChangeSpecTagEntry` has:

| Field           | Description                                                    |
| --------------- | -------------------------------------------------------------- |
| `project`       | Parsed project basename                                        |
| `name`          | ChangeSpec `NAME`                                              |
| `status`        | Normalized non-terminal status                                 |
| `workflow_type` | Detected workspace workflow type, such as `git`, `gh`, or `hg` |
| `tag`           | Copyable xprompt target in `#{workflow_type}:{name}` form      |

If workspace workflow detection fails for an entry, that ChangeSpec is omitted and a human-readable message is appended
to `ChangeSpecTagListing.skipped`. This lets callers still show the rest of the list while surfacing degraded entries.

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

| Bucket            | Meaning                                                               |
| ----------------- | --------------------------------------------------------------------- |
| `Needs Attention` | User-facing blockers such as `PLANNING` and `QUESTION`.               |
| `Failed`          | Terminal failure statuses (`FAILED...`).                              |
| `Running`         | Active execution, including `PLAN APPROVED` and unrecognized actives. |
| `Waiting`         | `WAITING` agents with timer/dependency progress.                      |
| `Done`            | Terminal success/plan handoff states.                                 |

Source: `src/sase/integrations/agent_status_groups.py`, `src/sase/agent/status_buckets.py`

## Mobile Notification Bridge

`sase.integrations.mobile_notifications` is the stable host-side facade used by the Rust mobile gateway to expose the
local notification inbox to mobile clients. External callers should import from this facade only; the
`sase.integrations._mobile_notification_*` modules hold the split implementation and are internal.

```python
from sase.integrations.mobile_notifications import (
    build_mobile_attachment_manifests,
    execute_mobile_plan_action,
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
```

Snapshot reads project notifications into mobile-safe rows with display paths, host paths, action state, read/dismissed
state, mute/snooze state, and priority counts. Detail reads include dismissed and silent rows so clients can rebuild
local state after an event-stream resync. Action helpers resolve exact IDs or unique prefixes, write the corresponding
response JSON once, run best-effort host side effects, and raise `MobilePlanActionError` with deterministic `code` and
`target` fields for duplicate, stale, ambiguous, unsupported, missing, and invalid requests.

Source: `src/sase/integrations/mobile_notifications.py`

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
`update-start`, which starts the configured `chat_install.command` worker and reports status through structured polling.

External callers should import from these facade modules only. The `_mobile_agent_*` and `_mobile_helper_*` modules are
private split implementations kept small for testability and should not be imported by plugins or clients. The public
HTTP route contract is documented in [`docs/mobile_gateway.md`](mobile_gateway.md).

Source: `src/sase/integrations/mobile_agents.py`, `src/sase/integrations/mobile_helpers.py`

## Chat Update Worker

Chat integrations that need to update a SASE install can call
`sase.integrations.chat_install.start_chat_install_worker()`. The helper starts a detached worker process and returns a
chat-safe result object instead of blocking the chat request on the full update.

```python
from sase.integrations.chat_install import start_chat_install_worker

result = start_chat_install_worker()
print(result.status, result.message)
if result.log_path:
    print(result.log_path)
```

The worker sequence is:

1. Acquire `~/.sase/chat_install/install.lock`; if another worker owns it, return `already_running`.
2. Resolve the registered primary workspace for the `sase` project.
3. Stop axe.
4. Optionally sync the workspace through the selected VCS provider.
5. Run `chat_install.command` from that workspace with `chat_install.timeout_seconds`.
6. Restart axe, retrying up to `chat_install.restart_attempts`.

`start_chat_install_worker()` returns `ChatInstallLaunchResult` with one of these statuses: `config_missing_command`,
`workspace_resolution_failed`, `already_running`, `launched`, or `launch_failed`. Worker logs live under
`~/.sase/chat_install/logs/`. Configuration fields are documented in
[`docs/configuration.md`](configuration.md#chat_install). The API, config key, and state paths keep the `chat_install`
name for compatibility, but chat integrations should present this workflow to users as an update.

Source: `src/sase/integrations/chat_install.py`
