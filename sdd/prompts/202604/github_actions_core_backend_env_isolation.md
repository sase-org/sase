---
plan: sdd/plans/202604/github_actions_core_backend_env_isolation.md
---
  GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/test_core_facade.py::test_unported_query_facade_apis_rust_without_impl_fall_back_to_python - sase.core.backend.RustBackendUnavailableError: Rust backend requested for 'parse_query' but no Rust implementation is registered. Unset SASE_CORE_BACKEND, install or refresh the optional sase_core_rs extension, or mark the operation as an explicit Python fallback.
============ 1 failed, 6102 passed, 10 skipped in 146.42s (0:02:26) ============
error: Recipe `test-cov` failed on line 120 with exit code 1
Error: Process completed with exit code 1.
```