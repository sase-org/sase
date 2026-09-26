---
keyword: Receipts Prove Before They Skip
aliases: [receipts are proof not reuse, no reuse without measured opportunity]
summary:
  Verdict receipts are proof for host completion, never execution skip or reuse; reuse
  waits for measured content-equivalent repeat opportunity plus a hermeticity proof.
metadata:
  status: accepted
  decided: 2026-09-26
---

**Claim.** A verdict [[glossary:receipt]] proves that a named verification ran with a
trustworthy verdict on an exact fingerprint, so host-owned prepared completion can
consult it. It never skips, reuses, or redirects a `sase tool run`: every invocation
still executes its child. A later reuse program (E4b) reopens only after at least 2
h/week of content-equivalent covered repeats for one tool on one machine for two
consecutive weeks, plus a hermeticity proof — measured through `sase tool receipts`,
never asserted from a single audit.

**Why.** The E4 opportunity recount found 0 already-passing `check` repeats across 527
fingerprinted runs, and fail-fast lint-to-test time was 247 s median, so no cheap reuse
case exists yet; granting skip semantics now would trade unverified speed for silent
staleness. Rejected alternative: let a covering receipt skip the child immediately —
rejected because fingerprints exclude external bead/flag state by design (bounded by a
<=2 h TTL instead), so a skip could bless a tree whose lint inputs moved. Rejected
alternative: keep the beta flag indefinitely while reuse is studied — rejected because
the flag's Off branch would keep two completion semantics alive with no owner; landing
removes it and the report keeps the measurement.

**Cost.** Every verification pays full execution cost until E4b proves otherwise.
Receipt rows and the opportunity report are retained measurement, not savings.

**Reopens when.** The 14-day owner check shows sustained content-equivalent covered
repeats meeting the threshold above with a hermeticity proof, or fingerprint-change
refusals prove to be pure noise rather than real drift.
