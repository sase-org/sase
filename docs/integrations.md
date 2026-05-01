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
2. Resolve the primary SASE workspace.
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
