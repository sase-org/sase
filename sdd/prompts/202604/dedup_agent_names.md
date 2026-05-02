---
plan: sdd/plans/202604/dedup_agent_names.md
---
 When we use the `R` keymap on the "Agents" tab of the `sase ace` TUI to revive an agent, the "YYmmdd." suffix is removed from that agent's name. I'm concerned that this might sometimes break the invariant that every agent
name is distinct. Can you help me make sure we de-dup (add a number or something) the revived agent's name if there is another agent on the Agents tab with the same name? While on this topic, can you also change it so, when an agent
is started that contains `%name:<name>` in its prompt but `<name>` is already take by an agent on the Agents tab, that we use the same process to de-dup the EXISTING agent's name? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 