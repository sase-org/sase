---
keyword: Receipt
---

A receipt is the machine-local proof that one named [[glossary:tool-catalog]] entry
produced one settled [[glossary:tool-run]] with one trustworthy
[[glossary:triage-verdict]] on one exact fingerprint. The Rust core mints it only after
wrapper and triage settlement for an eligible run, and `sase tool receipt` reports it
(or exactly one typed refusal) without ever claiming a completion policy is met. An
explicitly opted-in prepared [[glossary:sase-monitor]] completion may consult a
covering, unexpired receipt before committing an all-KNOWN/FLAKY tree; the receipt never
skips or reuses the execution itself.
