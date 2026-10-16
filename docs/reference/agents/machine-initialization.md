---
title: Machine initialization
description: Look up remote machine enrollment through SASE initialization.
---

# Machine initialization

This page describes machine discovery, enrollment, activation, and review behavior.

## Remote machines

`sase machine init` is the canonical remote-machine initializer. `sase init machine` and
the bare `sase init` machine spec delegate to the same planner and apply service. The
operational target-preparation flow is covered in the
[Remote Dispatch Runbook](../../remote_dispatch.md).

`--check`, `--json`, and other previews inspect only local merged configuration: they
never run discovery or talk to a gateway. `--diff` only renders ordinary initializer
diffs; it is not a guarantee that no interactive apply-time discovery will occur when
you accept the machine initializer. A zero-machine or all-enrolled registry is not
drift, so `sase init --check` does not stay red just because enrollment is available. On
an interactive TTY before the local review has completed, bare `sase init` may offer one
explicit enrollment review.

The first successful explicit `sase machine init` review on a controller records a local
acknowledgment in `~/.sase/fleet/machine_init_review.json` (under `SASE_HOME` when set).
The record is machine-local and is not synced through project config or chezmoi. A
completed review includes candidates you consciously skip and successful empty reviews.
After that local acknowledgment exists, bare `sase init`, `sase init --all`, and
`sase init --project` do not perform automatic remote-machine discovery, prompt for
newly appearing machines, or print provider health failures. They report the machine
initializer as current from local state only. Existing installations need one catch-up
review because old state cannot prove the first review happened, and an unreadable
record also asks for a catch-up review with a local-state warning. Run
`sase machine init` directly, or the `sase init machine` compatibility alias, any time
you want to reconsider skipped candidates or force a fresh review. Use
`sase machine discover` for an explicit discovery scan and `sase machine status` to
check configured machines.

Explicit apply always rescans. Already-enrolled identities are listed and skipped;
selecting one existing machine does not hide another candidate. A changed installation
identity is never silently repinned — run `sase machine repair ALIAS` with a new
bootstrap instead. Enrollment bundles come from `-B/--bootstrap-file`, piped stdin, or a
hidden prompt; they are never accepted through an echoing `input()` prompt.

After the machine record and credential are written, init deploys a chezmoi-managed
overlay through the scoped `chezmoi apply --force` path, reloads merged configuration,
and runs a bounded authenticated hello. Only then does it print an enrolled success.
Quarantine and failed activation exit non-zero. If apply or hello fails after the target
may have consumed the one-time bootstrap, the command explains whether to retry the
apply or issue a new bundle and run `sase machine repair`.

## Related

- [Agents and workspaces](index.md) — the section hub.
