"""Public compatibility aliases for ``sase.integrations.daemon_lifecycle``."""

from __future__ import annotations

from sase.integrations import _daemon_lifecycle_types as _types
from sase.integrations import _daemon_lifecycle_values as _values

DEFAULT_STARTUP_TIMEOUT_SECONDS = _types.DEFAULT_STARTUP_TIMEOUT_SECONDS
DEFAULT_STOP_TIMEOUT_SECONDS = _types.DEFAULT_STOP_TIMEOUT_SECONDS
LOCK_FILENAME = _types.LOCK_FILENAME
LOCK_METADATA_FILENAME = _types.LOCK_METADATA_FILENAME
LOCK_SCHEMA_VERSION = _types.LOCK_SCHEMA_VERSION
SOCKET_FILENAME = _types.SOCKET_FILENAME
KillFn = _types.KillFn
PopenFactory = _types.PopenFactory
SleepFn = _types.SleepFn
DaemonInspection = _types.DaemonInspection
DaemonLaunch = _types.DaemonLaunch
DaemonLifecycleConfig = _types.DaemonLifecycleConfig
DaemonLifecycleError = _types.DaemonLifecycleError
DaemonRuntimePaths = _types.DaemonRuntimePaths
command_value = _values.command_value
int_value = _values.int_value
optional_path = _values.optional_path
positive_float = _values.positive_float
