Can you help me add new "PLANNING", "CODING", and "QUESTION" statuses to the side-panel shown on the left in the
"Agents" tab of the `sase ace` TUI? This panel holds a list of agent / workflow entries with statuses like "FAILED",
"DONE", "RUNNING", etc. I want these new statuses to be treated exactly like the RUNNING status (make sure you cover ALL
scenarios).

- An agent's status should be switched to "PLANNING" when a plan notification has been sent to the the `sase ace` TUI's
  notification system (the notification panel is triggered with the `N` keymap) and will remain in that status until the
  user accepts / rejects / alters the plan.
- Accepting the plan should move the state to "CODING" and rejecting it should kill the agent process (using the
  PID---logic already exists to kill agents so re-use that) and change the status to "FAILED". Using `f` to provide
  feedback should keep it in "PLANNING" (the agent will send a new plan notification after receiving the feedback).
- An agent's status should be switched to "QUESTION" when one or more question notifications have been sent to the
  `sase ace` TUI and will remain in that status until the user answers the question(s). Answering the question(s) should
  move the state back to what it was before (always "RUNNING" I _think_).
- The "CODING" status should be a green-blue and the "PLANNING" status should be pink. You decide on a good color for
  the "QUESTION" status.
