---
type: core
parent: AGENTS.md
---

# Feature Flags

You MUST put a feature flag on user-reaching behavior before it is ready: a disabled
beta, an early landed path, or a deprecation whose old branch must stay reachable. You
SHOULD NOT flag anything users are meant to choose forever; that is a config field.

Create one only with `sase flag new <key>`, which also files its `flag` removal bead.
Flags are a `sase`-project concern, and a flag bead is a task bead of type `flag`. Read
`sase/memory/sase_flags.md` with `/sase_memory_read` before adding, deferring, or
removing any flag.
