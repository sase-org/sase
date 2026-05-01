 Something is very broken with the "Agents" tab of the `sase ace` TUI. I'm seeing "RUNNING" instead of "WAITING". Also, the startup time increased from ~3s to ~5s recently, which is unacceptable.
Can you help me diagnose the root cause of these issue and fix them? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- If something isn't implemented in Rust then implement it. Also, we shouldn't be keeping around the Python version for anything that has a Rust version, so delete the Python version.