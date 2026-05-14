"""Local SASE daemon client helpers."""

from sase.daemon.changespec_reads import (
    load_changespecs_from_daemon,
    read_changespecs_or_fallback,
)
from sase.daemon.client import LocalDaemonClient, diff, health, read, rebuild, verify
from sase.daemon.constants import (
    LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    LOCAL_DAEMON_MAX_PAYLOAD_BYTES,
    LOCAL_DAEMON_SCHEMA_VERSION,
)
from sase.daemon.errors import (
    LocalDaemonError,
    LocalDaemonRpcError,
    LocalDaemonTransportError,
    LocalDaemonUnavailableError,
)
from sase.daemon.paths import daemon_disabled, default_socket_path
from sase.daemon.protocol import LocalDaemonTransport
from sase.daemon.read_facade import (
    DaemonReadResult,
    is_fallbackable_daemon_error,
    read_or_fallback,
)
from sase.daemon.read_models import (
    PROJECTION_READ_SCHEMA_VERSION,
    BeadDetailRead,
    BeadListRead,
    BeadStatsRead,
    ChangeSpecDetailRead,
    ChangeSpecListEntry,
    ChangeSpecListRead,
    GenericDaemonRead,
    NotificationDetailRead,
    NotificationListRead,
    ProjectionPage,
    ProjectionPayloadBound,
    ProjectionSnapshot,
    bead_detail_from_dict,
    bead_list_from_dict,
    bead_stats_from_dict,
    changespec_detail_from_dict,
    changespec_list_from_dict,
    generic_read_from_dict,
    notification_detail_from_dict,
    notification_list_from_dict,
)

__all__ = [
    "LOCAL_DAEMON_DEFAULT_PAGE_LIMIT",
    "LOCAL_DAEMON_MAX_PAYLOAD_BYTES",
    "LOCAL_DAEMON_SCHEMA_VERSION",
    "LocalDaemonClient",
    "LocalDaemonError",
    "LocalDaemonRpcError",
    "LocalDaemonTransport",
    "LocalDaemonTransportError",
    "LocalDaemonUnavailableError",
    "DaemonReadResult",
    "PROJECTION_READ_SCHEMA_VERSION",
    "BeadDetailRead",
    "BeadListRead",
    "BeadStatsRead",
    "ChangeSpecDetailRead",
    "ChangeSpecListEntry",
    "ChangeSpecListRead",
    "GenericDaemonRead",
    "NotificationDetailRead",
    "NotificationListRead",
    "ProjectionPage",
    "ProjectionPayloadBound",
    "ProjectionSnapshot",
    "bead_detail_from_dict",
    "bead_list_from_dict",
    "bead_stats_from_dict",
    "changespec_detail_from_dict",
    "changespec_list_from_dict",
    "default_socket_path",
    "daemon_disabled",
    "diff",
    "generic_read_from_dict",
    "health",
    "is_fallbackable_daemon_error",
    "load_changespecs_from_daemon",
    "notification_detail_from_dict",
    "notification_list_from_dict",
    "read",
    "read_changespecs_or_fallback",
    "read_or_fallback",
    "rebuild",
    "verify",
]
