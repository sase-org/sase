Can you help me drastically improve the notification system which is triggered by the N keymap from the TUI. That key
map allows you to see a pop-up of notifications (this popup is what we will improve). This is a very large change, so
you should split this up into phases. I'll let you decide how many phases to use, but keep in mind that each phase will
be completed by a distinct cloud code instance, and our goal is to not exceed the context window.

### `sase notify` Subcommand

I would like to add a new subcommand called `sase notify` which accepts a JSON Schema argument somehow, you figured that
out. This argument should follow the following scheme:

```json
{
  "type": "object",
  "properties": {
    "notes": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "files": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "action": {
      "type": ["string", "null"]
    }
  }
}
```

### Notification Senders

I want to be able to support various different senders for this notification system, that's why I want this command in
place. Here's a list of the senders that I know about:

- The #crs workflow should notify the user when they're done addressing reviewer comments.
- The #fix_hook workflow should notify the user when they're done fixing a hook.
- Whenever a workflow or agent that a user explicitly started (via the `sase run` command or via one of the key maps in
  the `sase ace` TUI, for example) completes, it should notify the user of its completion. This includes both successful
  and unsuccessful completions.
- Wheneve a workflow completes a step that has `hitl: true` set.
- The `sase axe` command should start collecting errors that it experiences while running its periodic checks. Once
  every hour, it should publish all errors it's collected in that hour to the notification system using the
  `sase notify` command.
- The #sync workflow should notify the user when they complete a merge successfully or when they fail to complete a
  merge for some reason. The #sync workflow should NOT notify the user when it completes successfully without having to
  use a merge agent.

### Actions

The action field supported by the notification schema should accept the following enum values:

- HITL: Should trigger a `y/n/e` (yes / no / edit artifact, where the artifact depends on the agent's `output` field).
  Use cases:
  - When a workflow completes a step that has `hitl: true` set, it should use this to let the user decide whether to
    continue with the workflow execution, stop the workflow execution, or edit the artifact that was just produced by
    the step.
- JumpToChangeSpec: Should trigger a jump to the change spec associated with the notification, if there is one. If there
  isn't one, it should do nothing. This enum value needs to have a change spec name associated with it somehow. Use
  cases:
  - The #crs workflow should use this to let the user jump to the change spec that the #crs workflow ran on.
  - The #fix_hook workflow should use this to let the user jump to the change spec that the #fix_hook workflow ran on.
- Tmux: Should trigger a tmux window to open that uses the directory of a particular workspace. Use cases:
  - `gai axe` should use this to let the user open the workspace directory that experienced an error (so the user can
    attempt to fix the problem manually).
  - The #sync workflow should use this to let the user open the workspace directory that experienced a merge conflict
    that was successfully / unsuccessfully resolved (so the user can attempt to fix the problem manually if it was
    unsuccessful).

The action field controls what happens, if anything, when the user hits enter when a particular notification event is
selected.

### Obsolete Functionality

This functionality will obsolete the notifications that currently display on the agents tab. This includes the audible
notifications and the special highlighting of the agents tab that uses a counter. This functionality will also obsolete
the HITL functionality in the TUI on the agents tab (see below).
