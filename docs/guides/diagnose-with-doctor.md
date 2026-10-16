---
title: Diagnose problems with sase doctor
description: Run the read-only diagnostic checks and act on what they report.
---

# Diagnose problems with sase doctor

This guide runs SASE's diagnostics when something looks wrong. Start here before any
other Fix problems guide: the doctor names the failing area so you fix the cause, not a
symptom. Every mode below is read-only.

## Before you start

You need a checkout where `sase` runs. No provider, scheduler, or running agent is
required.

## 1. Run the default checks

Run the bounded default set and read the summary row:

```bash
sase doctor
```

`OK` means that area is fine. `WARN` and `SKIP` still exit `0`; only `ERROR` exits `1`.

## 2. Narrow to one area

Re-run with detail for the area you suspect. The check id can be one check or a whole
group; `-L` lists them all:

```bash
sase doctor -C llm.auth -v
sase doctor -L
```

The verbose report prints a summary, a next step, and bounded detail per check. When a
page and the doctor disagree, trust the doctor output.

## 3. Go deeper when needed

Include the slower read-only checks, and treat warnings as failures when you need a
strict answer:

```bash
sase doctor -D
sase doctor -s
```

The deep run adds checks that spawn real shells and contact live services. Emit JSON
with `-j` when you are pasting a support report.

## If it goes wrong

A clean doctor with a stuck run means the problem is admission or recovery, not
configuration: continue with [Unstick a queued agent](unstick-queued-agent.md) for a run
that never starts, or [Recover an interrupted agent](recover-interrupted-agent.md) for
one that died.

## Related

- [sase doctor](../reference/cli/doctor.md) — every check, flag, and exit code.
- [Configure the essentials](configure-essentials.md) — fix the values the doctor flags.
