---
plan: sdd/tales/202607/atomic_rust_dev_update.md
---
 I just updated sase and sase-core-rs from the "Updates" tab of the "SASE Admin Center" panel and then immediately started reporting the following error. I've since uninstalled the dev/editable version and re-installed the version that is published to PyPI.  Can you help me diagnose the root cause of this issue and prevent it from happening again? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
Traceback (most recent call last):
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/core/rust.py", line 43, in require_rust_extension
    return importlib.import_module(RUST_EXTENSION_MODULE_NAME)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/homebrew/Cellar/python@3.12/3.12.5/Frameworks/Python.framework/Versions/3.12/lib/python3.12/importlib/__init__.py", line 90, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 995, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/Users/bbugyi/.local/share/uv/tools/sase/lib/python3.12/site-packages/sase_core_rs/__init__.py", line 1, in <module>
    from .sase_core_rs import *
ModuleNotFoundError: No module named 'sase_core_rs.sase_core_rs'

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/__main__.py", line 6, in <module>
    main()
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/main/entry.py", line 44, in main
    handle_ace_command(args)
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/main/ace_handler.py", line 146, in handle_ace_command
    app = AceApp(
          ^^^^^^^
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/ace/tui/app.py", line 225, in __init__
    self._init_app_state(
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/ace/tui/actions/_state_init.py", line 119, in _init_app_state
    self.parsed_query = parse_query(query)
                        ^^^^^^^^^^^^^^^^^^
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/ace/query/parser.py", line 301, in parse_query
    return _facade(query)
           ^^^^^^^^^^^^^^
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/core/query_facade.py", line 36, in parse_query
    rust_parse_query = require_rust_binding("parse_query")
                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/core/rust.py", line 62, in require_rust_binding
    module = require_rust_extension()
             ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/core/rust.py", line 45, in require_rust_extension
    raise ImportError(
ImportError: sase_core_rs is not importable in this environment but is a hard runtime dependency of sase; reinstall with `just install` (or `just rust-install` for an editable build against ../sase-core).
```