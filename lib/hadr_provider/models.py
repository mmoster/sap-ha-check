"""Data models for HA/DR provider hook validation."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ArchType(Enum):
    """Resource agent architecture type."""
    ANGI = "angi"       # sap-hana-ha package (RHEL 9+)
    LEGACY = "legacy"   # resource-agents-sap-hana / resource-agents-sap-hana-scaleout


class Topology(Enum):
    """SAP HANA cluster topology."""
    SCALE_UP = "Scale-Up"
    SCALE_OUT = "Scale-Out"


@dataclass
class HookConfig:
    """Expected or actual configuration for a single HA/DR provider hook."""
    section_name: str               # e.g. "ha_dr_provider_hanasr"
    provider: str                   # e.g. "HanaSR"
    path: str                       # e.g. "/usr/share/sap-hana-ha/"
    execution_order: int            # e.g. 1
    action_on_lost: Optional[str] = None   # e.g. "stop" (for ChkSrv/susChkSrv)
    is_optional: bool = False       # True for ChkSrv/susChkSrv hooks


@dataclass
class TraceConfig:
    """Expected or actual trace configuration."""
    entries: Dict[str, str] = field(default_factory=dict)
    # e.g. {"ha_dr_hanasr": "info", "ha_dr_chksrv": "info"}


@dataclass
class SudoersEntry:
    """A single expected sudoers line."""
    line_pattern: str       # Regex pattern to match in sudoers
    description: str        # Human-readable description
    example_line: str       # Exact expected line (with {sid} placeholder)
    is_optional: bool = False


@dataclass
class ExpectedConfig:
    """Full expected configuration for a given arch+topology+RHEL combination."""
    arch_type: ArchType
    topology: Topology
    rhel_major: int
    hooks: List[HookConfig]
    trace: TraceConfig
    sudoers_entries: List[SudoersEntry]
    provider_files: List[str]       # Paths that must exist on disk


@dataclass
class ActualConfig:
    """Configuration actually found on a node."""
    node: str
    sid: str
    sidadm: str
    global_ini_raw: str = ""
    global_ini_sections: Dict[str, Dict[str, str]] = field(default_factory=dict)
    trace_settings: Dict[str, str] = field(default_factory=dict)
    sudoers_raw: str = ""
    sudoers_lines: List[str] = field(default_factory=list)
    provider_files_found: List[str] = field(default_factory=list)
    provider_files_missing: List[str] = field(default_factory=list)
    installed_packages: List[str] = field(default_factory=list)
    rhel_version: str = ""


@dataclass
class Finding:
    """A single validation finding with remediation suggestion."""
    category: str           # "global_ini", "sudoers", "trace", "provider_file", "compatibility"
    severity: str           # "CRITICAL", "WARNING", "INFO"
    what_is_wrong: str      # Description of the problem
    expected_value: str     # What it should be
    actual_value: str       # What was found (or "missing")
    fix_description: str    # Human-readable fix instructions
    fix_command: str        # Shell command or config text to fix it
    node: str               # Which node this applies to
    section: Optional[str] = None   # global.ini section if applicable
