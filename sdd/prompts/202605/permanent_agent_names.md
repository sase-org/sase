---
plan: sdd/epics/202605/permanent_agent_names.md
---
  We currently do some bad, hacky stuff with agent names. These are meant to be permanent IDs, but we change them
when the agent is dismissed or when de-duplicating. Can you help me change this so we NEVER change previous agent names
or allow the re-use of a previously used agent name without requiring that the previous agent be deleted?

- From now on, all agent names should be permanent. If the user really wants to re-use the agent name `<name>`, they can
put a "!" symbol in front of `<name>` when passing it to the `%name` directive. This will cause the previous agent to
be killed (if necessary--make sure to use a y/n user confirmation for this) and completely wiped from our system.
- Currently our auto-generated names use a sequence of lowercase letters. Let's start also allowing numbers, but not for
the first character in the sequence (e.g. `1` and `2b` are both invalid / won't be used as auto-generated names).
- This new naming policy is a drastic enough change that it warrants starting our auto-generated ID/name space fresh
(i.e. the next auto-generated name should be `a`). In order to make that possible, make sure that you add a `YYmmdd.`
prefix to ALL existing auto-generated agent names (including this one!) and update ALL references to each one of them.
- If the user attempts to use the `%name:<name>` directive and `<name>` was already used by an agent at some point, the
entire prompt should be canceled (add it to prompt history as a canceled agent prompt) and a toast should be displayed
to the user letting them know that the name was taken AND suggesting a name of the form `<name><N>` where `<N>` is the
  lowest positive integer such that `<name><N>` is a unique agent name.
- Make sure that these changes do not affect performance at all. For example, we should make sure that fetching the next
auto-generated name is fast and that checking name membership (i.e. if an agent exists with a given name) is fast.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

