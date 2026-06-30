"""
SAP Pacemaker Cluster Health Check - Access Data Models

Dataclass definitions for access discovery:
- NodeAccess: access information for a single cluster node
- AccessConfig: configuration for cluster access discovery
"""

from typing import Dict, Optional

# Python 3.6 compatibility for dataclasses
try:
    from dataclasses import dataclass, asdict  # pylint: disable=unused-import  # noqa: F401 - re-exported
except ImportError:
    # Fallback for Python < 3.7
    def field(default=None, default_factory=None):
        return default_factory() if default_factory else default

    def dataclass(cls):
        """Simple dataclass decorator fallback"""

        def __init__(self, **kwargs):
            # Set defaults from class annotations first
            if hasattr(cls, "__annotations__"):
                for name in cls.__annotations__:
                    default = getattr(cls, name, None)
                    setattr(self, name, default)
            # Override with provided kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)
            # Call __post_init__ if defined
            if hasattr(self, "__post_init__"):
                self.__post_init__()

        cls.__init__ = __init__
        return cls

    def asdict(obj):
        """Simple asdict fallback"""
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return obj


@dataclass
class NodeAccess:
    """Represents access information for a single node."""

    hostname: str = None
    ssh_reachable: bool = False
    ssh_user: Optional[str] = None
    ansible_reachable: bool = False
    ansible_host: Optional[str] = None
    ansible_user: Optional[str] = None
    sosreport_path: Optional[str] = None
    preferred_method: Optional[str] = None  # 'ssh', 'ansible', 'sosreport'
    last_checked: Optional[str] = None
    machine_id: Optional[str] = None  # Unique host identifier from /etc/machine-id


@dataclass
class AccessConfig:
    """Configuration for cluster access discovery."""

    ansible_inventory_source: Optional[str] = None
    ansible_inventory_path: Optional[str] = None
    sosreport_directory: Optional[str] = None
    hosts_file: Optional[str] = None
    nodes: Dict[str, dict] = None
    clusters: Dict[str, dict] = None  # cluster_name -> {nodes: [], discovered_from: host}
    discovery_timestamp: Optional[str] = None
    discovery_complete: bool = False

    def __post_init__(self):
        if self.nodes is None:
            self.nodes = {}
        if self.clusters is None:
            self.clusters = {}
