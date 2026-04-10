"""
SAP Pacemaker Cluster Health Check - Library modules.

This package contains modular components:
- utils: Utility functions (resource scanning, SOSreport extraction, update checking)
- installation: Installation guides and step suggestions
- interactive: Interactive startup and usage scanning
- cib_parser: Unified CIB (cib.xml) parser for cluster configuration
"""

from .utils import (
    scan_for_resources,
    extract_sosreports_parallel,
    check_for_updates,
    SCRIPT_DIR,
)

from .installation import (
    print_guide,
    print_steps,
    print_suggestions,
)

from .interactive import (
    interactive_startup,
    run_usage_scan,
    print_usage_help,
)

from .cib_parser import CIBParser

__all__ = [
    # utils
    'scan_for_resources',
    'extract_sosreports_parallel',
    'check_for_updates',
    'SCRIPT_DIR',
    # installation
    'print_guide',
    'print_steps',
    'print_suggestions',
    # interactive
    'interactive_startup',
    'run_usage_scan',
    'print_usage_help',
    # cib_parser
    'CIBParser',
]
