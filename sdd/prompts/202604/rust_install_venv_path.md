---
plan: sdd/plans/202604/rust_install_venv_path.md
---
 Running `just rust-install` fails (see command output below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
❯ just rust-install
cd ../sase-core/crates/sase_core_py && .venv/bin/maturin develop --release
sh: 1: .venv/bin/maturin: not found
error: Recipe `rust-install` failed on line 186 with exit code 127
```