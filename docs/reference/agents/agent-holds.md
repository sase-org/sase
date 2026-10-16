---
title: Agent holds
description: Admission barriers for agents and undispatched procs.
---

# Agent holds

## `sase agent hold`

An agent hold is a durable, reverse-wait admission barrier: while it is active, matching
agents stay WAITING or QUEUED instead of starting, and matching procs that have not been
dispatched yet stay pending. `sase agent hold` is the standalone CLI for the hold store
that the [`%hold` directive](../macros/directive-launch.md#hold-directive) also
describes in prompt text. The CLI and directive are available without a feature flag.
Use the CLI when you need to inspect, release, or arm a hold outside a launch prompt.

```bash
sase agent hold create -n planner -t nightly   # block one name plus a tribe
sase agent hold create -f -s host -T 45m       # fence every later launch on this host
sase agent hold run -- just check-full         # quiesce while one command runs
sase agent hold list -j
sase agent hold show -k cli:myhost:12345
sase agent hold release                        # release this shell's or agent's own hold
```

`create` requires at least one selector: positional `SELECTOR` arguments (a name, or an
`@tribe`, expanded the same way as `%hold` names and tribes), repeatable `-n/--name` (an
agent, agent session, clan, workflow, or named proc name; role-suffixed names stay
exact), `-t/--tribe` (with or without `@`), and `-H/--hood`, plus `-f/--future` (agents
and undispatched procs submitted after the hold is armed) and `-p/--pending` (freeze the
WAITING/QUEUED agents in scope right now; it does not capture undispatched procs or
later launches). `-s/--scope` is `project` (the default, inferred from the current
checkout or agent) or `host`. `-T/--ttl` accepts bare seconds or a single-unit duration
such as `90s`, `45m`, or `2h` (compound values like `1h30m` are accepted only by
`%hold(ttl=...)`, not by `-T`); it defaults to `agent_hold_default_ttl` (`2h`) and may
not exceed `agent_hold_max_ttl` (`12h`); see
[agent hold limits](../config/agents-and-runners.md#agent-hold-limits). Arming,
releasing, and TTL expiry post notifications; the expiry notice includes the exact
boundary. sase's TUI Admin Center lists and releases active holds.

Each armer owns one hold. Inside an agent run the armer is that agent (`agent:<name>`),
and the hold is dropped once the agent's session settles. From a plain shell the armer
is `cli:<machine>:<pid>` anchored to the parent shell, so the hold lasts until it is
released, its TTL expires, or that shell exits. `sase agent hold release` releases the
calling agent's or shell's own hold unless `-k/--key` names another armer key, and exits
`1` when no such hold is active. `sase agent hold show -k KEY` prints one hold,
including its frozen pending artifact directories and launch-time capture summary (`-j`
prints the raw record), and exits `2` when the key has no active hold. Older records
without that evidence display “capture not recorded.”

`sase agent hold run [selectors] -- COMMAND` arms a hold anchored to the `run` process,
runs `COMMAND`, releases the hold on success, failure, or interruption, and exits with
the command's status. With no selector flags it defaults to `-f -p`, the selector-free
quiesce recipe. Holds whose armer has died or whose TTL has passed are pruned whenever
the store is read.
