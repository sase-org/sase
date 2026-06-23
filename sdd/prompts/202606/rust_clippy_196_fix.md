---
plan: sdd/tales/202606/rust_clippy_196_fix.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
cd /home/runner/work/sase/sase/sase-core && cargo fmt --all -- --check
cd /home/runner/work/sase/sase/sase-core && VIRTUAL_ENV=/home/runner/work/sase/sase/.venv PYO3_PYTHON=/home/runner/work/sase/sase/.venv/bin/python cargo clippy --workspace --all-targets -- -D warnings
   Compiling proc-macro2 v1.0.106
   Compiling quote v1.0.45
   Compiling unicode-ident v1.0.24
   Compiling libc v0.2.186
    Checking cfg-if v1.0.4
    Checking itoa v1.0.18
    Checking once_cell v1.21.4
    Checking memchr v2.8.0
   Compiling shlex v1.3.0
   Compiling find-msvc-tools v0.1.9
   Compiling cc v1.2.61
   Compiling version_check v0.9.5
    Checking smallvec v1.15.1
   Compiling syn v2.0.117
   Compiling autocfg v1.5.0
   Compiling serde_core v1.0.228
   Compiling zerocopy v0.8.48
   Compiling serde v1.0.228
   Compiling zmij v1.0.21
   Compiling num-traits v0.2.19
   Compiling ahash v0.8.12
   Compiling serde_json v1.0.149
   Compiling generic-array v0.14.7
    Checking pin-project-lite v0.2.17
    Checking hashbrown v0.17.0
    Checking equivalent v1.0.2
    Checking indexmap v2.14.0
    Checking typenum v1.20.0
    Checking aho-corasick v1.1.4
    Checking hashbrown v0.14.5
    Checking regex-syntax v0.8.10
    Checking bitflags v2.11.1
   Compiling pkg-config v0.3.33
    Checking bytes v1.11.1
   Compiling vcpkg v0.2.15
    Checking ryu v1.0.23
   Compiling getrandom v0.4.2
   Compiling serde_derive v1.0.228
    Checking tracing-subscriber v0.3.23
error: you should use the `ends_with` method
  --> crates/sase_core/src/editor/completion.rs:91:20
   |
91 |                 && document.text()[..byte].chars().next_back() == Some('+')
   |                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ help: like this: `document.text()[..byte].ends_with('+')`
   |
   = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.96.0/index.html#chars_last_cmp
   = note: `-D clippy::chars-last-cmp` implied by `-D warnings`
   = help: to override `-D warnings` add `#[allow(clippy::chars_last_cmp)]`

    Checking pem v3.0.6
    Checking rustls-pemfile v1.0.4
    Checking rand_chacha v0.3.1
    Checking hyper-rustls v0.24.2
    Checking url v2.5.8
    Checking simple_asn1 v0.6.4
    Checking hyper-util v0.1.20
   Compiling async-stream-impl v0.3.6
    Checking serde_path_to_error v0.1.20
   Compiling memoffset v0.9.1
    Checking encoding_rs v0.8.35
    Checking ipnet v2.12.0
    Checking matchit v0.7.3
error: could not compile `sase_core` (lib) due to 2 previous errors
warning: build failed, waiting for other jobs to finish...
error: Recipe `rust-clippy` failed on line 423 with exit code 101
Error: Process completed with exit code 101.
```