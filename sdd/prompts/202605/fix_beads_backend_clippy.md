---
plan: sdd/tales/202605/fix_beads_backend_clippy.md
---
 GitHub Actions is failing with the below error (the beads-backend job is failing). Can you help me diagnose the
root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
error: using `clone` on type `BeadEventOperationWire` which implements the `Copy` trait
   --> crates/sase_core/src/bead/events.rs:107:27
    |
107 |             .validate_for(self.operation.clone(), &self.issue_id)
    |                           ^^^^^^^^^^^^^^^^^^^^^^ help: try removing the `clone` call: `self.operation`
    |
    = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.95.0/index.html#clone_on_copy
    = note: `-D clippy::clone-on-copy` implied by `-D warnings`
    = help: to override `-D warnings` add `#[allow(clippy::clone_on_copy)]`

error: consider using `sort_by_key`
   --> crates/sase_core/src/bead/events.rs:288:5
    |
288 |     issues.sort_by(|a, b| event_issue_key(a).cmp(&event_issue_key(b)));
    |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |
    = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.95.0/index.html#unnecessary_sort_by
    = note: `-D clippy::unnecessary-sort-by` implied by `-D warnings`
    = help: to override `-D warnings` add `#[allow(clippy::unnecessary_sort_by)]`
help: try
    |
288 -     issues.sort_by(|a, b| event_issue_key(a).cmp(&event_issue_key(b)));
288 +     issues.sort_by_key(|a| event_issue_key(a));
    |

error: consider using `sort_by_key`
   --> crates/sase_core/src/bead/events.rs:387:5
    |
387 |     reduced.sort_by(|a, b| event_issue_key(a).cmp(&event_issue_key(b)));
    |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |
    = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.95.0/index.html#unnecessary_sort_by
help: try
    |
387 -     reduced.sort_by(|a, b| event_issue_key(a).cmp(&event_issue_key(b)));
387 +     reduced.sort_by_key(|a| event_issue_key(a));
    |

    Checking idna v1.1.0
    Checking serde_urlencoded v0.7.1
   Compiling pyo3-ffi v0.22.6
   Compiling pyo3-macros-backend v0.22.6
    Checking rand_core v0.6.4
    Checking futures v0.3.32
    Checking tracing-log v0.2.0
    Checking matchers v0.2.0
   Compiling async-trait v0.1.89
    Checking ppv-lite86 v0.2.21
    Checking thread_local v1.1.9
    Checking nu-ansi-term v0.50.3
error: could not compile `sase_core` (lib) due to 3 previous errors
warning: build failed, waiting for other jobs to finish...
error: Recipe `rust-clippy` failed on line 388 with exit code 101
Error: Process completed with exit code 101.
```