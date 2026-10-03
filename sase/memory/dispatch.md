---
type: reference
parent: AGENTS.md
description: Read before dispatching agents to a remote machine with `%dispatch`.
---

# Remote Dispatch

Remote dispatch launches agents on an enrolled machine from a controller prompt. Full
contract: `docs/remote_dispatch.md`. Directive grammar: [[macros.md]].

## Launch selector

- Add exactly one `%dispatch:<alias>` (or `%dispatch(alias)`) to a normal launch prompt.
  `%dispatch:local` is reserved; omit the directive for a local launch.
- V1 remote launch does not combine with `%wait`, `%queue`, or `%clan`, and `%hold`
  cannot combine with `%dispatch`.
- The controller strips only the dispatch selector; the remaining directives run on the
  target.
- `%tab` travels with the prompt: an agent, gate, or monitor turn on a named tab runs
  with `SASE_AGENT_TAB` set, and agent-initiated launches stamp `%tab:<name>` into each
  launched prompt or segment (skipped for an existing `%tab` or a session attach), so
  `sase run`, `sase bead work`, and gate option commands keep the planner's tab.
- A `%tab` + `%dispatch` launch runs a no-network version preflight against the target's
  last-known fleet contract version (federation cache-only host response): older than v7
  refuses with an upgrade hint, unknown warns and proceeds.

## Source preflight

- Without payload evidence (a Patch reference or an explicit revision), the controller
  requires a clean checkout, a current branch with an upstream, and a published `HEAD`.
  Local-only payloads (inputs, launch units, attachments, files, images) are rejected
  before submission.

## Same-key recovery

- Stop, retry, and fork wait for a settled receipt inside the acceptance window (at
  least 30 seconds). A lost response is recovered with the same operation key; an
  outcome still uncertain when the window ends must not be submitted again under a new
  key.
- A fresh remote agent can be exact-stopped once the owner index has its record, even
  while the fleet snapshot is still the previous cache. A remote stop does not dismiss
  the row; killed and other served turns advertise retry and fork until they leave the
  recent-terminal window.

## Enrollment and recovery

- Enroll with `sase machine init|add`; rotate a quarantined or mismatched enrollment
  with `sase machine repair TARGET` using a fresh one-time bundle.
- The Launch Target picker and the Machines tab perform no network probe: picker rows
  carry a local eligibility label (quarantined rows stay visible but disabled), and
  Machines runs a bounded hello only for the selected remote.

## Viewer parity notes

- Remote rows nest into the same session and clan nodes the owner reports; use _session_
  terminology. Workflow step rows are not served, so a remote session's `×N` can be
  lower than the owner's (shell-only `×N`).
- Remote load never joins the controller Agents `load:` gauge, which counts only the
  controller's own runners.
