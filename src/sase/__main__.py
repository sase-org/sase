"""Allow running the package as a module: python -m sase"""

import time as _time

# Capture the earliest practical timestamp for the sase ace startup stopwatch
# before any sase imports run. See src/sase/main/startup_timing.py.
_PROCESS_START_PERF_COUNTER: float = _time.perf_counter()

from sase.main.startup_timing import set_process_start  # noqa: E402

set_process_start(_PROCESS_START_PERF_COUNTER)

from sase.main.entry import main  # noqa: E402

if __name__ == "__main__":
    main()
