"""SAP HANA HA/DR Provider Hook Validator.

Architecture-aware validation of HA/DR provider hooks for SAP HANA
Pacemaker clusters on RHEL 8/9/10.
"""

from .models import (
    ArchType, Topology, HookConfig, TraceConfig, SudoersEntry,
    ExpectedConfig, ActualConfig, Finding,
)
from .config_matrix import (
    get_expected_config, detect_arch_type, validate_rhel_arch_compatibility,
)
from .collector import parse_collected_output, has_required_data
from .validator import HadrValidator
