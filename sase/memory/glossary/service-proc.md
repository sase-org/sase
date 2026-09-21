---
keyword: Service Proc
---

A service proc is a named proc the sase service owns, declared under `service.procs` by
core (builtin), a plugin's config layer, or the user, or created at runtime as a
transient oneshot. Its mode is `daemon` — kept running under its restart policy — or
`oneshot` — run once to completion. Control one with `sase service proc` or its
Services-tab node; `enabled: false` in a machine overlay keeps it off that machine.
Every launch is a distinct durable Proc carrying a `service` marker, hidden from the
Procs tab and proc gear by default.
