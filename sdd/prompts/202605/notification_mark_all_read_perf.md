---
plan: sdd/tales/202605/notification_mark_all_read_perf.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```

---------- Phase 7E regression floor (sase-1e.5) ----------
.venv/bin/python tests/perf/phase7_check_regression.py 

Phase 7E floor check FAILED.

==== Phase 7E floor: bench_core_parse ====

# golden_myproj (981 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct           0.092        0.096      0.107      0.120
  rust_direct             0.030        0.031      0.032      0.035
  rust_facade             0.044        0.045      0.047      0.051

# synthetic_200_specs (125298 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct           9.945       10.040     10.516     16.614
  rust_direct             3.158        3.199      3.222      3.324
  rust_facade             4.536        4.585      4.892     11.537

==== Phase 7E floor: bench_core_query ====

# parse_only
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.008        0.008      0.011      0.011
  python_facade_parse               0.009        0.010      0.011      0.011
  rust_direct_parse                 0.003        0.004      0.004      0.004
  rust_facade_parse                 0.009        0.009      0.010      0.010

# synthetic_100_specs (100 specs)
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  is_valid_transition                                   2.474        2.614      2.794      3.165
  remove_workspace_suffix                               0.752        0.806      0.882      1.031
  read_status_from_lines                                2.664        3.010      4.217     21.151
  apply_status_update                                   3.085        3.360      3.525     11.768
  plan_status_transition                               13.780       14.201     14.933    365.198

# golden_myproj_transition (981 bytes)
  runs=5 warmup=10 target_name='beta'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft           689.163      703.845    733.439    733.439
  transition_changespec_status_wip_to_ready           644.686      683.184    706.999    706.999

# synthetic_200_specs_pure (121208 bytes)
  runs=200 warmup=20 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  is_valid_transition                                   2.444        2.594      2.815     20.701
  remove_workspace_suffix                               0.741        0.791      0.872      1.032
  read_status_from_lines                              245.228      261.752    278.016    314.090
  apply_status_update                                 280.951      286.870    299.679    305.818
  plan_status_transition                               13.721       14.081     14.913     87.932

# synthetic_200_specs_transition (121208 bytes)
  runs=5 warmup=10 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft         11707.847    11870.421  12799.103  12799.103
  transition_changespec_status_wip_to_ready         11694.948    11786.365  22197.098  22197.098

==== Phase 7 floor: bench_notification_store ====

==== Phase 7E floor check results ====
  rust_slowdown_factor = 1.40x phase7b rust median
  [PASS] parse_project_bytes.golden_myproj.facade: rust=44.68us python=n/a ceiling=174.09us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_project_bytes.synthetic_200_specs.facade: rust=4584.56us python=n/a ceiling=26762.65us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_query.parse_only.direct: rust=3.52us python=8.25us ceiling=8.08us must_beat_python=True
  [PASS] evaluate_query_many.synthetic_1000_specs.persistent_query_keystroke: rust=52.98us python=3834.05us ceiling=93.38us must_beat_python=True
  [PASS] scan_agent_artifacts.synthetic_6p_200pp.scan_facade: rust=123201.69us python=n/a ceiling=167984.20us must_beat_python=False
        note: scenario 'scan_facade' missing from baseline (python) summaries
  [PASS] apply_status_update.golden_myproj_pure.apply_status_update: rust=3.36us python=n/a ceiling=8.12us must_beat_python=False
        note: scenario 'apply_status_update' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_load_snapshot: rust=9598.95us python=n/a ceiling=18466.00us must_beat_python=False
        note: scenario 'notification_store_5k_load_snapshot' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_mark_dismissed_burst: rust=59800.07us python=n/a ceiling=6811056.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_dismissed_burst' missing from baseline (python) summaries
  [FAIL] notification_store.synthetic_5k.notification_store_5k_mark_all_read: rust=149134.60us python=n/a ceiling=100359.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_all_read' missing from baseline (python) summaries
        FAIL: absolute floor: rust median 149134.60us exceeds ceiling 100359.00us (=1.40x phase7b rust median 71685.00us)
  [PASS] notification_store.synthetic_5k.notification_store_append_plus_rewrite_concurrency: rust=1663016.81us python=n/a ceiling=2717251.60us must_beat_python=False
        note: scenario 'notification_store_append_plus_rewrite_concurrency' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_modal_dismiss_burst: rust=184209.71us python=n/a ceiling=5098492.80us must_beat_python=False
        note: scenario 'notification_modal_dismiss_burst' missing from baseline (python) summaries
        note: absolute floor uses per-anchor rust_slowdown_factor 1.60x instead of global 1.40x: This modal path performs 25 production one-at-a-time persisted dismissals from a loaded 5k inbox and has shown multi-second GitHub-hosted runner IO variance; keep the extra slack local to this anchor while preserving the global 1.4x gate for stable floors.

  report written to sdd/tales/202604/perf_artifacts/rust_backend_phase7_floor_check.json
error: Recipe `phase7-perf-check` failed on line 379 with exit code 1
Error: Process completed with exit code 1.
```