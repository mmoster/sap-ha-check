#!/usr/bin/env python3
"""
SAP Pacemaker Cluster Health Check - Main Wrapper

This is the main entry point for the cluster health check tool.
It orchestrates all checks starting with access discovery.

Workflow:
1. Discover access methods to cluster nodes
2. Run cluster configuration checks (CHK_* rules)
3. Run Pacemaker/Corosync checks
4. Run SAP-specific checks
5. Generate report
"""

import os
import sys
import re
import argparse
import yaml
from pathlib import Path
from datetime import datetime

try:
    from dataclasses import asdict
except ImportError:
    # Python < 3.7 fallback
    def asdict(obj):
        """Simple fallback for dataclasses.asdict"""
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        return obj

# Add modules to path
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR / "access"))
sys.path.insert(0, str(SCRIPT_DIR / "rules"))

from discover_access import AccessDiscovery, show_config, delete_config, export_ansible_vars, fetch_sosreports, create_and_fetch_sosreports  # noqa: E402
from engine import RulesEngine, CheckResult, CheckStatus, Severity  # noqa: E402

# Import lib modules
from lib import (  # noqa: E402
    print_guide,
    print_steps,
    print_suggestions,
    interactive_startup,
    run_usage_scan,
    ClusterReportData,
    REPORT_VERSION,
)
from lib.config_extractor import ConfigExtractor  # noqa: E402

import threading  # noqa: E402
import itertools  # noqa: E402


class Spinner:
    """
    A simple spinner context manager that shows progress during long operations.
    Usage:
        with Spinner("Checking nodes"):
            do_long_operation()
    """
    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    FALLBACK_FRAMES = ['|', '/', '-', '\\']  # For terminals without Unicode

    def __init__(self, message: str = "Working", delay: float = 0.1):
        self.message = message
        self.delay = delay
        self._stop_event = threading.Event()
        self._thread = None
        # Test if Unicode works
        try:
            sys.stdout.write('\r⠋')
            sys.stdout.write('\r \r')
            sys.stdout.flush()
            self.frames = self.FRAMES
        except (UnicodeEncodeError, UnicodeError):
            self.frames = self.FALLBACK_FRAMES

    def _spin(self):
        """Spinner animation loop."""
        spinner = itertools.cycle(self.frames)
        while not self._stop_event.is_set():
            frame = next(spinner)
            sys.stdout.write(f'\r  {frame} {self.message}...')
            sys.stdout.flush()
            self._stop_event.wait(self.delay)
        # Clear the spinner line
        sys.stdout.write('\r' + ' ' * (len(self.message) + 10) + '\r')
        sys.stdout.flush()

    def __enter__(self):
        # Only show spinner if stdout is a terminal (not redirected)
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)

    def update(self, message: str):
        """Update the spinner message."""
        self.message = message


class ClusterHealthCheck:
    """Main orchestrator for SAP Pacemaker cluster health checks."""

    # Default rules path relative to script directory
    DEFAULT_RULES_PATH = str(SCRIPT_DIR / "rules" / "health_checks")

    def __init__(self, config_dir: str = None, sosreport_dir: str = None,
                 hosts_file: str = None, workers: int = 10, rules_path: str = None,
                 debug: bool = False, ansible_group: str = None, skip_ansible: bool = False,
                 cluster_name: str = None, local_mode: bool = False, strict_mode: bool = False,
                 generate_pdf: bool = False, verbose_pdf: bool = False):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.sosreport_dir = sosreport_dir
        self.hosts_file = hosts_file
        self.workers = workers
        self.rules_path = rules_path or self.DEFAULT_RULES_PATH
        self.access_config = None
        self.rules_engine = None
        self.check_results = []
        self.debug = debug
        self.ansible_group = ansible_group
        self.skip_ansible = skip_ansible
        self.cluster_name = cluster_name
        self.local_mode = local_mode
        self.strict_mode = strict_mode
        self.generate_pdf = generate_pdf
        self.verbose_pdf = verbose_pdf  # Show all checks in detail in PDF
        self.majority_makers = []  # Nodes that are majority makers (Scale-Out)
        self.last_pdf_file = None  # Track last generated PDF for auto-open
        self._hana_resource_state = 'unknown'  # running/stopped/disabled/unmanaged/absent
        self._hana_db_status = {}  # HANA DB status and replication info

    def _debug_print(self, message: str):
        """Print debug message if debug mode is enabled."""
        if self.debug:
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            print(f"  [DEBUG {timestamp}] {message}")

    def _extract_cluster_config(self, cluster_name: str = None) -> dict:
        """
        Extract detailed cluster configuration using ConfigExtractor.

        Uses the appropriate extraction method based on access method:
        - SOSreport: parse pcs_config file directly
        - SSH offline: run pcs -f cib.xml config remotely
        - Running cluster: run pcs config

        Args:
            cluster_name: Cluster name for finding config

        Returns:
            Dict with extracted configuration merged with existing cluster_config
        """
        extracted = {}

        # Find source for extraction
        if self.access_config:
            # Get first node's info to determine access method
            nodes = self.access_config.nodes or {}
            for node_name, node_info in nodes.items():
                # Try SOSreport first
                sos_path = node_info.get('sosreport_path')
                if sos_path:
                    self._debug_print(f"Extracting config from SOSreport: {sos_path}")
                    extractor = ConfigExtractor.from_sosreport(sos_path)
                    if extractor:
                        extracted = extractor.get_config()
                        # Write config YAML for reference
                        config_yaml = self.config_dir / f"{cluster_name or 'cluster'}_config.yaml"
                        try:
                            extractor.write_yaml(str(config_yaml))
                            self._debug_print(f"Config written to: {config_yaml}")
                        except Exception as e:
                            self._debug_print(f"Failed to write config YAML: {e}")
                        break

                # Try SSH method if no SOSreport
                method = node_info.get('preferred_method')
                if method == 'ssh':
                    user = node_info.get('ssh_user', 'root')
                    # Check if cluster is running (from access config or default to trying running first)
                    cluster_running = True
                    if self.access_config and hasattr(self.access_config, 'clusters'):
                        for cinfo in self.access_config.clusters.values():
                            if node_name in cinfo.get('nodes', []):
                                cluster_running = cinfo.get('cluster_running', True)
                                break

                    if cluster_running:
                        self._debug_print(f"Extracting config from running cluster via SSH: {node_name}")
                        extractor = ConfigExtractor.from_running_cluster(node_name, user)
                        # If running cluster extraction fails, try offline
                        if not extractor:
                            self._debug_print(f"Running cluster extraction failed, trying offline: {node_name}")
                            extractor = ConfigExtractor.from_ssh_offline(node_name, user)
                    else:
                        self._debug_print(f"Extracting config from offline cluster via SSH: {node_name}")
                        extractor = ConfigExtractor.from_ssh_offline(node_name, user)

                    if extractor:
                        extracted = extractor.get_config()
                        config_yaml = self.config_dir / f"{cluster_name or 'cluster'}_config.yaml"
                        try:
                            extractor.write_yaml(str(config_yaml))
                            self._debug_print(f"Config written to: {config_yaml}")
                        except Exception as e:
                            self._debug_print(f"Failed to write config YAML: {e}")
                        break

        # Return sap_hana section merged with other relevant fields
        result = {}
        if extracted:
            hana = extracted.get('sap_hana', {})
            stonith = extracted.get('stonith', {})
            constraints = extracted.get('constraints', {})
            cluster = extracted.get('cluster', {})

            # Cluster/system info
            result['rhel_version'] = cluster.get('rhel_version')
            result['pacemaker_version'] = cluster.get('pacemaker_version')

            # SAP HANA config
            result['sid'] = hana.get('sid')
            result['instance_number'] = hana.get('instance_number')
            result['virtual_ip'] = hana.get('virtual_ip')
            result['secondary_vip'] = hana.get('secondary_vip')
            result['vip_resource'] = hana.get('vip_resource')
            result['secondary_vip_resource'] = hana.get('secondary_vip_resource')

            # HA parameters
            result['prefer_site_takeover'] = hana.get('prefer_site_takeover')
            result['automated_register'] = hana.get('automated_register')
            result['duplicate_primary_timeout'] = hana.get('duplicate_primary_timeout')
            result['clone_max'] = hana.get('clone_max')

            # Resource info
            result['resource_type'] = hana.get('resource_type')
            result['resource_name'] = hana.get('resource_name')
            if hana.get('topology'):
                result['topology_resource'] = hana['topology'].get('resource_name')

            # STONITH
            result['stonith_device'] = stonith.get('device')
            result['stonith_params'] = {
                'pcmk_host_map': stonith.get('pcmk_host_map', ''),
                'ssl': stonith.get('ssl', ''),
                'ssl_insecure': stonith.get('ssl_insecure', ''),
            }

            # Majority maker
            if constraints.get('majority_maker'):
                result['majority_maker'] = constraints['majority_maker']

        return result

    def _build_cluster_report_data(self, cluster_name: str = None,
                                    summary: dict = None) -> ClusterReportData:
        """
        Build unified ClusterReportData from current state.

        This is the single source of truth for all report data, consolidating
        information from:
        - AccessConfig (cluster configuration)
        - RulesEngine (data source info, resource config from cib.xml)
        - check_results (health check results)
        - check_install_status (installation status)

        Args:
            cluster_name: Override cluster name (auto-detected if None)
            summary: Pre-computed summary dict (computed if None)

        Returns:
            ClusterReportData instance with all fields populated
        """
        # Auto-detect cluster name if not provided
        if cluster_name is None:
            cluster_name = 'unknown'
            if self.access_config and hasattr(self.access_config, 'clusters'):
                # Find cluster name from nodes
                for cname, cinfo in self.access_config.clusters.items():
                    nodes = cinfo.get('nodes', [])
                    if any(n in (self.access_config.nodes or {}) for n in nodes):
                        cluster_name = cname
                        break
                # Fallback: use most recently discovered cluster
                if cluster_name == 'unknown':
                    latest = None
                    for cname, cinfo in self.access_config.clusters.items():
                        discovered_at = cinfo.get('discovered_at', '')
                        if latest is None or discovered_at > latest:
                            latest = discovered_at
                            cluster_name = cname

        # Get cluster configuration from access_config
        cluster_config = {}
        if self.access_config and hasattr(self.access_config, 'clusters'):
            cluster_config = self.access_config.clusters.get(cluster_name, {})

        # Extract detailed config from pcs config output
        # This fills in SAP HANA parameters, VIPs, STONITH, etc.
        extracted_config = self._extract_cluster_config(cluster_name)
        if extracted_config:
            # Merge extracted config - extracted values take precedence for None/empty values
            for key, value in extracted_config.items():
                if value is not None and (cluster_config.get(key) is None or cluster_config.get(key) == ''):
                    cluster_config[key] = value

        # Get node list
        node_list = list(self.access_config.nodes.keys()) if self.access_config else []

        # Determine cluster type from CHK_CLUSTER_TYPE result (uses clone-max)
        cluster_type = 'Scale-Up'  # Default
        cluster_type_result = next(
            (r for r in self.check_results if r.check_id == 'CHK_CLUSTER_TYPE'),
            None
        )
        if cluster_type_result and cluster_type_result.details:
            cluster_type = cluster_type_result.details.get('cluster_type', 'Scale-Up')
        else:
            # Fallback if no check result - use clone-max from resource config
            clone_max = cluster_config.get('clone_max', 2)
            try:
                clone_max = int(clone_max) if clone_max else 2
            except (ValueError, TypeError):
                clone_max = 2
            if clone_max > 2:
                cluster_type = 'Scale-Out'

        # Get data source info from rules engine
        data_source_info = {}
        if self.rules_engine:
            data_source_info = self.rules_engine.get_data_source_info()

        # Get resource configuration from cib.xml
        resource_config = {}
        majority_makers = list(self.majority_makers) if self.majority_makers else []
        if self.rules_engine:
            resource_config = self.rules_engine.get_cluster_resources_config()
            # Majority maker only exists in Scale-Out (clone-max >= 4)
            # Nodes with HANA exclusion constraints in Scale-Up are app servers, not majority makers
            if resource_config.get('available') and resource_config.get('majority_maker'):
                mm_node = resource_config['majority_maker']
                if cluster_type == 'Scale-Out':
                    if mm_node not in majority_makers:
                        majority_makers.append(mm_node)
                    self._debug_print(f"Scale-Out majority maker: {mm_node}")
                else:
                    self._debug_print(f"Node {mm_node} has HANA exclusion constraints but cluster is {cluster_type} (app server, not majority maker)")

        # Build results list from check_results
        results_dict = [
            {
                'check_id': r.check_id,
                'node': r.node,
                'status': r.status.value,
                'severity': r.severity.value,
                'message': r.message,
                'description': r.description,
                'details': r.details if r.details else {}
            }
            for r in self.check_results
        ]

        # Compute summary if not provided
        if summary is None:
            total = len(self.check_results)
            passed = sum(1 for r in self.check_results if r.status == CheckStatus.PASSED)
            failed = sum(1 for r in self.check_results if r.status == CheckStatus.FAILED)
            skipped = sum(1 for r in self.check_results if r.status == CheckStatus.SKIPPED)
            errors = sum(1 for r in self.check_results if r.status == CheckStatus.ERROR)
            critical_failures = [r for r in self.check_results
                                 if r.status == CheckStatus.FAILED and r.severity == Severity.CRITICAL]
            warnings = [r for r in self.check_results
                        if r.status == CheckStatus.FAILED and r.severity == Severity.WARNING]
            summary = {
                'total': total,
                'passed': passed,
                'failed': failed,
                'skipped': skipped,
                'errors': errors,
                'critical_count': len(critical_failures),
                'warning_count': len(warnings)
            }

        # Get installation status
        install_status = None
        try:
            install_status = self.check_install_status()
        except Exception:
            pass

        # Determine if cluster is running
        # First check discovery-time status (from access discovery)
        cluster_running = cluster_config.get('cluster_running', True)

        # Also check install status (runtime check)
        if install_status:
            has_config = install_status.get('corosync_conf_exists') or install_status.get('cib_exists')
            pacemaker_running = install_status.get('pacemaker_running')
            if has_config and not pacemaker_running:
                cluster_running = False

        # Build the unified report data
        report_data = ClusterReportData(
            # Metadata
            version=REPORT_VERSION,
            timestamp=datetime.now().isoformat(),

            # Data source
            data_source=data_source_info.get('description', 'Unknown'),
            access_method=data_source_info.get('primary_method', 'unknown'),
            used_cib_xml=data_source_info.get('used_cib_xml', False),
            cluster_running=cluster_running,
            hana_resource_state=self._hana_resource_state,
            hana_db_status=self._hana_db_status if self._hana_db_status else None,

            # Cluster info
            cluster_name=cluster_name,
            cluster_type=cluster_type,
            nodes=node_list,
            majority_makers=majority_makers,

            # OS/Software versions (from install_status or extracted config)
            rhel_version=(install_status.get('rhel_version') if install_status else None) or cluster_config.get('rhel_version'),
            pacemaker_version=(install_status.get('pacemaker_version') if install_status else None) or cluster_config.get('pacemaker_version'),

            # SAP HANA config
            sid=cluster_config.get('sid'),
            instance_number=cluster_config.get('instance_number'),
            virtual_ip=cluster_config.get('virtual_ip'),
            secondary_vip=cluster_config.get('secondary_vip'),
            replication_mode=cluster_config.get('replication_mode'),
            operation_mode=cluster_config.get('operation_mode'),
            secondary_read=cluster_config.get('secondary_read'),

            # Node config
            node1_hostname=cluster_config.get('node1_hostname'),
            node1_ip=cluster_config.get('node1_ip'),
            node2_hostname=cluster_config.get('node2_hostname'),
            node2_ip=cluster_config.get('node2_ip'),
            sites=cluster_config.get('sites'),

            # HA parameters
            prefer_site_takeover=cluster_config.get('prefer_site_takeover'),
            automated_register=cluster_config.get('automated_register'),
            duplicate_primary_timeout=cluster_config.get('duplicate_primary_timeout'),
            migration_threshold=cluster_config.get('migration_threshold'),

            # Resource config
            resource_type=cluster_config.get('resource_type'),
            resource_name=cluster_config.get('resource_name'),
            topology_resource=cluster_config.get('topology_resource'),
            vip_resource=cluster_config.get('vip_resource'),
            secondary_vip_resource=cluster_config.get('secondary_vip_resource'),

            # STONITH
            stonith_device=cluster_config.get('stonith_device'),
            stonith_params=cluster_config.get('stonith_params'),

            # CIB resource config
            resource_config=resource_config if resource_config.get('available') else {},

            # Installation status
            install_status=install_status or {},

            # Results
            results=results_dict,
            summary=summary,
        )

        return report_data

    def check_install_status_sosreport(self, node: str, sosreport_path: str) -> dict:
        """
        Check installation status from a SOSreport directory.
        Returns dict with status of each installation step based on captured data.
        """
        sos_path = Path(sosreport_path)

        status = {
            # Phase 1: Prerequisites
            'subscription_registered': None,
            'repos_enabled': None,
            'firewall_configured': None,
            'packages_installed': None,
            'hacluster_password': None,
            'pcsd_running': None,
            'pcsd_enabled': None,
            # Phase 2: Cluster Creation
            'nodes_authenticated': None,
            'corosync_conf_exists': None,
            'cib_exists': None,
            'cluster_configured': None,
            'corosync_running': None,
            'pacemaker_running': None,
            'cluster_enabled': None,
            'cluster_online': None,
            # Phase 3: Fencing & Resources
            'stonith_enabled': None,
            'stonith_configured': None,
            'hana_installed': None,
            'hana_resources': None,
            # Details
            'missing_packages': [],
            'missing_repos': [],
            'node': node,
            'method': 'sosreport',
            'cluster_name': None,
            'cluster_nodes': [],
            'offline_nodes': [],
            # Version info
            'rhel_version': None,
            'pacemaker_version': None,
        }

        # Detect RHEL version from redhat-release
        redhat_release = sos_path / "etc/redhat-release"
        if redhat_release.exists():
            try:
                content = redhat_release.read_text().strip()
                match = re.search(r'release\s+(\d+\.?\d*)', content)
                if match:
                    status['rhel_version'] = f"RHEL {match.group(1)}"
                else:
                    status['rhel_version'] = content[:50]
            except Exception:
                pass

        # Detect Pacemaker version from installed-rpms
        installed_rpms = sos_path / "installed-rpms"
        if installed_rpms.exists():
            try:
                content = installed_rpms.read_text()
                match = re.search(r'pacemaker-(\d+\.\d+\.\d+)', content)
                if match:
                    status['pacemaker_version'] = match.group(1)
            except Exception:
                pass

        # Check if corosync.conf exists
        corosync_conf = sos_path / "etc/corosync/corosync.conf"
        status['corosync_conf_exists'] = corosync_conf.exists()

        # Check if cib.xml exists (cluster configuration exists)
        cib_xml = sos_path / "var/lib/pacemaker/cib/cib.xml"
        status['cib_exists'] = cib_xml.exists()

        # Extract cluster name from corosync.conf
        if corosync_conf.exists():
            try:
                content = corosync_conf.read_text()
                match = re.search(r'cluster_name:\s*(\S+)', content)
                if match:
                    status['cluster_name'] = match.group(1)
            except Exception:
                pass

        # Check packages from installed-rpms
        installed_rpms = sos_path / "installed-rpms"
        if installed_rpms.exists():
            try:
                content = installed_rpms.read_text()
                required_packages = ['pacemaker', 'corosync', 'pcs']
                sap_packages = ['sap-hana-ha', 'resource-agents-sap-hana', 'resource-agents-sap-hana-scaleout']

                missing = []
                for pkg in required_packages:
                    if pkg not in content:
                        missing.append(pkg)

                sap_found = any(pkg in content for pkg in sap_packages)
                if not sap_found:
                    missing.append('sap-hana-ha')

                status['missing_packages'] = missing
                status['packages_installed'] = len(missing) == 0
            except Exception:
                pass

        # Check pcs status output (try different filename variants)
        pcs_status = sos_path / "sos_commands/pacemaker/pcs_status_--full"
        if not pcs_status.exists():
            pcs_status = sos_path / "sos_commands/pacemaker/pcs_status"
        if pcs_status.exists():
            try:
                content = pcs_status.read_text()
                status['cluster_configured'] = 'Cluster name:' in content or 'nodes configured' in content

                # Check for online nodes - handle both formats:
                # Old format: "Online: [ node1 node2 ]"
                # New format: "Node nodename (id): online"
                if 'Online:' in content:
                    status['cluster_online'] = True
                    match = re.search(r'Online:\s*\[\s*(.*?)\s*\]', content)
                    if match:
                        status['cluster_nodes'] = [n.strip() for n in match.group(1).split() if n.strip()]

                # New pcs status format: "Node nodename (id): online"
                node_matches = re.findall(r'Node\s+(\S+)\s+\(\d+\):\s+online', content, re.IGNORECASE)
                if node_matches:
                    status['cluster_online'] = True
                    status['cluster_nodes'] = node_matches

                # Check STONITH - look for stonith resources running
                if 'stonith:' in content.lower() and 'Started' in content:
                    status['stonith_enabled'] = True
                elif 'stonith-enabled=true' in content.lower() or 'stonith-enabled: true' in content.lower():
                    status['stonith_enabled'] = True
                elif 'stonith-enabled=false' in content.lower() or 'stonith-enabled: false' in content.lower():
                    status['stonith_enabled'] = False

                # Check HANA resources
                if 'SAPHana' in content:
                    status['hana_resources'] = True
            except Exception:
                pass

        # Check systemctl output for service status
        systemctl_output = sos_path / "sos_commands/systemd/systemctl_list-units_--all"
        if systemctl_output.exists():
            try:
                content = systemctl_output.read_text()
                status['corosync_running'] = 'corosync.service' in content and 'running' in content.lower()
                status['pacemaker_running'] = 'pacemaker.service' in content and 'running' in content.lower()
                status['pcsd_running'] = 'pcsd.service' in content and 'running' in content.lower()
            except Exception:
                pass

        # Check for HANA installation
        hana_check = sos_path / "usr/sap"
        if not hana_check.exists():
            # Try alternative location in sos data
            proc_mounts = sos_path / "proc/mounts"
            if proc_mounts.exists():
                try:
                    content = proc_mounts.read_text()
                    status['hana_installed'] = '/usr/sap/' in content or '/hana/' in content.lower()
                except Exception:
                    pass

        return status

    def _execute_check_cmd(self, cmd: str, node: str, method: str, user: str = None) -> tuple:
        """Execute a command on a node and return (success, output)."""
        import subprocess
        try:
            if method == 'local':
                full_cmd = cmd
            elif method == 'ssh':
                ssh_user = user or 'root'
                escaped_cmd = cmd.replace("'", "'\"'\"'")
                full_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_user}@{node} '{escaped_cmd}'"
            else:
                return False, "Unsupported method"

            if self.debug:
                print(f"  [DEBUG] Executing: {full_cmd[:100]}...")

            result = subprocess.run(
                full_cmd, shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=30
            )

            if self.debug:
                print(f"  [DEBUG] Return code: {result.returncode}, Output: {result.stdout.strip()[:50]}...")

            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            if self.debug:
                print(f"  [DEBUG] Exception: {e}")
            return False, str(e)

    def check_install_status(self, node: str = None, method: str = 'ssh', user: str = None) -> dict:
        """
        Check installation status on a node.
        Returns dict with status of each installation step.
        """
        status = {
            # Phase 1: Prerequisites
            'subscription_registered': None,
            'repos_enabled': None,
            'firewall_configured': None,
            'packages_installed': None,
            'hacluster_password': None,
            'pcsd_running': None,
            'pcsd_enabled': None,
            # Phase 2: Cluster Creation
            'nodes_authenticated': None,
            'corosync_conf_exists': None,
            'cib_exists': None,
            'cluster_configured': None,
            'corosync_running': None,
            'pacemaker_running': None,
            'cluster_enabled': None,
            'cluster_online': None,
            # Phase 3: Fencing & Resources
            'stonith_enabled': None,
            'stonith_configured': None,
            'hana_installed': None,
            'hana_resources': None,
            # Details
            'missing_packages': [],
            'missing_repos': [],
            'node': node,
            'method': method,
            'cluster_name': None,
            'cluster_nodes': [],
            'offline_nodes': [],
            # Version info
            'rhel_version': None,
            'pacemaker_version': None,
        }

        if not node and not self.access_config:
            return status

        # Use first accessible node if not specified
        if not node and self.access_config:
            for n, info in self.access_config.nodes.items():
                if info.get('preferred_method'):
                    node = n
                    method = info.get('preferred_method', 'ssh')
                    user = info.get('ssh_user', 'root')
                    break

        if not node:
            return status

        status['node'] = node

        # For sosreport mode, use the sosreport-specific method
        if method == 'sosreport' and self.access_config:
            node_info = self.access_config.nodes.get(node, {})
            sosreport_path = node_info.get('sosreport_path')
            if sosreport_path:
                return self.check_install_status_sosreport(node, sosreport_path)

        # Check packages FIRST (if installed, subscription/repos don't matter)
        # Note: rpm -q returns exit code 1 if ANY package is missing, but still outputs info
        # SAP resource agent packages (any one is OK):
        #   - sap-hana-ha: RHEL 9/10, Scale-Up & Scale-Out (recommended, required for RHEL 10)
        #   - resource-agents-sap-hana: legacy Scale-Up (RHEL 8/9)
        #   - resource-agents-sap-hana-scaleout: legacy Scale-Out (RHEL 8/9)
        required_packages = ['pacemaker', 'corosync', 'pcs']
        sap_packages = ['sap-hana-ha', 'resource-agents-sap-hana', 'resource-agents-sap-hana-scaleout']
        success, output = self._execute_check_cmd(
            "rpm -q pacemaker corosync pcs sap-hana-ha resource-agents-sap-hana resource-agents-sap-hana-scaleout 2>/dev/null",
            node, method, user
        )
        # Parse output even if exit code is non-zero (rpm returns 1 if any package missing)
        if output:
            for pkg in required_packages:
                if f'{pkg} is not installed' in output or f'package {pkg} is not installed' in output:
                    status['missing_packages'].append(pkg)
                elif pkg not in output:
                    status['missing_packages'].append(pkg)
            # Check if at least one SAP package is installed
            sap_pkg_found = any(pkg in output and f'{pkg} is not installed' not in output
                               for pkg in sap_packages)
            if not sap_pkg_found:
                status['missing_packages'].append('sap-hana-ha')  # Recommend newer package
            status['packages_installed'] = len(status['missing_packages']) == 0
        else:
            status['packages_installed'] = False
            status['missing_packages'] = required_packages + ['sap-hana-ha']

        # Detect RHEL version from /etc/redhat-release
        success, output = self._execute_check_cmd(
            "cat /etc/redhat-release 2>/dev/null",
            node, method, user
        )
        if success and output:
            # Extract version like "Red Hat Enterprise Linux release 9.5 (Plow)" -> "RHEL 9.5"
            import re as regex_mod
            match = regex_mod.search(r'release\s+(\d+\.?\d*)', output)
            if match:
                status['rhel_version'] = f"RHEL {match.group(1)}"
            else:
                status['rhel_version'] = output.strip()[:50]  # Fallback to raw output

        # Detect Pacemaker version
        success, output = self._execute_check_cmd(
            "rpm -q pacemaker 2>/dev/null | head -1",
            node, method, user
        )
        if success and output and 'not installed' not in output:
            # Extract version like "pacemaker-2.1.8-3.el9.x86_64" -> "2.1.8"
            import re as regex_mod
            match = regex_mod.search(r'pacemaker-(\d+\.\d+\.\d+)', output)
            if match:
                status['pacemaker_version'] = match.group(1)
            else:
                status['pacemaker_version'] = output.strip()[:30]

        # If packages are installed, subscription/repos are OK (could be local repo)
        if status['packages_installed']:
            status['subscription_registered'] = True
            status['repos_enabled'] = True
        else:
            # Check subscription status
            success, output = self._execute_check_cmd(
                "subscription-manager identity 2>/dev/null | grep -qE 'system identity|org ID' && echo 'registered' || "
                "subscription-manager status 2>/dev/null | grep -qE 'Overall Status:' && echo 'registered' || "
                "test -f /etc/yum.repos.d/*.repo && echo 'registered'",
                node, method, user
            )
            status['subscription_registered'] = success and 'registered' in output

            # Check required repos
            success, output = self._execute_check_cmd(
                "subscription-manager repos --list-enabled 2>/dev/null | grep -E 'highavailability|sap' || "
                "dnf repolist 2>/dev/null | grep -iE 'highavailability|ha|sap'",
                node, method, user
            )
            status['repos_enabled'] = success and output.strip() != ''
            if not status['repos_enabled']:
                status['missing_repos'] = ['highavailability', 'sap-solutions']

        # Check firewall configuration
        success, output = self._execute_check_cmd(
            "firewall-cmd --list-services 2>/dev/null | grep -q high-availability && echo 'configured' || "
            "systemctl is-active firewalld 2>/dev/null | grep -q inactive && echo 'configured'",
            node, method, user
        )
        status['firewall_configured'] = success and 'configured' in output

        # Check hacluster user password is set (can login)
        success, output = self._execute_check_cmd(
            "getent shadow hacluster 2>/dev/null | grep -v '!' | grep -q ':' && echo 'password_set'",
            node, method, user
        )
        status['hacluster_password'] = success and 'password_set' in output

        # Check pcsd service running
        success, output = self._execute_check_cmd(
            "systemctl is-active pcsd 2>/dev/null",
            node, method, user
        )
        status['pcsd_running'] = success and 'active' in output

        # Check pcsd service enabled
        success, output = self._execute_check_cmd(
            "systemctl is-enabled pcsd 2>/dev/null",
            node, method, user
        )
        status['pcsd_enabled'] = success and 'enabled' in output

        # Check if nodes are authenticated (known-hosts has multiple nodes)
        # pcs host auth stores tokens in /var/lib/pcsd/known-hosts
        success, output = self._execute_check_cmd(
            "cat /var/lib/pcsd/known-hosts 2>/dev/null | grep -c '\"token\"' || echo '0'",
            node, method, user
        )
        try:
            token_count = int(output.strip())
            status['nodes_authenticated'] = token_count >= 2  # At least 2 nodes authenticated
        except (ValueError, AttributeError):
            status['nodes_authenticated'] = False

        # Check if corosync.conf exists (cluster was set up)
        success, output = self._execute_check_cmd(
            "test -f /etc/corosync/corosync.conf && echo 'exists'",
            node, method, user
        )
        status['corosync_conf_exists'] = success and 'exists' in output

        # Check if cib.xml exists (cluster configuration exists - even if not running)
        success, output = self._execute_check_cmd(
            "test -f /var/lib/pacemaker/cib/cib.xml && echo 'exists'",
            node, method, user
        )
        status['cib_exists'] = success and 'exists' in output

        # Check cluster configured and get cluster name
        success, output = self._execute_check_cmd(
            "pcs cluster status 2>/dev/null | head -10",
            node, method, user
        )
        status['cluster_configured'] = success and 'Cluster' in output
        if success:
            # Try to extract cluster name
            match = re.search(r'Cluster name:\s*(\S+)', output)
            if match:
                status['cluster_name'] = match.group(1)

        # Check corosync service
        success, output = self._execute_check_cmd(
            "systemctl is-active corosync 2>/dev/null",
            node, method, user
        )
        status['corosync_running'] = success and 'active' in output

        # Check pacemaker service
        success, output = self._execute_check_cmd(
            "systemctl is-active pacemaker 2>/dev/null",
            node, method, user
        )
        status['pacemaker_running'] = success and 'active' in output

        # Check cluster enabled (auto-start on boot)
        success, output = self._execute_check_cmd(
            "systemctl is-enabled corosync pacemaker 2>/dev/null | grep -q enabled && echo 'enabled'",
            node, method, user
        )
        status['cluster_enabled'] = success and 'enabled' in output

        # Check if nodes are online
        success, output = self._execute_check_cmd(
            "pcs status nodes 2>/dev/null",
            node, method, user
        )
        if success:
            status['cluster_online'] = 'Online:' in output and output.strip() != ''
            # Extract online nodes - handles both "Online: [ node1 node2 ]" and "Online: node1 node2"
            # Try bracket format first
            match = re.search(r'Online:\s*\[\s*(.*?)\s*\]', output)
            if match:
                status['cluster_nodes'] = [n.strip() for n in match.group(1).split() if n.strip()]
            else:
                # Try space-separated format: "Online: node1 node2"
                match = re.search(r'Online:\s*(.+?)(?:\n|$)', output)
                if match:
                    nodes = match.group(1).strip()
                    # Filter out empty strings and common non-node words
                    status['cluster_nodes'] = [n.strip() for n in nodes.split()
                                               if n.strip() and n.strip() not in ['Standby:', 'Offline:', 'Maintenance:']]

        # Check STONITH enabled (default is true if not explicitly set in modern pacemaker)
        success, output = self._execute_check_cmd(
            "pcs property show stonith-enabled 2>/dev/null",
            node, method, user
        )
        # If stonith-enabled is explicitly set to false, it's disabled
        # If not set or set to true, it's enabled
        if success:
            if 'false' in output.lower():
                status['stonith_enabled'] = False
            else:
                # Check if stonith devices exist (if they do, stonith is effectively enabled)
                stonith_check, stonith_out = self._execute_check_cmd(
                    "pcs stonith status 2>/dev/null | grep -E 'Started|Stopped'",
                    node, method, user
                )
                status['stonith_enabled'] = stonith_check and stonith_out.strip() != ''

        # Check STONITH configured and running
        success, output = self._execute_check_cmd(
            "pcs stonith status 2>/dev/null",
            node, method, user
        )
        if success:
            status['stonith_configured'] = 'Started' in output
            if 'NO stonith' in output or 'no stonith' in output.lower():
                status['stonith_configured'] = False
                status['stonith_enabled'] = False

        # Check HANA installed
        success, output = self._execute_check_cmd(
            "ls -d /usr/sap/*/HDB[0-9][0-9] 2>/dev/null | head -1",
            node, method, user
        )
        status['hana_installed'] = success and '/usr/sap/' in output

        # Check HANA resources
        success, output = self._execute_check_cmd(
            "pcs resource status 2>/dev/null | grep -i saphana",
            node, method, user
        )
        status['hana_resources'] = success and 'SAPHana' in output

        return status

    def print_dynamic_install_guide(self, node: str = None):
        """Print installation guide showing only steps that are still needed."""
        print("\n" + "=" * 63)
        print(" Checking current installation status...")
        print("=" * 63)

        # Get first accessible node
        method = 'ssh'
        user = 'root'
        if not node and self.access_config:
            for n, info in self.access_config.nodes.items():
                if info.get('preferred_method'):
                    node = n
                    method = info.get('preferred_method', 'ssh')
                    user = info.get('ssh_user', 'root')
                    break

        if not node:
            print("\n[WARNING] No accessible nodes found. Showing full guide.")
            print_suggestions('install')
            return

        if method == 'local':
            print("  Checking: LOCAL execution (this machine)")
        else:
            print(f"  Checking: {node} via {method.upper()} (user={user})")
        status = self.check_install_status(node, method, user)

        # Print status summary
        print("\n" + "-" * 63)
        print(" Current Installation Status")
        print("-" * 63)

        def status_icon(val):
            if val is None:
                return "[?]"
            return "[OK]" if val else "[--]"

        # Phase 1: Prerequisites
        print("\n  PHASE 1 - PREREQUISITES:")
        print(f"    {status_icon(status['subscription_registered'])} Subscription/repos available")
        print(f"    {status_icon(status['firewall_configured'])} Firewall ports open (high-availability)")
        print(f"    {status_icon(status['packages_installed'])} Cluster packages installed")
        if status['missing_packages']:
            print(f"        Missing: {', '.join(status['missing_packages'])}")
        print(f"    {status_icon(status['hacluster_password'])} hacluster user password set")
        print(f"    {status_icon(status['pcsd_running'])} PCSD daemon running")
        print(f"    {status_icon(status['pcsd_enabled'])} PCSD enabled on boot")

        # Phase 2: Cluster Creation
        print("\n  PHASE 2 - CLUSTER CREATION:")
        print(f"    {status_icon(status['nodes_authenticated'])} Nodes authenticated (pcs host auth)")
        cluster_info = f" ({status['cluster_name']})" if status['cluster_name'] else ""
        print(f"    {status_icon(status.get('corosync_conf_exists'))} Cluster created (corosync.conf)")
        print(f"    {status_icon(status.get('cib_exists'))} Cluster configured (cib.xml)")
        print(f"    {status_icon(status['cluster_configured'])} Cluster running{cluster_info}")
        print(f"    {status_icon(status['corosync_running'])} Corosync running (messaging)")
        print(f"    {status_icon(status['pacemaker_running'])} Pacemaker running (resource mgr)")
        # Cluster enabled on boot is optional - show warning if not enabled
        if status['cluster_enabled']:
            print(f"    {status_icon(True)} Cluster enabled on boot")
        elif status['cluster_enabled'] is False:
            print("    [~] Cluster enabled on boot (optional)")
        else:
            print("    [?] Cluster enabled on boot (optional)")
        print(f"    {status_icon(status['cluster_online'])} All nodes online")
        if status['cluster_nodes']:
            print(f"        Online: {', '.join(status['cluster_nodes'])}")
        if status.get('offline_nodes'):
            print(f"        Offline: {', '.join(status['offline_nodes'])}")

        # Warning if cluster is configured but not running
        if (status.get('corosync_conf_exists') or status.get('cib_exists')) and not status['pacemaker_running']:
            print("""
  ╔═════════════════════════════════════════════════════════════╗
  ║  [!] CLUSTER NOT RUNNING                                    ║
  ╠═════════════════════════════════════════════════════════════╣
  ║  Run:  pcs cluster start --all                              ║
  ╚═════════════════════════════════════════════════════════════╝""")

        # Phase 3: Fencing & Resources
        print("\n  PHASE 3 - FENCING & RESOURCES:")
        print(f"    {status_icon(status['stonith_enabled'])} STONITH enabled")
        print(f"    {status_icon(status['stonith_configured'])} STONITH device running")
        print(f"    {status_icon(status['hana_installed'])} SAP HANA installed")
        print(f"    {status_icon(status['hana_resources'])} SAP HANA cluster resources")

        # Determine what steps are needed based on phases
        steps_needed = []

        # If cluster is running, prerequisites must have been completed
        cluster_running = status['cluster_configured'] or status['pacemaker_running']

        # Phase 1: Prerequisites - skip if cluster is already running
        if not cluster_running:
            if status['subscription_registered'] is False:
                steps_needed.append('subscription')
            if status['firewall_configured'] is False:
                steps_needed.append('firewall')
            if status['packages_installed'] is False:
                steps_needed.append('packages')
            if status['hacluster_password'] is False:
                steps_needed.append('hacluster')
            if status['pcsd_running'] is False:
                steps_needed.append('pcsd')

        # Phase 2: Cluster Creation - skip auth/setup if cluster already exists
        if not cluster_running:
            if status['pcsd_running'] and status['nodes_authenticated'] is False:
                steps_needed.append('authenticate')
            if status['nodes_authenticated'] and not status['cluster_configured']:
                steps_needed.append('cluster_setup')
        if status['cluster_configured'] and not status['corosync_running']:
            steps_needed.append('cluster_start')
        # Note: cluster_enable is optional - cluster works without being enabled on boot

        # Phase 3: Fencing & Resources
        if status['cluster_online'] and status['stonith_enabled'] is False:
            steps_needed.append('stonith')
        if status['hana_installed'] and status['hana_resources'] is False:
            steps_needed.append('hana')

        if not steps_needed:
            print("\n" + "=" * 63)
            print(" All installation steps completed!")
            print("=" * 63)
            print("\n  Run health check to verify configuration:")
            print("    ./cluster_health_check.py")
            return

        # Determine the immediate next step
        next_step = steps_needed[0] if steps_needed else None

        # Print summary and next step with prominent separator
        print("\n")
        print("=" * 63)
        print("=" * 63)
        print(f" NEXT STEP: {next_step.upper().replace('_', ' ') if next_step else 'DONE'}")
        print("=" * 63)
        print("=" * 63)

        # Print only the needed steps
        print(f"\n  Remaining steps ({len(steps_needed)}): {', '.join(steps_needed)}")

        step_num = 1

        if 'subscription' in steps_needed:
            print(f"""
STEP {step_num}: REGISTER SUBSCRIPTION (both nodes)
---------------------------------------------------------------
  # Register system and attach SAP subscription
  subscription-manager register
  subscription-manager attach --pool=<SAP_POOL_ID>

  # Enable High Availability repository (RHEL 9)
  subscription-manager repos --enable=rhel-9-for-x86_64-highavailability-rpms
""")
            step_num += 1

        if 'firewall' in steps_needed:
            print(f"""
STEP {step_num}: CONFIGURE FIREWALL (both nodes)
---------------------------------------------------------------
  # Allow High Availability traffic through the firewall
  firewall-cmd --permanent --add-service=high-availability
  firewall-cmd --reload

  # Verify
  firewall-cmd --list-services | grep high-availability
""")
            step_num += 1

        if 'packages' in steps_needed:
            missing = status['missing_packages']
            pkg_list = ' '.join(missing) if missing else 'pacemaker pcs fence-agents-all sap-hana-ha'
            print(f"""
STEP {step_num}: INSTALL CLUSTER PACKAGES (both nodes)
---------------------------------------------------------------
  # Install required packages
  dnf install -y {pkg_list}

  # SAP resource agent package (install ONE):
  dnf install -y sap-hana-ha  # RHEL 9/10, Scale-Up & Scale-Out (required for RHEL 10)
  # Legacy alternatives (RHEL 8/9 only):
  #   dnf install -y resource-agents-sap-hana           # legacy Scale-Up
  #   dnf install -y resource-agents-sap-hana-scaleout  # legacy Scale-Out

  # Verify installation
  rpm -q pacemaker corosync pcs sap-hana-ha
""")
            step_num += 1

        if 'hacluster' in steps_needed:
            print(f"""
STEP {step_num}: SET HACLUSTER PASSWORD (both nodes)
---------------------------------------------------------------
  # Set password for hacluster user (use SAME password on all nodes)
  passwd hacluster

  # Verify the user exists
  id hacluster
""")
            step_num += 1

        if 'pcsd' in steps_needed:
            print(f"""
STEP {step_num}: START PCSD DAEMON (both nodes)
---------------------------------------------------------------
  # Enable and start pcsd service
  systemctl enable --now pcsd.service

  # Verify pcsd is running
  systemctl status pcsd
""")
            step_num += 1

        if 'authenticate' in steps_needed:
            print(f"""
STEP {step_num}: AUTHENTICATE NODES (one node only)
---------------------------------------------------------------
  # Authenticate cluster nodes (RHEL 9 syntax: pcs host auth)
  pcs host auth node1 node2 -u hacluster

  # Enter the hacluster password when prompted
  # This creates /etc/corosync/corosync.conf on successful auth
""")
            step_num += 1

        if 'cluster_setup' in steps_needed:
            print(f"""
STEP {step_num}: CREATE CLUSTER (one node only)
---------------------------------------------------------------
  # Create the cluster (replace my_cluster with your cluster name)
  pcs cluster setup my_cluster node1 node2

  # This generates /etc/corosync/corosync.conf on all nodes
""")
            step_num += 1

        if 'cluster_start' in steps_needed:
            print(f"""
STEP {step_num}: START CLUSTER (one node only)
---------------------------------------------------------------
  NOTE: If 'pcs status' shows "Connection to cluster failed: Connection
        refused" - the cluster needs to be STARTED or CREATED first!

  # Start the cluster on all nodes
  pcs cluster start --all

  # Verify cluster is running
  pcs cluster status
  pcs status

  # If cluster doesn't exist yet, create it first:
  pcs cluster setup <cluster_name> <node1> <node2>

  # Monitor in real-time
  watch pcs status
""")
            step_num += 1

        if 'cluster_enable' in steps_needed:
            print(f"""
STEP {step_num}: ENABLE CLUSTER ON BOOT (one node only)
---------------------------------------------------------------
  # Enable cluster to start automatically on boot
  pcs cluster enable --all

  # Verify
  systemctl is-enabled corosync pacemaker
""")
            step_num += 1

        if 'stonith' in steps_needed:
            print(f"""
STEP {step_num}: CONFIGURE STONITH/FENCING (one node only)
---------------------------------------------------------------

  OPTION A: Production cluster - Configure real STONITH device
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  IMPORTANT: STONITH is REQUIRED for production SAP HANA clusters!

  # Example: IPMI/iLO fencing
  pcs stonith create fence_node1 fence_ipmilan \\
      ipaddr=<IPMI_IP> login=<USER> passwd=<PASS> \\
      lanplus=1 pcmk_host_list=node1

  # Example: Cloud fencing (Azure)
  pcs stonith create fence_azure fence_azure_arm ...

  # Verify fencing
  pcs stonith status

  OPTION B: Test/Dev cluster - Disable STONITH (NOT for production!)
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  # Disable STONITH for non-production/test clusters only
  sudo pcs property set stonith-enabled=false

  # Verify STONITH is disabled
  pcs property show stonith-enabled

  # To re-enable STONITH later (before going to production):
  sudo pcs property set stonith-enabled=true
""")
            step_num += 1

        if 'hana' in steps_needed:
            print(f"""
STEP {step_num}: CONFIGURE SAP HANA RESOURCES (one node only)
---------------------------------------------------------------
  # Ensure HANA System Replication is configured first!
  # Run as <sid>adm: hdbnsutil -sr_state

  # Create SAPHanaTopology resource
  pcs resource create SAPHanaTopology_<SID>_<INST> SAPHanaTopology \\
      SID=<SID> InstanceNumber=<INST> \\
      op start timeout=600 op stop timeout=300 op monitor interval=10 timeout=600 \\
      clone clone-max=2 clone-node-max=1 interleave=true

  # Create SAPHana resource
  pcs resource create SAPHana_<SID>_<INST> SAPHana \\
      SID=<SID> InstanceNumber=<INST> \\
      PREFER_SITE_TAKEOVER=true DUPLICATE_PRIMARY_TIMEOUT=7200 AUTOMATED_REGISTER=true \\
      op start timeout=3600 op stop timeout=3600 \\
      op monitor interval=61 role=Slave timeout=700 \\
      op monitor interval=59 role=Master timeout=700 \\
      op promote timeout=3600 op demote timeout=3600 \\
      promotable meta notify=true clone-max=2 clone-node-max=1 interleave=true

  # Create virtual IP
  pcs resource create vip_<SID>_<INST> IPaddr2 ip=<VIP> cidr_netmask=24 \\
      op monitor interval=10 timeout=20

  # Add constraints
  pcs constraint colocation add vip_<SID>_<INST> with master SAPHana_<SID>_<INST>-clone 4000
  pcs constraint order SAPHanaTopology_<SID>_<INST>-clone then SAPHana_<SID>_<INST>-clone
""")
            step_num += 1

        print("-" * 63)
        print(" After completing these steps, rerun the health check:")
        print("   ./cluster_health_check.py")
        print("-" * 63)

    def print_banner(self):
        """Print the tool banner."""
        print("""
╔═══════════════════════════════════════════════════════════════╗
║       SAP Pacemaker Cluster Health Check Tool                 ║
║       Red Hat Enterprise Linux (RHEL 8/9/10)                  ║
╠───────────────────────────────────────────────────────────────╣
║  -h help | -i install guide | -G usage guide | --suggest tips ║
╚═══════════════════════════════════════════════════════════════╝
""")
        if self.debug:
            print("=" * 63)
            print(" DEBUG MODE ENABLED - Configuration Files")
            print("=" * 63)
            print(f"  Config directory:    {self.config_dir}")
            print(f"  Access config file:  {self.config_dir / AccessDiscovery.CONFIG_FILE}")
            print(f"  Rules path:          {self.rules_path}")
            print(f"  Strict mode:         {self.strict_mode}")
            print(f"  Local mode:          {self.local_mode}")
            print(f"  Hosts file:          {self.hosts_file or '(auto-discover from Ansible)'}")
            print(f"  SOSreport dir:       {self.sosreport_dir or '(not set)'}")
            print(f"  Workers:             {self.workers}")
            print()

    def step_access_discovery(self, force: bool = False) -> bool:
        """
        Step 1: Discover and validate access to cluster nodes.
        Returns True if at least one node is accessible.
        """
        print("\n" + "=" * 63)
        print(" STEP 1: Access Discovery")
        print("=" * 63)

        self._debug_print("Starting access discovery...")
        self._debug_print(f"Config file: {self.config_dir / AccessDiscovery.CONFIG_FILE}")
        self._debug_print(f"Force rediscover: {force}")

        discovery = AccessDiscovery(
            config_dir=str(self.config_dir),
            sosreport_dir=self.sosreport_dir,
            hosts_file=self.hosts_file,
            force_rediscover=force,
            debug=self.debug,
            ansible_group=self.ansible_group,
            skip_ansible=self.skip_ansible,
            cluster_name=self.cluster_name,
            local_mode=self.local_mode
        )
        discovery.MAX_WORKERS = self.workers

        self._debug_print(f"Hosts file: {self.hosts_file or 'auto-discover'}")
        self._debug_print(f"SOSreport dir: {self.sosreport_dir or 'not set'}")

        self.access_config = discovery.discover_all()

        self._debug_print(f"Discovery complete, found {len(self.access_config.nodes)} node(s)")

        # Check if we have any accessible nodes
        accessible_nodes = [
            node for node in self.access_config.nodes.values()
            if node.get('preferred_method')
        ]

        if not accessible_nodes:
            print("\n[ERROR] No accessible nodes found!")
            print("Please ensure at least one of the following:")
            print("  - SSH access to cluster nodes")
            print("  - Valid Ansible inventory with reachable hosts")
            print("  - SOSreport directory with extracted reports")
            return False

        # Show cluster and nodes summary
        node_names = list(self.access_config.nodes.keys())
        cluster_name = None
        for cname, cinfo in self.access_config.clusters.items():
            if any(n in node_names for n in cinfo.get('nodes', [])):
                cluster_name = cname
                break

        print("\n" + "-" * 63)
        if cluster_name:
            print(f"  Cluster:  {cluster_name}")
        print(f"  Nodes:    {', '.join(sorted(node_names))}")
        print("-" * 63)
        print(f"\n[OK] {len(accessible_nodes)} node(s) accessible for health checks")
        return True

    def _load_rules_engine(self):
        """Initialize and load the rules engine."""
        if self.rules_engine is None:
            self._debug_print(f"Loading rules engine from: {self.rules_path}")
            access_dict = asdict(self.access_config) if self.access_config else {}
            self.rules_engine = RulesEngine(
                rules_path=self.rules_path,
                access_config=access_dict,
                strict_mode=self.strict_mode
            )
            self.rules_engine.load_rules()
            self._debug_print(f"Loaded {len(self.rules_engine.rules)} rules")
            if not self.strict_mode:
                optional_count = sum(1 for r in self.rules_engine.rules if r.optional)
                if optional_count > 0:
                    self._debug_print(f"Non-strict mode: {optional_count} optional checks will be warnings")

    def _run_rules_parallel(self, rules: list, nodes: dict) -> list:
        """Run multiple rules in parallel using thread pool."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_results = []
        max_parallel_rules = min(len(rules), 4)  # Max 4 rules in parallel

        with ThreadPoolExecutor(max_workers=max_parallel_rules) as executor:
            futures = {}
            for rule in rules:
                future = executor.submit(self.rules_engine.run_check, rule, nodes)
                futures[future] = rule.check_id

            for future in as_completed(futures):
                check_id = futures[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                    self._debug_print(f"Completed: {check_id} ({len(results)} results)")
                except Exception as e:
                    self._debug_print(f"Error in {check_id}: {e}")

        return all_results

    def _filter_rules_by_prefix(self, prefixes: list) -> list:
        """Filter loaded rules by check_id prefix."""
        return [r for r in self.rules_engine.rules
                if any(r.check_id.startswith(p) for p in prefixes)]

    def step_cluster_config_check(self) -> bool:
        """
        Step 2: Check cluster configuration.
        Runs: CHK_NODE_STATUS, CHK_CLUSTER_QUORUM, CHK_QUORUM_CONFIG,
              CHK_CLONE_CONFIG, CHK_SETUP_VALIDATION
        """
        print("\n" + "=" * 63)
        print(" STEP 2: Cluster Configuration Check")
        print("=" * 63)

        self._debug_print("Starting cluster configuration checks...")
        self._load_rules_engine()

        # Filter relevant checks
        config_checks = ['CHK_NODE_STATUS', 'CHK_CLUSTER_QUORUM', 'CHK_QUORUM_CONFIG',
                        'CHK_CLONE_CONFIG', 'CHK_SETUP_VALIDATION', 'CHK_CIB_TIME_SYNC',
                        'CHK_PACKAGE_CONSISTENCY', 'CHK_CLUSTER_TYPE']

        rules_to_run = [r for r in self.rules_engine.rules if r.check_id in config_checks]

        self._debug_print(f"Checks to run: {[r.check_id for r in rules_to_run]}")

        if not rules_to_run:
            print("[SKIP] No cluster configuration checks found")
            return True

        nodes = self.access_config.nodes if self.access_config else {}
        self._debug_print(f"Target nodes: {list(nodes.keys())}")

        # Run rules in parallel with spinner
        with Spinner(f"Running {len(rules_to_run)} cluster configuration checks"):
            results = self._run_rules_parallel(rules_to_run, nodes)
        self.check_results.extend(results)
        print(f"  Completed {len(rules_to_run)} cluster configuration checks")

        failed = [r for r in self.check_results if r.status == CheckStatus.FAILED
                  and r.check_id in config_checks]
        return len([f for f in failed if f.severity == Severity.CRITICAL]) == 0

    def _extract_hana_resource_state(self, results: list) -> str:
        """Extract HANA resource state from CHK_RESOURCE_STATUS results.

        Checks parsed 'hana_resource_state' first (live_cmd emits this),
        then falls back to inferring from individual regex matches (SOSreport).
        """
        resource_status_result = next(
            (r for r in results if r.check_id == 'CHK_RESOURCE_STATUS'), None
        )
        if not resource_status_result or not resource_status_result.details:
            return 'unknown'

        parsed = resource_status_result.details.get('parsed', {})

        # Primary: use the explicit state summary (from live_cmd)
        state = parsed.get('hana_resource_state')
        if state and state != 'unknown':
            return state

        # Fallback: infer from individual regex matches (SOSreport data)
        has_resource = parsed.get('sap_hana_resource') is not None
        if not has_resource:
            return 'absent'
        if parsed.get('resource_unmanaged') is not None:
            return 'unmanaged'
        if parsed.get('resource_disabled') is not None:
            return 'disabled'
        if parsed.get('resource_started') is not None:
            return 'running'
        if parsed.get('resource_stopped') is not None:
            return 'stopped'
        return 'unknown'

    def step_pacemaker_check(self) -> bool:
        """
        Step 3: Check Pacemaker/Corosync status.

        Runs in two phases:
        Phase 1: Resource-independent checks (STONITH, resource status, failures, etc.)
        Phase 2: Resource-dependent checks (master/slave roles) - skipped if HANA
                 resource is stopped/disabled/unmanaged.
        """
        print("\n" + "=" * 63)
        print(" STEP 3: Pacemaker/Corosync Check")
        print("=" * 63)

        self._debug_print("Starting Pacemaker/Corosync checks...")
        self._load_rules_engine()

        all_pacemaker_checks = ['CHK_STONITH_CONFIG', 'CHK_RESOURCE_STATUS', 'CHK_RESOURCE_FAILURES',
                                'CHK_ALERT_FENCING', 'CHK_MASTER_SLAVE_ROLES', 'CHK_MAJORITY_MAKER']

        nodes = self.access_config.nodes if self.access_config else {}
        self._debug_print(f"Target nodes: {list(nodes.keys())}")

        # Phase 1: Run resource-independent checks first
        independent_checks = ['CHK_STONITH_CONFIG', 'CHK_RESOURCE_STATUS', 'CHK_RESOURCE_FAILURES',
                              'CHK_ALERT_FENCING', 'CHK_MAJORITY_MAKER']
        independent_rules = [r for r in self.rules_engine.rules if r.check_id in independent_checks]

        self._debug_print(f"Phase 1 checks: {[r.check_id for r in independent_rules]}")

        if not independent_rules:
            print("[SKIP] No Pacemaker checks found")
            return True

        with Spinner(f"Running {len(independent_rules)} Pacemaker/Corosync checks"):
            results = self._run_rules_parallel(independent_rules, nodes)
        self.check_results.extend(results)

        # Extract HANA resource state from CHK_RESOURCE_STATUS
        self._hana_resource_state = self._extract_hana_resource_state(results)
        self._debug_print(f"HANA resource state: {self._hana_resource_state}")
        if self.rules_engine:
            self.rules_engine.set_hana_resource_state(self._hana_resource_state)

        # Phase 2: Resource-dependent checks
        resource_dependent_checks = ['CHK_MASTER_SLAVE_ROLES']

        if self._hana_resource_state == 'running':
            dependent_rules = [r for r in self.rules_engine.rules
                               if r.check_id in resource_dependent_checks]
            if dependent_rules:
                self._debug_print(f"Phase 2 checks: {[r.check_id for r in dependent_rules]}")
                with Spinner("Running resource-dependent checks"):
                    dep_results = self._run_rules_parallel(dependent_rules, nodes)
                self.check_results.extend(dep_results)
                results.extend(dep_results)
        else:
            # Skip resource-dependent checks with WARNING
            for check_id in resource_dependent_checks:
                rule = next((r for r in self.rules_engine.rules if r.check_id == check_id), None)
                if rule:
                    skip_msg = f"Skipped: HANA resource is {self._hana_resource_state} (not managed by Pacemaker)"
                    self.check_results.append(CheckResult(
                        check_id=check_id,
                        description=rule.description,
                        status=CheckStatus.SKIPPED,
                        severity=Severity.WARNING,
                        message=skip_msg,
                        node="all"
                    ))
            print(f"  [WARN] HANA resource is {self._hana_resource_state}"
                  " - skipping master/slave role check")

        print(f"  Completed Pacemaker/Corosync checks")

        failed = [r for r in self.check_results if r.status == CheckStatus.FAILED
                  and r.check_id in all_pacemaker_checks]
        return len([f for f in failed if f.severity == Severity.CRITICAL]) == 0

    def step_sap_check(self) -> bool:
        """
        Step 4: SAP-specific checks.
        First checks if HANA is installed, then runs other SAP checks.
        """
        print("\n" + "=" * 63)
        print(" STEP 4: SAP-Specific Checks")
        print("=" * 63)

        self._debug_print("Starting SAP-specific checks...")
        self._load_rules_engine()

        nodes = self.access_config.nodes if self.access_config else {}
        self._debug_print(f"Target nodes: {list(nodes.keys())}")

        # First check if HANA is installed
        hana_installed_rule = next(
            (r for r in self.rules_engine.rules if r.check_id == 'CHK_HANA_INSTALLED'),
            None
        )

        hana_installed = False
        nodes_with_hana = []
        if hana_installed_rule:
            print("Checking if SAP HANA is installed...")
            install_results = self._run_rules_parallel([hana_installed_rule], nodes)
            self.check_results.extend(install_results)

            # Track which nodes have HANA (Scale-Out clusters may have majority makers without HANA)
            nodes_with_hana = [r.node for r in install_results if r.status == CheckStatus.PASSED]
            nodes_without_hana = [r.node for r in install_results if r.status != CheckStatus.PASSED]

            # HANA is installed if at least one node has it
            hana_installed = len(nodes_with_hana) > 0

            self._debug_print(f"HANA install check results: {[(r.node, str(r.status)) for r in install_results]}")
            self._debug_print(f"Nodes with HANA: {nodes_with_hana}, Nodes without: {nodes_without_hana}")
            self._debug_print(f"HANA installed: {hana_installed}")

            # Check which nodes are excluded from HANA by constraints
            # These nodes don't run HANA (app servers in Scale-Up, majority makers in Scale-Out)
            hana_excluded_nodes = set()
            if self.rules_engine:
                resource_config = self.rules_engine.get_cluster_resources_config()
                if resource_config.get('available'):
                    excluded = resource_config.get('hana_excluded_node')
                    if excluded:
                        hana_excluded_nodes.add(excluded)

            # Update CHK_HANA_INSTALLED results for constraint-excluded nodes
            if nodes_without_hana and hana_excluded_nodes:
                excluded_without_hana = [n for n in nodes_without_hana if n in hana_excluded_nodes]
                other_without_hana = [n for n in nodes_without_hana if n not in hana_excluded_nodes]

                for node_name in excluded_without_hana:
                    # Mark CHK_HANA_INSTALLED as SKIPPED (not ERROR) for excluded nodes
                    for result in self.check_results:
                        if result.check_id == 'CHK_HANA_INSTALLED' and result.node == node_name:
                            result.status = CheckStatus.SKIPPED
                            result.message = "Node excluded from HANA resources by constraints"
                            break

                if excluded_without_hana:
                    print(f"[OK] Nodes excluded from HANA by constraints: {', '.join(excluded_without_hana)}")
                if other_without_hana:
                    print(f"[INFO] Nodes without HANA: {', '.join(other_without_hana)}")
            elif nodes_without_hana:
                print(f"[INFO] Nodes without HANA: {', '.join(nodes_without_hana)}")

            # After majority maker check, if no HANA installed, skip SAP checks
            if not hana_installed:
                print("[SKIP] SAP HANA not installed - skipping HANA-specific checks")
                # Add skipped results for other SAP checks
                sap_checks_skip = ['CHK_HANA_SR_STATUS', 'CHK_REPLICATION_MODE', 'CHK_HADR_HOOKS',
                                   'CHK_HANA_AUTOSTART', 'CHK_SYSTEMD_SAP', 'CHK_SITE_ROLES']
                for check_id in sap_checks_skip:
                    rule = next((r for r in self.rules_engine.rules if r.check_id == check_id), None)
                    if rule:
                        self.check_results.append(CheckResult(
                            check_id=check_id,
                            description=rule.description if rule else check_id,
                            status=CheckStatus.SKIPPED,
                            severity=Severity.INFO,
                            message="SAP HANA not installed",
                            node="all"
                        ))
                return True

        # HANA is installed on some nodes, run SAP checks only on those nodes
        # Filter nodes to only those with HANA installed
        hana_nodes = {k: v for k, v in nodes.items() if k in nodes_with_hana} if nodes_with_hana else nodes

        hana_resource_active = self._hana_resource_state == 'running'

        # Split SAP checks based on resource state
        # Resource-dependent: require HANA resource active in Pacemaker
        resource_dependent_sap = ['CHK_HANA_SR_STATUS', 'CHK_SITE_ROLES']
        # Resource-independent: can run even if HANA resource is stopped/disabled
        resource_independent_sap = ['CHK_REPLICATION_MODE', 'CHK_HADR_HOOKS',
                                    'CHK_HANA_AUTOSTART', 'CHK_SYSTEMD_SAP']

        if hana_resource_active:
            # Normal path: run all SAP checks
            sap_checks = resource_dependent_sap + resource_independent_sap
            rules_to_run = [r for r in self.rules_engine.rules if r.check_id in sap_checks]
        else:
            # Resource stopped/disabled: skip dependent checks, run independent ones
            print(f"  [WARN] HANA resource is {self._hana_resource_state}"
                  " - skipping Pacemaker-dependent SAP checks")

            # Skip resource-dependent checks with WARNING
            for check_id in resource_dependent_sap:
                rule = next((r for r in self.rules_engine.rules if r.check_id == check_id), None)
                if rule:
                    self.check_results.append(CheckResult(
                        check_id=check_id,
                        description=rule.description,
                        status=CheckStatus.SKIPPED,
                        severity=Severity.WARNING,
                        message=f"Skipped: HANA resource is {self._hana_resource_state} in Pacemaker",
                        node="all"
                    ))

            sap_checks = resource_independent_sap
            rules_to_run = [r for r in self.rules_engine.rules if r.check_id in sap_checks]

        # Always gather HANA database status and replication info
        self._gather_hana_db_status(install_results, hana_nodes)

        self._debug_print(f"Checks to run: {[r.check_id for r in rules_to_run]}")

        if not rules_to_run:
            print("[SKIP] No SAP checks to run")
            return True

        # Run rules in parallel only on nodes with HANA
        with Spinner(f"Running {len(rules_to_run)} SAP-specific checks on {len(hana_nodes)} node(s)"):
            results = self._run_rules_parallel(rules_to_run, hana_nodes)
        self.check_results.extend(results)
        print(f"  Completed {len(rules_to_run)} SAP-specific checks")

        all_sap_checks = resource_dependent_sap + resource_independent_sap
        failed = [r for r in self.check_results if r.status == CheckStatus.FAILED
                  and r.check_id in all_sap_checks]
        return len([f for f in failed if f.severity == Severity.CRITICAL]) == 0

    def _gather_hana_db_status(self, install_results: list, hana_nodes: dict):
        """
        Gather comprehensive HANA database status and replication info.

        Determines:
        - Whether the HANA database is running on each node
        - Whether HANA is managed by the cluster (resource running) or not
        - Replication status via the appropriate source:
          * DB running + resource running: already gathered by CHK_HANA_SR_STATUS
          * DB running + resource stopped/disabled: hdbnsutil -sr_state (direct)
          * DB NOT running: SAPHanaSR-stateConfiguration (last known config from CIB)

        Results are stored in self._hana_db_status for report generation.
        """
        cluster_running = True
        if self.access_config and hasattr(self.access_config, 'clusters'):
            for cinfo in self.access_config.clusters.values():
                if cinfo.get('cluster_running') is False:
                    cluster_running = False
                    break

        hana_resource_active = self._hana_resource_state == 'running'

        # Determine HANA managed state:
        # Managed = cluster is running AND resource is started/running
        hana_managed = cluster_running and hana_resource_active

        # Find nodes where HANA is installed and their running status
        hana_running_nodes = []
        hana_stopped_nodes = []
        sidadm = None

        for result in install_results:
            if result.status != CheckStatus.PASSED or not result.details:
                continue
            parsed = result.details.get('parsed', {})
            node_sidadm = parsed.get('sidadm')
            if node_sidadm:
                sidadm = node_sidadm  # Keep last valid sidadm for offline queries

            if parsed.get('hana_running') == 'yes' and node_sidadm:
                hana_running_nodes.append({
                    'node': result.node,
                    'sidadm': node_sidadm,
                    'sid': parsed.get('sid'),
                })
            elif parsed.get('hana_installed') == 'HANA_INSTALLED':
                hana_stopped_nodes.append({
                    'node': result.node,
                    'sidadm': node_sidadm,
                    'sid': parsed.get('sid'),
                })

        db_running = len(hana_running_nodes) > 0
        running_nodes = [n['node'] for n in hana_running_nodes]
        stopped_nodes = [n['node'] for n in hana_stopped_nodes]

        # Store status for report generation
        self._hana_db_status = {
            'db_running': db_running,
            'hana_managed': hana_managed,
            'running_nodes': running_nodes,
            'stopped_nodes': stopped_nodes,
            'hana_resource_state': self._hana_resource_state,
            'sr_source': None,
            'sr_info': None,
        }

        if db_running:
            print(f"  [INFO] HANA database running on: {', '.join(running_nodes)}")
        else:
            print(f"  [INFO] HANA database NOT running on any node")

        if hana_managed:
            print(f"  [INFO] HANA is managed by the cluster (resource {self._hana_resource_state})")
            # Replication info already gathered by CHK_HANA_SR_STATUS
            self._hana_db_status['sr_source'] = 'Pacemaker (CHK_HANA_SR_STATUS)'
            return

        print(f"  [INFO] HANA is NOT managed by the cluster"
              f" (resource {self._hana_resource_state})")

        # --- Gather replication info based on DB running state ---

        if db_running:
            # DB running but resource not managed: query hdbnsutil directly
            self._query_hdbnsutil_replication(hana_running_nodes[0], hana_nodes)
        else:
            # DB not running: try SAPHanaSR-stateConfiguration for last known config
            self._query_sr_state_configuration(hana_nodes, sidadm)

    def _query_hdbnsutil_replication(self, node_info: dict, hana_nodes: dict):
        """Query replication status directly from a running HANA database via hdbnsutil."""
        sidadm = node_info['sidadm']
        node_name = node_info['node']

        # Validate sidadm to prevent command injection
        if not re.match(r'^[a-z0-9]+adm$', sidadm):
            self._debug_print(f"Invalid sidadm user: {sidadm}")
            return

        node_access = hana_nodes.get(node_name, {})
        method = node_access.get('preferred_method', 'ssh')
        user = node_access.get('ssh_user')

        sr_cmd = f"su - {sidadm} -c 'hdbnsutil -sr_state' 2>/dev/null"
        self._debug_print(f"Running: {sr_cmd} on {node_name}")

        success, output = self.rules_engine._execute_command_raw(sr_cmd, node_name, method, user)

        if success and output and output.strip():
            self._hana_db_status['sr_source'] = 'hdbnsutil -sr_state (direct query)'
            self._hana_db_status['sr_info'] = output.strip()

            # Add a CHK_HANA_SR_STATUS result with maintenance context
            self.check_results.append(CheckResult(
                check_id='CHK_HANA_SR_STATUS',
                description='HANA System Replication status (direct query - resource not managed)',
                status=CheckStatus.PASSED,
                severity=Severity.WARNING,
                message=(f"Replication info gathered directly from HANA (NOT via Pacemaker). "
                         f"HANA resource is {self._hana_resource_state}."),
                details={
                    'maintenance_mode': True,
                    'hana_resource_state': self._hana_resource_state,
                    'sr_state_output': output[:1000],
                    'source': 'hdbnsutil -sr_state',
                    'note': 'HANA is NOT managed by Pacemaker in this state'
                },
                node=node_name
            ))
            # Remove the SKIPPED result we added earlier for CHK_HANA_SR_STATUS
            # (only the one from resource gating, not from other skip reasons)
            self.check_results = [
                r for r in self.check_results
                if not (r.check_id == 'CHK_HANA_SR_STATUS'
                        and r.status == CheckStatus.SKIPPED
                        and 'HANA resource is' in (r.message or ''))
            ]
            print(f"  [OK] Replication status retrieved from {node_name} (via hdbnsutil)")
        else:
            self._debug_print(f"hdbnsutil query failed or returned empty output on {node_name}")

    def _query_sr_state_configuration(self, hana_nodes: dict, sidadm: str = None):
        """
        Query last known SR configuration when HANA database is NOT running.

        Tries in order:
        1. hdbnsutil -sr_stateConfiguration (works even when DB is down, requires sidadm)
        2. SAPHanaSR-stateConfiguration (ANGI/sap-hana-ha packages only, not on legacy Scale-Up)
        3. SAPHanaSR-showAttr (ANGI/sap-hana-ha packages only, not on legacy Scale-Up)
        4. crm_mon -A1 (works on all setups including legacy resource-agents-sap-hana)
        """
        # Try on any accessible node
        for node_name, node_access in hana_nodes.items():
            method = node_access.get('preferred_method', 'ssh')
            if not method:
                continue
            user = node_access.get('ssh_user')

            # 1. Try hdbnsutil -sr_stateConfiguration via sidadm (primary method)
            if sidadm and re.match(r'^[a-z0-9]+adm$', sidadm):
                sr_cmd = f"su - {sidadm} -c 'hdbnsutil -sr_stateConfiguration' 2>/dev/null"
                self._debug_print(f"Running: {sr_cmd} on {node_name}")

                success, output = self.rules_engine._execute_command_raw(
                    sr_cmd, node_name, method, user)

                if success and output and output.strip() and 'not found' not in output.lower():
                    self._hana_db_status['sr_source'] = 'hdbnsutil -sr_stateConfiguration'
                    self._hana_db_status['sr_info'] = output.strip()
                    print(f"  [OK] SR configuration retrieved via hdbnsutil on {node_name}")
                    return

            # 2. Try SAPHanaSR-stateConfiguration (ANGI packages only)
            sr_cmd = "SAPHanaSR-stateConfiguration 2>/dev/null"
            self._debug_print(f"Trying: {sr_cmd} on {node_name}")

            success, output = self.rules_engine._execute_command_raw(
                sr_cmd, node_name, method, user)

            if success and output and output.strip() and 'not found' not in output.lower():
                self._hana_db_status['sr_source'] = 'SAPHanaSR-stateConfiguration (CIB attributes)'
                self._hana_db_status['sr_info'] = output.strip()
                print(f"  [OK] SR configuration retrieved from CIB via {node_name}")
                return

            # 3. Try SAPHanaSR-showAttr (ANGI packages only)
            sr_cmd = "SAPHanaSR-showAttr 2>/dev/null"
            self._debug_print(f"Trying: {sr_cmd} on {node_name}")

            success, output = self.rules_engine._execute_command_raw(
                sr_cmd, node_name, method, user)

            if success and output and output.strip() and 'not found' not in output.lower():
                self._hana_db_status['sr_source'] = 'SAPHanaSR-showAttr (CIB attributes)'
                self._hana_db_status['sr_info'] = output.strip()
                print(f"  [OK] SR attributes retrieved from CIB via {node_name}")
                return

            # 4. Fallback for legacy Scale-Up (resource-agents-sap-hana):
            #    crm_mon -A1 shows node attributes including SR state from CIB
            sr_cmd = "crm_mon -A1 2>/dev/null | grep -iE 'hana|srmode|sync|site|sra|srah|lss|srr'"
            self._debug_print(f"Legacy fallback: crm_mon -A1 on {node_name}")

            success, output = self.rules_engine._execute_command_raw(
                sr_cmd, node_name, method, user)

            if success and output and output.strip():
                self._hana_db_status['sr_source'] = 'crm_mon -A1 (CIB node attributes)'
                self._hana_db_status['sr_info'] = output.strip()
                print(f"  [OK] SR attributes retrieved from CIB node attributes via {node_name}")
                return

        self._debug_print("Could not retrieve SR configuration from any node")

    def step_generate_report(self) -> bool:
        """
        Step 5: Generate final report.
        Summarizes all check results and optionally saves to file.
        """
        print("\n" + "=" * 63)
        print(" STEP 5: Health Check Report")
        print("=" * 63)

        self._debug_print("Generating report...")
        self._debug_print(f"Total results collected: {len(self.check_results)}")

        if not self.check_results:
            print("[INFO] No check results to report")
            return True

        # Summary statistics
        total = len(self.check_results)
        passed = len([r for r in self.check_results if r.status == CheckStatus.PASSED])
        failed = len([r for r in self.check_results if r.status == CheckStatus.FAILED])
        skipped = len([r for r in self.check_results if r.status == CheckStatus.SKIPPED])
        errors = len([r for r in self.check_results if r.status == CheckStatus.ERROR])

        critical_failures = [r for r in self.check_results
                            if r.status == CheckStatus.FAILED and r.severity == Severity.CRITICAL]
        warnings = [r for r in self.check_results
                   if r.status == CheckStatus.FAILED and r.severity == Severity.WARNING]

        print(f"\n  Total Checks Run:    {total}")
        print(f"  Passed:              {passed}")
        print(f"  Failed:              {failed}")
        print(f"    - Critical:        {len(critical_failures)}")
        print(f"    - Warning:         {len(warnings)}")
        print(f"  Skipped:             {skipped}")
        print(f"  Errors:              {errors}")

        if critical_failures:
            print("\n  CRITICAL FAILURES:")
            for r in critical_failures:
                node_str = f" ({r.node})" if r.node else ""
                print(f"    [CRIT] {r.check_id}{node_str}")
                print(f"           {r.message[:70]}")

        if warnings:
            print("\n  WARNINGS:")
            for r in warnings[:10]:
                node_str = f" ({r.node})" if r.node else ""
                print(f"    [WARN] {r.check_id}{node_str}: {r.message[:50]}")
            if len(warnings) > 10:
                print(f"    ... and {len(warnings) - 10} more warnings")

        # Build unified report data using single source of truth
        # Use pre-computed summary to avoid recalculating
        summary = {
            'total': total,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'errors': errors,
            'critical_count': len(critical_failures),
            'warning_count': len(warnings)
        }

        # Use cluster_name override if explicitly set
        cluster_name_override = self.cluster_name if self.cluster_name else None
        report_data = self._build_cluster_report_data(
            cluster_name=cluster_name_override,
            summary=summary
        )

        # Sanitize cluster name for filename
        cluster_name = report_data.cluster_name
        cluster_name_safe = "".join(c if c.isalnum() or c in '-_' else '_' for c in cluster_name)

        # Save unified report to YAML with format: YYYYMMDD_HHMMSS_clustername.yaml
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.config_dir / f"{timestamp}_{cluster_name_safe}.yaml"

        # Serialize unified data to YAML
        yaml_data = report_data.to_dict()
        with open(report_file, 'w') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

        print(f"\n  Report saved: {report_file}")

        # Generate PDF report if requested (fpdf2 availability checked at startup)
        if self.generate_pdf:
            try:
                from report_generator import generate_health_check_report

                # Use unified data for PDF generation
                cluster_info = report_data.to_cluster_info()
                results_dict = report_data.get_results_list()
                summary_dict = report_data.get_summary_dict()
                install_status = report_data.get_install_status()

                # PDF filename format: YYYYMMDD_health_check_report_clustername_HHMM.pdf
                pdf_timestamp = datetime.now().strftime('%Y%m%d')
                pdf_time = datetime.now().strftime('%H%M')
                pdf_file = self.config_dir / f"{pdf_timestamp}_health_check_report_{cluster_name_safe}_{pdf_time}.pdf"

                # Use spinner for PDF generation (can take a while in verbose mode)
                with Spinner("Generating PDF report"):
                    generate_health_check_report(
                        results_dict,
                        summary_dict,
                        cluster_info,
                        str(pdf_file),
                        install_status if install_status else None,
                        verbose=self.verbose_pdf
                    )
                print(f"  PDF report: {pdf_file}")
            except Exception as e:
                print(f"  [WARN] PDF generation failed: {e}")

        return len(critical_failures) == 0

    def run_all_checks(self, force_rediscover: bool = False,
                       skip_steps: list = None) -> int:
        """
        Run all health checks in sequence.
        Returns exit code (0 = success, non-zero = failure).
        """
        # Clear results from any previous run
        self.check_results = []

        self.print_banner()
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Config directory: {self.config_dir}")

        # Show what source is being used
        config_file = self.config_dir / AccessDiscovery.CONFIG_FILE
        if self.local_mode:
            print("Mode: LOCAL (running on cluster node)")
        elif self.sosreport_dir:
            print(f"Source: SOSreports from {self.sosreport_dir}")
        elif self.hosts_file:
            print(f"Source: Hosts file {self.hosts_file}")
        elif self.cluster_name:
            print(f"Source: Saved cluster '{self.cluster_name}'")
        elif config_file.exists():
            print("Source: Existing config (use -f to rediscover, -D to reset)")
        else:
            print("Source: Ansible inventory (auto-discovery)")

        print("-" * 63)
        print("To use different nodes:  ./cluster_health_check.py <node1> <node2>")
        print("To reset configuration:  ./cluster_health_check.py -D")
        print("-" * 63)

        skip_steps = skip_steps or []
        results = {}

        # Step 1: Access Discovery (required)
        if 'access' not in skip_steps:
            results['access'] = self.step_access_discovery(force=force_rediscover)
            if not results['access']:
                print("\n[ABORT] Cannot proceed without accessible nodes.")
                return 1

        # Step 2: Cluster Config Check
        if 'config' not in skip_steps:
            results['config'] = self.step_cluster_config_check()

        # Step 3: Pacemaker Check
        if 'pacemaker' not in skip_steps:
            results['pacemaker'] = self.step_pacemaker_check()

        # Step 4: SAP Check
        if 'sap' not in skip_steps:
            results['sap'] = self.step_sap_check()

        # Step 5: Generate Report
        if 'report' not in skip_steps:
            results['report'] = self.step_generate_report()

        # Final summary
        print("\n" + "=" * 63)
        print(" Health Check Complete")
        print("=" * 63)
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Show cluster and nodes info
        if self.access_config:
            nodes = list(self.access_config.nodes.keys())
            # Find cluster name from config
            cluster_name = None
            for cname, cinfo in self.access_config.clusters.items():
                if set(cinfo.get('nodes', [])) == set(nodes) or \
                   any(n in nodes for n in cinfo.get('nodes', [])):
                    cluster_name = cname
                    break

            if cluster_name:
                print(f"Cluster: {cluster_name}")
            print(f"Nodes checked: {', '.join(sorted(nodes))}")

            # Show detected cluster type from CHK_CLUSTER_TYPE
            if self.check_results:
                for r in self.check_results:
                    if hasattr(r, 'check_id') and r.check_id == 'CHK_CLUSTER_TYPE':
                        cluster_type = r.details.get('cluster_type', 'Unknown') if r.details else 'Unknown'
                        print(f"Cluster Type: {cluster_type}")
                        if r.message and 'configuration' in r.message:
                            print(f"  ({r.message})")
                        break

        # Show health check results summary
        if self.check_results:
            all_results = self.check_results
            passed = [r for r in all_results if hasattr(r, 'status') and str(r.status) == 'CheckStatus.PASSED']
            failed_checks = [r for r in all_results if hasattr(r, 'status') and str(r.status) == 'CheckStatus.FAILED']
            skipped = [r for r in all_results if hasattr(r, 'status') and str(r.status) == 'CheckStatus.SKIPPED']
            errors = [r for r in all_results if hasattr(r, 'status') and str(r.status) == 'CheckStatus.ERROR']

            print("\nHealth Check Results:")
            print(f"  PASSED:  {len(passed):3d}  FAILED: {len(failed_checks):3d}  SKIPPED: {len(skipped):3d}  ERROR: {len(errors):3d}")

            # Show data source information
            if self.rules_engine:
                data_source_info = self.rules_engine.get_data_source_info()
                data_source = data_source_info.get('description', '')
                if data_source:
                    print(f"\n  Data Source: {data_source}")

            # Show cluster configuration in verbose mode
            if self.verbose_pdf:
                config_file = self.config_dir / 'cluster_access_config.yaml'
                if config_file.exists():
                    # Get cluster name from access config
                    cluster_to_show = None
                    if self.access_config and hasattr(self.access_config, 'clusters'):
                        clusters = self.access_config.clusters
                        if clusters:
                            cluster_to_show = list(clusters.keys())[0]
                    print("\n" + "-" * 63)
                    print(" Cluster Configuration (verbose mode)")
                    print("-" * 63)
                    show_config(config_file, cluster_to_show, config_only=True)

            # Check for installation issues
            # Essential commands for RHEL clusters
            essential_commands = ['pacemaker', 'corosync', 'pcs', 'crm_mon']  # noqa: F841
            packages_missing = False
            commands_missing = []
            for r in all_results:
                msg = getattr(r, 'message', '') or ''
                if 'pacemaker package not found' in msg.lower() or 'corosync package not found' in msg.lower():
                    packages_missing = True
                if "command '" in msg.lower() and "not found" in msg.lower():
                    # Extract command name
                    match = re.search(r"command '(\w+)'", msg.lower())
                    if match:
                        cmd = match.group(1)
                        # Only track essential commands as missing
                        if cmd in essential_commands and cmd not in commands_missing:
                            commands_missing.append(cmd)

            if packages_missing or commands_missing:
                print()
                print("=" * 63)
                print(" INSTALLATION REQUIRED")
                print("=" * 63)
                if packages_missing:
                    print("  Cluster packages (pacemaker, corosync) are NOT installed!")
                if commands_missing:
                    print(f"  Missing commands: {', '.join(commands_missing)}")
                print()
                print("  To see installation steps, run:")
                print("    ./cluster_health_check.py -i")
                print("    ./cluster_health_check.py --suggest install")
                print("=" * 63)

            elif failed_checks:
                print()
                print("-" * 63)
                print(" Failed Checks (CRITICAL issues):")
                for r in failed_checks:
                    if hasattr(r, 'severity') and str(r.severity) == 'Severity.CRITICAL':
                        print(f"  - {r.check_id}: {r.message[:50]}...")
                print("-" * 63)

            else:
                # All checks passed - show healthy banner
                print()
                print("=" * 63)
                print("  ╔═══════════════════════════════════════════════════════╗")
                print("  ║                                                       ║")
                print("  ║            ✓  CLUSTER IS HEALTHY  ✓                   ║")
                print("  ║                                                       ║")
                print("  ║     All health checks passed successfully.            ║")
                print("  ║     Your SAP HANA cluster is properly configured.     ║")
                print("  ║                                                       ║")
                print("  ╚═══════════════════════════════════════════════════════╝")
                print("=" * 63)

                # Auto-generate PDF report on success (fpdf2 availability checked at startup)
                if self.generate_pdf:
                    try:
                        from report_generator import generate_health_check_report

                        # Use unified data model for PDF generation
                        report_data = self._build_cluster_report_data()
                        cluster_name = report_data.cluster_name
                        cluster_name_safe = re.sub(r'[^\w\-]', '_', cluster_name)

                        # Generate PDF with default name
                        pdf_timestamp = datetime.now().strftime('%Y%m%d')
                        pdf_time = datetime.now().strftime('%H%M')
                        pdf_file = self.config_dir / f"{pdf_timestamp}_health_check_report_{cluster_name_safe}_{pdf_time}.pdf"

                        # Use spinner for PDF generation
                        with Spinner("Generating PDF report"):
                            generate_health_check_report(
                                report_data.get_results_list(),
                                report_data.get_summary_dict(),
                                report_data.to_cluster_info(),
                                str(pdf_file),
                                report_data.get_install_status() or None,
                                verbose=self.verbose_pdf
                            )
                        self.last_pdf_file = pdf_file  # Track for auto-open
                        print(f"\n  PDF report saved: {pdf_file}")
                    except Exception as e:
                        print(f"\n  [WARN] PDF generation failed: {e}")

                # Cluster is healthy - exit early without showing extra output
                return 0

        # Show all steps with status and results (only when there are issues)
        print("\nSteps completed:")
        step_names = {
            'access': 'Access Discovery',
            'config': 'Cluster Configuration',
            'pacemaker': 'Pacemaker/Corosync',
            'sap': 'SAP HANA',
            'report': 'Report Generation'
        }

        # Map check IDs to steps for counting
        step_checks = {
            'config': ['CHK_NODE_STATUS', 'CHK_CLUSTER_QUORUM', 'CHK_QUORUM_CONFIG',
                      'CHK_CLONE_CONFIG', 'CHK_SETUP_VALIDATION', 'CHK_CIB_TIME_SYNC',
                      'CHK_PACKAGE_CONSISTENCY', 'CHK_CLUSTER_TYPE'],
            'pacemaker': ['CHK_STONITH_CONFIG', 'CHK_RESOURCE_STATUS', 'CHK_RESOURCE_FAILURES',
                         'CHK_ALERT_FENCING', 'CHK_MASTER_SLAVE_ROLES', 'CHK_MAJORITY_MAKER'],
            'sap': ['CHK_HANA_INSTALLED', 'CHK_HANA_SR_STATUS', 'CHK_REPLICATION_MODE', 'CHK_HADR_HOOKS',
                   'CHK_HANA_AUTOSTART', 'CHK_SYSTEMD_SAP', 'CHK_SITE_ROLES']
        }

        for step, success in results.items():
            name = step_names.get(step, step)

            # Get detailed results for this step
            if step == 'access':
                nodes = self.access_config.nodes if self.access_config else {}
                accessible = sum(1 for n in nodes.values() if n.get('preferred_method'))
                total = len(nodes)
                if accessible == total and total > 0:
                    print(f"  [{accessible}/{total}] {name}: PASSED")
                else:
                    print(f"  [{accessible}/{total}] {name}: {accessible} node(s) accessible")
            elif step in step_checks and self.check_results:
                check_ids = step_checks[step]
                step_results = [r for r in self.check_results if r.check_id in check_ids]
                passed = sum(1 for r in step_results if str(r.status) == 'CheckStatus.PASSED')
                failed = sum(1 for r in step_results if str(r.status) == 'CheckStatus.FAILED')
                skipped = sum(1 for r in step_results if str(r.status) == 'CheckStatus.SKIPPED')
                errors = sum(1 for r in step_results if str(r.status) == 'CheckStatus.ERROR')
                total = len(step_results)

                if self.debug:
                    print(f"  [DEBUG] {step}: {[(r.check_id, str(r.status), r.node) for r in step_results]}")

                # Show ratio and details
                if passed == total and total > 0:
                    print(f"  [{passed}/{total}] {name}: PASSED")
                else:
                    details = []
                    if failed:
                        details.append(f"{failed} failed")
                    if skipped:
                        details.append(f"{skipped} skipped")
                    if errors:
                        details.append(f"{errors} errors")
                    detail_str = f" ({', '.join(details)})" if details else ""
                    print(f"  [{passed}/{total}] {name}{detail_str}")
            elif step == 'report':
                status_icon = "[OK]" if success else "[FAIL]"
                print(f"  {status_icon} {name}")
            else:
                status_icon = "[OK]" if success else "[FAIL]"
                print(f"  {status_icon} {name}")

        failed = [step for step, success in results.items() if not success]
        if failed:
            print(f"\n[WARNING] Failed steps: {', '.join(failed)}")

        # Save step results for --suggest to use
        status_file = self.config_dir / "last_run_status.yaml"
        status_data = {
            'timestamp': datetime.now().isoformat(),
            'steps': {step: 'passed' if success else 'failed' for step, success in results.items()},
            'failed_steps': failed
        }
        with open(status_file, 'w') as f:
            yaml.dump(status_data, f, default_flow_style=False)

        # Check actual health check results
        has_failures = False
        has_skipped = False
        needs_install = False
        # Essential commands - if these are missing, installation is needed
        essential_commands = ['pacemaker', 'corosync', 'pcs', 'crm_mon']
        if self.check_results:
            for r in self.check_results:
                status = str(getattr(r, 'status', ''))
                msg = getattr(r, 'message', '') or ''
                if status == 'CheckStatus.FAILED':
                    has_failures = True
                if status == 'CheckStatus.SKIPPED':
                    has_skipped = True
                # Only trigger needs_install for essential package/command issues
                if 'pacemaker package not found' in msg.lower() or 'corosync package not found' in msg.lower():
                    needs_install = True
                elif "command '" in msg.lower() and "not found" in msg.lower():
                    match = re.search(r"command '(\w+)'", msg.lower())
                    if match and match.group(1) in essential_commands:
                        needs_install = True

        if failed:
            # Show hint about --suggest
            first_failed = failed[0]
            print(f"\n  Get help: ./cluster_health_check.py --suggest {first_failed}")
            print("  Or auto:  ./cluster_health_check.py --suggest")

        # Show next steps
        self._print_next_steps(results)

        # Final status and prompt
        if needs_install:
            print("\n" + "=" * 63)
            print(" [ACTION REQUIRED] Cluster packages not installed.")
            print("=" * 63)

            # Show first suggested commands
            print("\n  Quick start (run on cluster nodes):")
            print("    dnf install -y pacemaker pcs sap-hana-ha  # or resource-agents-sap-hana-scaleout")
            print("    systemctl enable --now pcsd")
            print("    ... (more steps required)")
            print("\n  For full guide: ./cluster_health_check.py -i")

            print("\nOptions:")
            print("  [Enter]  Rerun health check (monitor installation progress)")
            print("  [i]      Show installation guide")
            print("  [d]      Delete report files")
            print("  [q]      Quit")

            try:
                response = input("\nYour choice: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                response = 'q'
                print()

            while True:
                if response == '':
                    # Rerun health check
                    print("\n" + "=" * 63)
                    print(" Rerunning health check...")
                    print("=" * 63)
                    return self.run_all_checks(force_rediscover=False, skip_steps=[])
                elif response == 'i':
                    print()
                    self.print_dynamic_install_guide()
                elif response == 'd':
                    from access.discover_access import delete_config
                    delete_config(self.config_dir / AccessDiscovery.CONFIG_FILE)
                    print("  Restarting health check...\n")
                    # Restart without -D flag
                    new_argv = [arg for arg in sys.argv if arg not in ['-D', '--delete-reports']]
                    os.execv(sys.executable, [sys.executable] + new_argv)
                elif response == 'q':
                    break
                else:
                    print("Invalid option.")

                # Show options again
                print("\n" + "-" * 63)
                print("Options:")
                print("  [Enter]  Rerun health check")
                print("  [i]      Show installation guide")
                print("  [d]      Delete report files")
                print("  [q]      Quit")

                try:
                    response = input("\nYour choice: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    break

            return 2

        # Check installation progress
        install_complete = True
        steps_done = 0
        steps_total = 7
        missing_steps = []
        install_status = {}
        if not needs_install:
            try:
                install_status = self.check_install_status()
                steps_done = sum(1 for v in [
                    install_status.get('subscription_registered'),
                    install_status.get('repos_enabled'),
                    install_status.get('packages_installed'),
                    install_status.get('pcsd_running'),
                    install_status.get('cluster_configured'),
                    install_status.get('stonith_configured'),
                    install_status.get('hana_resources')
                ] if v)
                install_complete = (steps_done >= steps_total)

                # Build list of missing steps
                if not install_status.get('subscription_registered'):
                    missing_steps.append("subscription")
                if not install_status.get('repos_enabled'):
                    missing_steps.append("repos")
                if not install_status.get('packages_installed'):
                    missing_steps.append("packages")
                if not install_status.get('pcsd_running'):
                    missing_steps.append("pcsd")
                if not install_status.get('cluster_configured'):
                    missing_steps.append("cluster")
                if not install_status.get('stonith_configured'):
                    missing_steps.append("stonith")
                if not install_status.get('hana_resources'):
                    missing_steps.append("hana_resources")
            except Exception:
                pass

        # Determine overall status
        if failed or has_failures:
            if not install_complete:
                print(f"\n[WARNING] Installation incomplete ({steps_done}/{steps_total} steps) and health checks FAILED.")
                if missing_steps:
                    print(f"          Missing: {', '.join(missing_steps)}")
                print("          Run ./cluster_health_check.py -i to see remaining steps.")
            else:
                print("\n[WARNING] Some health checks FAILED. Review report for details.")
            return 1
        elif not install_complete:
            print(f"\n[INCOMPLETE] Installation in progress: {steps_done}/{steps_total} steps complete.")
            if missing_steps:
                print(f"             Missing: {', '.join(missing_steps)}")
            print("             Run ./cluster_health_check.py -i to see remaining steps.")
            return 2
        elif has_skipped:
            print("\n[INFO] Some checks were skipped (commands not available).")
            return 0
        else:
            print("\n[OK] All health checks passed! Cluster is fully configured.")
            return 0

    def _print_next_steps(self, results: dict):
        """Print suggested next steps based on results."""
        print("\n")
        print("=" * 63)
        print("=" * 63)
        print(" NEXT STEPS")
        print("=" * 63)
        print("=" * 63)

        # Check what was done and suggest next actions
        if not results.get('access'):
            print("""
  Access discovery failed. Try:
    ./cluster_health_check.py --debug hana01    # Debug with specific node
    ./cluster_health_check.py -s /path/to/sos   # Use SOSreports instead
""")
            return

        # Get results from rules engine if available
        all_results = self.check_results

        if all_results:
            # Analyze results
            critical = [r for r in all_results if hasattr(r, 'status') and
                       str(r.status) == 'CheckStatus.FAILED' and
                       hasattr(r, 'severity') and str(r.severity) == 'Severity.CRITICAL']
            warnings = [r for r in all_results if hasattr(r, 'status') and
                       str(r.status) == 'CheckStatus.FAILED' and
                       hasattr(r, 'severity') and str(r.severity) == 'Severity.WARNING']
            skipped = [r for r in all_results if hasattr(r, 'status') and
                      str(r.status) == 'CheckStatus.SKIPPED']

            # Check for essential package/command not found issues
            essential_commands = ['pacemaker', 'corosync', 'pcs', 'crm_mon']
            packages_missing = False
            essential_cmd_missing = False
            for r in all_results:
                msg = getattr(r, 'message', '') or ''
                if 'pacemaker package not found' in msg.lower() or 'corosync package not found' in msg.lower():
                    packages_missing = True
                if "command '" in msg.lower() and "not found" in msg.lower():
                    match = re.search(r"command '(\w+)'", msg.lower())
                    if match and match.group(1) in essential_commands:
                        essential_cmd_missing = True

            # Check for "cluster not running" scenario - many errors, packages installed
            errors = [r for r in all_results if hasattr(r, 'status') and
                     str(r.status) == 'CheckStatus.ERROR']
            cluster_not_running = False
            cluster_not_created = False
            install_status = None
            if len(errors) >= 3 and not packages_missing and not essential_cmd_missing:
                # Many errors with packages installed - check if cluster exists
                try:
                    install_status = self.check_install_status()
                    if not install_status.get('corosync_conf_exists') and not install_status.get('cib_exists'):
                        # Neither corosync.conf nor cib.xml exist - cluster not created
                        cluster_not_created = True
                    elif not install_status.get('pacemaker_running'):
                        # Cluster config exists (corosync.conf or cib.xml) but not running
                        cluster_not_running = True
                except Exception:
                    # Fallback - assume cluster might not be running
                    cluster_not_running = True

            if packages_missing or essential_cmd_missing:
                print("""
  INSTALLATION REQUIRED: Cluster packages not installed!
    Run: ./cluster_health_check.py --suggest install

    This will show step-by-step installation instructions for:
    - Pacemaker, Corosync, pcs
    - SAP HANA resource agents
    - Cluster setup and configuration
""")
            elif cluster_not_created:
                # Build list of missing steps only
                missing_steps = []
                if install_status:
                    if not install_status.get('hacluster_password'):
                        missing_steps.append("passwd hacluster")
                    if not install_status.get('pcsd_running'):
                        missing_steps.append("systemctl enable --now pcsd")
                    if not install_status.get('nodes_authenticated'):
                        missing_steps.append("pcs host auth <node1> <node2>")
                # These are always needed if cluster not created
                missing_steps.append("pcs cluster setup <name> <node1> <node2>")
                missing_steps.append("pcs cluster start --all")

                print("""
  ╔═══════════════════════════════════════════════════════════════╗
  ║  [!] CLUSTER NOT YET CREATED                                  ║
  ╠═══════════════════════════════════════════════════════════════╣
  ║                                                               ║
  ║  /etc/corosync/corosync.conf does not exist                  ║
  ║                                                               ║
  ║  ACTION REQUIRED:                                             ║
  ║  ─────────────────                                            ║""")
                for i, step in enumerate(missing_steps, 1):
                    print(f"  ║  {i}. {step:<55} ║")
                print("""  ║                                                               ║
  ║  Run ./cluster_health_check.py -i for detailed guide          ║
  ╚═══════════════════════════════════════════════════════════════╝
""")
            elif cluster_not_running:
                print("""
  ╔═══════════════════════════════════════════════════════════════╗
  ║  [!] CLUSTER NOT RUNNING                                      ║
  ╠═══════════════════════════════════════════════════════════════╣
  ║                                                               ║
  ║  Cluster exists but is not started                            ║
  ║                                                               ║
  ║  ACTION REQUIRED:                                             ║
  ║  ─────────────────                                            ║
  ║  Start the cluster:   pcs cluster start --all                 ║
  ║                                                               ║
  ╚═══════════════════════════════════════════════════════════════╝
""")
            elif critical:
                print(f"""
  CRITICAL issues found ({len(critical)}). Review:
    - Check the report file for details
    - Address STONITH/fencing issues first
    - Verify quorum configuration
""")

            if warnings and not packages_missing:
                print(f"  Warnings found ({len(warnings)}). Review report for details.")

            if skipped and not essential_cmd_missing:
                print(f"  Skipped checks ({len(skipped)}). Some commands may not be available.")

        print("""
  Common next steps:
    ./cluster_health_check.py --suggest install   # Installation guide
    ./cluster_health_check.py --show-config       # View all clusters config
    ./cluster_health_check.py -S mycluster        # View specific cluster config
    ./cluster_health_check.py -f hana01           # Force re-discovery
    ./cluster_health_check.py --list-rules        # List all health checks
    ./cluster_health_check.py --guide             # Show detailed usage guide
""")

        print("  Documentation:")
        print("    SAP HANA Admin:  https://help.sap.com/docs/SAP_HANA_PLATFORM")
        print("    SAP HANA SR:     https://help.sap.com/docs/SAP_HANA_PLATFORM/6b94445c94ae495c83a19646e7c3fd56")
        print("    Red Hat HA:      https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/configuring_and_managing_high_availability_clusters/")
        print("    Pacemaker:       https://clusterlabs.org/pacemaker/doc/")

        print("\n" + "-" * 63)
        print(" Quick: -h help | -i install | -G guide | --suggest | --list-steps")
        print("-" * 63)


# Note: print_guide(), print_steps(), print_suggestions(), interactive_startup(),
# run_usage_scan(), print_usage_help(), scan_for_resources(), extract_sosreports_parallel()
# are now imported from lib module


# Functions moved to lib/ modules:
# - print_guide, print_steps, print_suggestions (lib/installation.py)
# - interactive_startup, run_usage_scan, print_usage_help (lib/interactive.py)
# - scan_for_resources, extract_sosreports_parallel, check_for_updates (lib/utils.py)


# [Content removed - see lib/ modules]


def main():
    parser = argparse.ArgumentParser(
        description='SAP Pacemaker Cluster Health Check Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Run on cluster node (auto-detects local mode)
  %(prog)s --local                  Explicit local mode (on cluster node)
  %(prog)s hana03                   Auto-discover cluster from hana03 and check all members
  %(prog)s -C mycluster             Use previously discovered cluster 'mycluster'
  %(prog)s -d hana03                Same with debug output
  %(prog)s --access-only hana03     Only test access (discover cluster members)
  %(prog)s -g sap_cluster           Only check hosts in Ansible group 'sap_cluster'
  %(prog)s --show-config            Show all discovered clusters and nodes
  %(prog)s --show-config mycluster  Show config for specific cluster
  %(prog)s -S hana03                Show config for cluster containing hana03
  %(prog)s -H hosts.txt             Use custom hosts file
  %(prog)s -s /path/to/sosreports   Use SOSreport directory
  %(prog)s -v hana03                Verbose PDF - show all checks in detail (for audits)
  %(prog)s -i                        Show installation guide (shortcut)
  %(prog)s --suggest                Show suggestions for first failing step
  %(prog)s --suggest install        Show full installation guide
  %(prog)s --list-steps             List all steps with suggestion commands
        """
    )

    # Input sources
    parser.add_argument(
        'hosts',
        nargs='*',
        help='Hostname(s) to check (e.g., hana01 hana02)'
    )
    parser.add_argument(
        '--hosts-file', '-H',
        help='File containing list of hosts (one per line)'
    )
    parser.add_argument(
        '--sosreport-dir', '-s',
        help='Directory containing SOSreport archives/directories (default: ./sosreports)'
    )
    parser.add_argument(
        '--group', '-g',
        help='Only check hosts from this Ansible inventory group'
    )
    parser.add_argument(
        '--cluster', '-C',
        help='Use saved cluster by name (from previous discovery)'
    )
    parser.add_argument(
        '--config-dir', '-c',
        help='Directory to store configuration (default: ./)'
    )

    # Actions
    parser.add_argument(
        '--access-only', '-a',
        action='store_true',
        help='Only run access discovery step'
    )
    parser.add_argument(
        '--show-config', '-S',
        nargs='?',
        const=True,
        default=False,
        metavar='CLUSTER|NODE',
        help='Display configuration and exit. Optionally specify cluster name or hostname to show only that cluster.'
    )
    parser.add_argument(
        '--delete-reports', '-D',
        action='store_true',
        help='Delete report files (keeps node access config)'
    )
    parser.add_argument(
        '--export-ansible', '-E',
        nargs='+',
        metavar=('CLUSTER', 'OUTPUT_FILE'),
        help='Export cluster config as Ansible group_vars YAML. Usage: --export-ansible CLUSTER [output.yml]'
    )
    parser.add_argument(
        '--fetch-sosreports', '-F',
        nargs='*',
        metavar='CLUSTER_OR_NODE',
        help='Fetch SOSreports from cluster nodes via SCP. Prompts to create if missing. Usage: -F [CLUSTER|node1 node2...]'
    )
    parser.add_argument(
        '--create-sosreports',
        action='store_true',
        help='Auto-create SOSreports on nodes where missing (use with -F). Skips confirmation prompt.'
    )
    parser.add_argument(
        '--collect-sosreports', '-R',
        metavar='NODE',
        help='Collect SOSreports from cluster: discover nodes from NODE, configure SAP extensions, create and fetch SOSreports'
    )
    parser.add_argument(
        '--configure-extensions',
        action='store_true',
        default=None,
        help='Auto-configure SAP SOSreport extensions without prompting (use with -R)'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Force rediscovery (ignore existing config)'
    )

    # Performance
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=10,
        help='Number of parallel workers (default: 10)'
    )

    # Rules
    parser.add_argument(
        '--rules-path', '-r',
        help='Path to CHK_*.yaml rules directory (default: ./rules/health_checks)'
    )
    parser.add_argument(
        '--list-rules', '-L',
        action='store_true',
        help='List available health check rules and exit'
    )

    # Skip options
    parser.add_argument(
        '--skip',
        nargs='+',
        choices=['access', 'config', 'pacemaker', 'sap', 'report'],
        help='Skip specific steps'
    )

    # Debug option
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug mode (show config files used and step progress)'
    )

    # Strict mode option
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Strict mode: all checks required (fencing, alerts). Default: optional checks are warnings only'
    )

    # PDF report option (now default, kept for backwards compatibility)
    parser.add_argument(
        '--pdf',
        action='store_true',
        help='Generate PDF report (default: enabled, this flag is kept for compatibility)'
    )

    # No-PDF option to skip PDF generation
    parser.add_argument(
        '--no-pdf',
        action='store_true',
        help='Skip PDF report generation (useful if fpdf2 is not installed)'
    )

    # Verbose PDF option to show all checks in detail
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose PDF report - show all checks in detail (not just failed/warnings)'
    )

    # No-update-check option
    parser.add_argument(
        '--no-update-check',
        action='store_true',
        help='Skip checking for software updates'
    )

    # Local mode option
    parser.add_argument(
        '--local', '-l',
        action='store_true',
        help='Run on cluster node itself (execute commands locally instead of via SSH)'
    )

    # Guide option
    parser.add_argument(
        '--guide', '-G',
        action='store_true',
        help='Show detailed usage guide with examples and next steps'
    )

    # Install guide shortcut
    parser.add_argument(
        '--install', '-i',
        action='store_true',
        help='Show installation guide (shortcut for --suggest install)'
    )

    # Suggest option
    parser.add_argument(
        '--suggest',
        nargs='?',
        const='auto',
        choices=['access', 'config', 'pacemaker', 'sap', 'install', 'all', 'auto'],
        help='Show suggestions for a step (default: first failing step from last run)'
    )
    parser.add_argument(
        '--suggest-skip',
        nargs='+',
        choices=['access', 'config', 'pacemaker', 'sap', 'install'],
        help='Skip these steps when auto-suggesting (use with --suggest)'
    )

    # List steps option
    parser.add_argument(
        '--list-steps',
        action='store_true',
        help='List all health check steps with descriptions'
    )

    # Usage/scan option
    parser.add_argument(
        '--usage', '-u',
        action='store_true',
        help='Scan current directory for sosreports, inventory files, and former results; interactive setup'
    )

    args = parser.parse_args()

    # Check for software updates
    def check_for_updates():
        """Check if a newer version is available via git and offer to update."""
        try:
            import subprocess

            # Check if we're in a git repository
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return  # Not a git repo

            # Fetch latest from remote (quietly)
            subprocess.run(
                ['git', 'fetch', '--quiet'],
                cwd=SCRIPT_DIR,
                capture_output=True,
                timeout=30
            )

            # Get local and remote HEAD
            local_head = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=5
            ).stdout.strip()

            remote_head = subprocess.run(
                ['git', 'rev-parse', '@{u}'],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=5
            ).stdout.strip()

            if local_head != remote_head:
                # Check how many commits behind (remote has that we don't)
                behind_count = subprocess.run(
                    ['git', 'rev-list', '--count', f'{local_head}..{remote_head}'],
                    cwd=SCRIPT_DIR,
                    capture_output=True,
                    text=True,
                    timeout=5
                ).stdout.strip()

                # Only show update prompt if actually behind (not if ahead with local commits)
                try:
                    behind_int = int(behind_count)
                except ValueError:
                    behind_int = 0

                if behind_int > 0:
                    print(f"\n[INFO] A newer version is available ({behind_count} commit(s) behind)")
                    try:
                        response = input("  Update to latest version? [y/N]: ").strip().lower()
                        if response == 'y' or response == 'yes':
                            print("  Updating...")
                            result = subprocess.run(
                                ['git', 'pull'],
                                cwd=SCRIPT_DIR,
                                capture_output=True,
                                text=True,
                                timeout=60
                            )
                            if result.returncode == 0:
                                print("  Updated successfully. Restarting health check...\n")
                                # Restart the script with the same arguments
                                os.execv(sys.executable, [sys.executable] + sys.argv + ['--no-update-check'])
                            else:
                                print(f"  [WARN] Update failed: {result.stderr.strip()}")
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Skipping update.")
        except Exception:
            pass  # Silently ignore any errors in update check

    # Check for updates (skip only if explicitly disabled with --no-update-check)
    if sys.stdin.isatty() and not args.no_update_check:
        check_for_updates()

    # Handle usage/scan action (-u)
    if args.usage:
        # Pass sosreport_dir and any CLI-provided hosts to avoid re-prompting
        result = run_usage_scan(base_dir=args.sosreport_dir, seed_hosts=args.hosts or None)
        if result is None:
            sys.exit(0)

        # Process the result and run health check
        if result['action'] == 'local':
            args.local = True
        elif result['action'] == 'hosts':
            # Create temp hosts file
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            for host in result['hosts']:
                temp_file.write(f"{host}\n")
            temp_file.close()
            args.hosts_file = temp_file.name
        elif result['action'] == 'hosts_file':
            args.hosts_file = result['hosts_file']
        elif result['action'] == 'sosreport':
            args.sosreport_dir = result['sosreport_dir']
        elif result['action'] == 'continue':
            args.config_dir = result.get('config_dir')
        elif result['action'] == 'fetch_sosreports':
            # Fetch SOSreports from cluster and then analyze them
            seed_node = result['seed_node']
            output_dir = result.get('output_dir') or args.sosreport_dir
            downloaded = create_and_fetch_sosreports(
                seed_node=seed_node,
                output_dir=output_dir,
                interactive=sys.stdin.isatty()
            )
            if downloaded:
                # Set sosreport_dir to where we downloaded them
                args.sosreport_dir = output_dir or str(Path.cwd() / 'sosreports')
            else:
                print("  No SOSreports were collected.")
                sys.exit(1)
        # Continue to run the health check with the set arguments

    # Handle guide action
    if args.guide:
        print_guide()
        sys.exit(0)

    # Handle install guide shortcut (-i / --install)
    if args.install:
        # Try to use dynamic guide if we have access config
        config_dir = Path(args.config_dir) if args.config_dir else SCRIPT_DIR
        config_path = config_dir / AccessDiscovery.CONFIG_FILE
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    access_data = yaml.safe_load(f) or {}
                if access_data.get('nodes'):
                    # Create minimal health check instance for dynamic guide
                    hc = ClusterHealthCheck(config_dir=str(config_dir), local_mode=args.local)
                    hc.access_config = type('Config', (), {'nodes': access_data.get('nodes', {})})()
                    hc.print_dynamic_install_guide()
                    sys.exit(0)
            except Exception:
                pass
        # Fall back to static guide
        print_suggestions('install')
        sys.exit(0)

    # Handle suggest action
    if args.suggest:
        step = args.suggest
        skip_steps = args.suggest_skip or []
        config_dir = Path(args.config_dir) if args.config_dir else SCRIPT_DIR

        if step == 'auto':
            # Read last run status to find first failing step
            status_file = config_dir / "last_run_status.yaml"

            if not status_file.exists():
                print("No previous run found. Run a health check first:")
                print("  ./cluster_health_check.py hana01")
                print("\nOr specify a step directly:")
                print("  ./cluster_health_check.py --suggest config")
                sys.exit(1)

            with open(status_file, 'r') as f:
                status = yaml.safe_load(f)

            # Check for package/command issues in the last report
            packages_missing = False
            # Find most recent report
            import glob
            reports = sorted(glob.glob(str(config_dir / "health_check_report_*.yaml")), reverse=True)
            if reports:
                try:
                    with open(reports[0], 'r') as f:
                        report = yaml.safe_load(f)
                    for result in report.get('results', []):
                        msg = result.get('message', '') or ''
                        if 'package not found' in msg.lower() or ("command '" in msg.lower() and "not found" in msg.lower()):
                            packages_missing = True
                            break
                except Exception:
                    pass

            if packages_missing and 'install' not in skip_steps:
                print("Cluster packages not installed!")
                print("Showing installation guide...\n")
                step = 'install'
            else:
                failed_steps = status.get('failed_steps', [])

                # Filter out skipped steps
                if skip_steps:
                    failed_steps = [s for s in failed_steps if s not in skip_steps]
                    if skip_steps:
                        print(f"Skipping: {', '.join(skip_steps)}\n")

                if not failed_steps:
                    print("No failing steps found!")
                    if skip_steps:
                        print(f"(after skipping: {', '.join(skip_steps)})")
                    print("\nAll steps passed in the last run.")
                    sys.exit(0)

                step = failed_steps[0]
                print(f"First failing step: {step}")
                if len(failed_steps) > 1:
                    others = ', '.join(failed_steps[1:])
                    print(f"Other failing steps: {others}")
                    print(f"\nTo skip this and see next: --suggest --suggest-skip {step}")
                print()

        # Use dynamic guide for install step
        if step == 'install':
            config_path = config_dir / AccessDiscovery.CONFIG_FILE
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        access_data = yaml.safe_load(f) or {}
                    if access_data.get('nodes'):
                        hc = ClusterHealthCheck(config_dir=str(config_dir), local_mode=args.local)
                        hc.access_config = type('Config', (), {'nodes': access_data.get('nodes', {})})()
                        hc.print_dynamic_install_guide()
                        sys.exit(0)
                except Exception:
                    pass

        print_suggestions(step)
        sys.exit(0)

    # Handle list-steps action
    if args.list_steps:
        print_steps()
        sys.exit(0)

    # Determine config directory
    config_dir = Path(args.config_dir) if args.config_dir else SCRIPT_DIR
    config_path = config_dir / AccessDiscovery.CONFIG_FILE

    # Handle export-ansible action (before interactive mode)
    if args.export_ansible:
        cluster_name = args.export_ansible[0]
        output_file = args.export_ansible[1] if len(args.export_ansible) > 1 else None
        success = export_ansible_vars(config_path, cluster_name, output_file)
        sys.exit(0 if success else 1)

    # Handle fetch-sosreports action
    if args.fetch_sosreports is not None:
        # Check what was provided: cluster name or node names
        fetch_args = args.fetch_sosreports
        auto_create = getattr(args, 'create_sosreports', False)

        if not fetch_args:
            # No arguments - use cluster from -C if provided
            if args.cluster:
                downloaded = fetch_sosreports(config_path, cluster_name=args.cluster,
                                              auto_create=auto_create)
            else:
                print("[ERROR] Please specify a cluster name or node names.")
                print("Usage: --fetch-sosreports CLUSTER")
                print("       --fetch-sosreports node1 node2 ...")
                print("       -C CLUSTER --fetch-sosreports")
                sys.exit(1)
        elif len(fetch_args) == 1:
            # Single argument - check if it's a cluster name or a node
            arg = fetch_args[0]
            # Load config to check if it's a cluster name
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                clusters = config.get('clusters', {})
                if arg in clusters:
                    downloaded = fetch_sosreports(config_path, cluster_name=arg,
                                                  auto_create=auto_create)
                else:
                    # Treat as node name
                    downloaded = fetch_sosreports(config_path, nodes=[arg],
                                                  auto_create=auto_create)
            else:
                # No config, treat as node name
                downloaded = fetch_sosreports(config_path, nodes=[arg],
                                              auto_create=auto_create)
        else:
            # Multiple arguments - treat as node names
            downloaded = fetch_sosreports(config_path, nodes=fetch_args,
                                          auto_create=auto_create)

        sys.exit(0 if downloaded else 1)

    # Handle collect-sosreports action (new comprehensive workflow)
    if args.collect_sosreports:
        seed_node = args.collect_sosreports
        configure_ext = getattr(args, 'configure_extensions', None)

        downloaded = create_and_fetch_sosreports(
            seed_node=seed_node,
            output_dir=args.sosreport_dir,
            configure_extensions=configure_ext,
            interactive=sys.stdin.isatty()
        )
        sys.exit(0 if downloaded else 1)

    # Interactive mode: if no arguments provided, show intro and ask user
    local_mode = args.local
    interactive_hosts = None

    no_input_specified = (not args.hosts and not args.hosts_file and
                          not args.sosreport_dir and not args.cluster and
                          not args.local and not args.access_only and
                          not args.show_config and not args.delete_reports and
                          not args.list_rules and not args.force and
                          not args.export_ansible and
                          args.fetch_sosreports is None)

    if no_input_specified:
        # Run interactive startup
        nodes, should_continue = interactive_startup(config_path)
        if not should_continue:
            sys.exit(0)

        if nodes == ['local']:
            local_mode = True
        elif nodes:
            interactive_hosts = nodes

    # Handle hosts provided on command line or from interactive mode
    hosts_file = args.hosts_file
    temp_hosts_file = None
    hosts_to_use = args.hosts or interactive_hosts

    if hosts_to_use and not hosts_file:
        # Create temporary hosts file from command line or interactive input
        import tempfile
        temp_hosts_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        for host in hosts_to_use:
            temp_hosts_file.write(f"{host}\n")
        temp_hosts_file.close()
        hosts_file = temp_hosts_file.name
        if args.debug:
            print(f"[DEBUG] Created temp hosts file: {hosts_file}")
            print(f"[DEBUG] Hosts: {', '.join(hosts_to_use)}")

    # Handle show-config action
    if args.show_config:
        # args.show_config is True (no argument) or a string (cluster/node name)
        cluster_or_node = None if args.show_config is True else args.show_config
        show_config(config_path, cluster_or_node, config_only=True)
        sys.exit(0)

    # Handle delete-config action
    if args.delete_reports:
        delete_config(config_path)
        print("  Restarting health check...\n")
        # Restart without -D flag to prevent loop
        new_argv = [arg for arg in sys.argv if arg not in ['-D', '--delete-reports']]
        os.execv(sys.executable, [sys.executable] + new_argv)

    # Handle list-rules action
    if args.list_rules:
        rules_path = args.rules_path or ClusterHealthCheck.DEFAULT_RULES_PATH
        engine = RulesEngine(rules_path=rules_path)
        engine.load_rules()
        print("\n" + "=" * 63)
        print(" Available Health Check Rules")
        print("=" * 63)
        print(f"\nRules path: {rules_path}\n")
        print(f"{'Check ID':<30} {'Severity':<10} Description")
        print("-" * 63)
        for rule in engine.rules:
            print(f"{rule.check_id:<30} {rule.severity:<10} {rule.description[:40]}")
        print(f"\nTotal: {len(engine.rules)} rules")
        sys.exit(0)

    # Create health check instance
    # PDF generation is enabled by default, can be disabled with --no-pdf
    generate_pdf = not args.no_pdf
    verbose_pdf = args.verbose  # Show all checks in detail in PDF

    # Check upfront if fpdf2 is available - inform user and disable PDF generation if not
    if generate_pdf:
        from report_generator import is_pdf_available
        if not is_pdf_available():
            print("  [INFO] PDF reports will not be created (fpdf2 not installed)")
            print("         To enable: pip install fpdf2")
            generate_pdf = False

    health_check = ClusterHealthCheck(
        config_dir=str(config_dir),
        sosreport_dir=args.sosreport_dir,
        hosts_file=hosts_file,
        workers=args.workers,
        rules_path=args.rules_path,
        debug=args.debug,
        ansible_group=args.group,
        cluster_name=args.cluster,
        local_mode=local_mode,
        strict_mode=args.strict,
        generate_pdf=generate_pdf,
        verbose_pdf=verbose_pdf
    )

    def cleanup_temp_file():
        """Clean up temporary hosts file if created."""
        if temp_hosts_file:
            try:
                os.unlink(temp_hosts_file.name)
            except Exception:
                pass

    def show_interactive_menu():
        """Show interactive menu and return user choice."""
        print("\n" + "=" * 63)
        print(" What would you like to do next?")
        print("=" * 63)
        print("  [1] Show installation status (-i)  [default]")
        print("  [2] Rerun health check")
        print("  [3] Run on different hosts")
        print("  [4] Show configuration")
        if generate_pdf:
            print("  [5] Save PDF report (custom filename)")
        print("  [6] Show suggestions")
        print("  [7] Reset configuration (delete cached discovery)")
        if generate_pdf:
            print("  [q] Save PDF and quit")
        else:
            print("  [q] Quit")
        if not generate_pdf:
            print("  (PDF options hidden - fpdf2 not installed)")
        print("-" * 63)
        try:
            choice = input("  Enter choice [1-7/q] (default=1): ").strip().lower()
            return choice if choice else '1'  # Default to installation status
        except (EOFError, KeyboardInterrupt):
            return 'q'

    try:
        if args.access_only:
            # Only run access discovery
            health_check.print_banner()
            success = health_check.step_access_discovery(force=args.force)
            cleanup_temp_file()
            sys.exit(0 if success else 1)
        else:
            # Run all checks
            exit_code = health_check.run_all_checks(
                force_rediscover=args.force,
                skip_steps=args.skip
            )

            # If cluster is healthy (exit_code == 0), exit directly
            if exit_code == 0:
                # Auto-open PDF if generated
                if generate_pdf and health_check.last_pdf_file:
                    import subprocess
                    import platform
                    try:
                        system = platform.system()
                        if system == 'Linux':
                            subprocess.Popen(['xdg-open', str(health_check.last_pdf_file)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        elif system == 'Darwin':  # macOS
                            subprocess.Popen(['open', str(health_check.last_pdf_file)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        elif system == 'Windows':
                            os.startfile(str(health_check.last_pdf_file))
                        print("  Opening PDF...")
                    except Exception:
                        pass  # Silently ignore if can't open
                print("\n  Goodbye!")
                cleanup_temp_file()
                sys.exit(0)

            # Interactive menu loop (only shown when there are issues)
            while True:
                choice = show_interactive_menu()

                if choice == '1' or choice == 'i':
                    # Show installation status
                    health_check.print_dynamic_install_guide()
                elif choice == '2' or choice == 'r':
                    # Rerun health check
                    print("\n" + "=" * 63)
                    print(" Rerunning health check...")
                    print("=" * 63)
                    exit_code = health_check.run_all_checks(
                        force_rediscover=False,
                        skip_steps=args.skip
                    )
                elif choice == '3' or choice == 'h':
                    # Run on different hosts
                    try:
                        new_hosts = input("  Enter hostnames (space-separated): ").strip()
                        if new_hosts:
                            host_list = new_hosts.split()
                            print(f"\n  Running health check on: {', '.join(host_list)}")
                            print("=" * 63)

                            # Create temporary hosts file
                            import tempfile
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
                                tmp.write('\n'.join(host_list))
                                tmp_hosts_path = tmp.name

                            try:
                                # Create new health check instance with new hosts
                                new_health_check = ClusterHealthCheck(
                                    config_dir=str(config_dir),
                                    sosreport_dir=args.sosreport_dir,
                                    hosts_file=tmp_hosts_path,
                                    workers=args.workers,
                                    rules_path=args.rules_path,
                                    debug=args.debug,
                                    ansible_group=args.group,
                                    cluster_name=None,  # Force rediscovery
                                    local_mode=False,
                                    strict_mode=args.strict,
                                    generate_pdf=not args.no_pdf,
                                    verbose_pdf=verbose_pdf
                                )
                                # Run health check with force rediscovery
                                exit_code = new_health_check.run_all_checks(
                                    force_rediscover=True,
                                    skip_steps=args.skip
                                )
                                # Update reference for subsequent menu options
                                health_check = new_health_check
                            finally:
                                # Clean up temp file
                                try:
                                    os.unlink(tmp_hosts_path)
                                except Exception:
                                    pass
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Cancelled.")
                elif choice == '4' or choice == 'c':
                    # Show configuration (show_config imported at module level)
                    show_config(health_check.config_dir / 'cluster_access_config.yaml')
                elif choice == '5' or choice == 'p':
                    # Save PDF report with custom filename
                    if not generate_pdf:
                        print("\n  [INFO] PDF reports not available (fpdf2 not installed)")
                        continue
                    if not health_check.check_results:
                        print("\n  [WARN] No health check results available. Run a health check first.")
                        continue
                    try:
                        # Get cluster name for default filename
                        cluster_name = '(unknown)'
                        if health_check.access_config and health_check.access_config.clusters:
                            for cname in health_check.access_config.clusters.keys():
                                if cname != '(unknown)':
                                    cluster_name = cname
                                    break
                        cluster_name_safe = re.sub(r'[^\w\-]', '_', cluster_name)

                        # Default filename
                        pdf_timestamp = datetime.now().strftime('%Y%m%d')
                        pdf_time = datetime.now().strftime('%H%M')
                        default_name = f"{pdf_timestamp}_health_check_report_{cluster_name_safe}_{pdf_time}.pdf"

                        print(f"\n  Default filename: {default_name}")
                        custom_name = input("  Enter filename (or press Enter for default): ").strip()

                        if custom_name:
                            # Ensure .pdf extension
                            if not custom_name.lower().endswith('.pdf'):
                                custom_name += '.pdf'
                            pdf_file = health_check.config_dir / custom_name
                        else:
                            pdf_file = health_check.config_dir / default_name

                        # Generate PDF using unified data model
                        from report_generator import generate_health_check_report

                        # Use unified data model for PDF generation
                        report_data = health_check._build_cluster_report_data()

                        generate_health_check_report(
                            report_data.get_results_list(),
                            report_data.get_summary_dict(),
                            report_data.to_cluster_info(),
                            str(pdf_file),
                            report_data.get_install_status() or None,
                            verbose=verbose_pdf
                        )
                        print(f"\n  PDF report saved: {pdf_file}")
                        print("  Goodbye!")
                        break

                    except ImportError:
                        print("\n  [ERROR] PDF generation requires fpdf2")
                        print("         Install with: pip install fpdf2")
                        print("         Or run with --no-pdf to skip PDF generation")
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Cancelled.")
                    except Exception as e:
                        print(f"\n  [ERROR] PDF generation failed: {e}")
                elif choice == '6' or choice == 's':
                    # Show suggestions
                    print("\n  Available suggestion topics:")
                    print("    [1] install   - Full installation guide")
                    print("    [2] access    - Access discovery help")
                    print("    [3] config    - Cluster configuration")
                    print("    [4] pacemaker - Pacemaker/Corosync")
                    print("    [5] sap       - SAP HANA configuration")
                    print("    [a] all       - Show all suggestions")
                    print("    [q] back      - Return to main menu")
                    try:
                        topic = input("\n  Select topic: ").strip().lower()
                        topic_map = {'1': 'install', '2': 'access', '3': 'config', '4': 'pacemaker', '5': 'sap'}
                        if topic in topic_map:
                            print_suggestions(topic_map[topic])
                        elif topic in ['install', 'access', 'config', 'pacemaker', 'sap']:
                            print_suggestions(topic)
                        elif topic == 'a' or topic == 'all':
                            for t in ['install', 'access', 'config', 'pacemaker', 'sap']:
                                print_suggestions(t)
                        elif topic == 'q' or topic == 'back' or topic == '':
                            pass  # Return to main menu
                        else:
                            print(f"  Unknown topic: {topic}")
                    except (EOFError, KeyboardInterrupt):
                        pass
                elif choice == '7' or choice == 'd':
                    # Reset/delete configuration
                    config_file = health_check.config_dir / 'cluster_access_config.yaml'
                    if config_file.exists():
                        try:
                            confirm = input("  Delete saved configuration? This will force fresh discovery. [y/N]: ").strip().lower()
                            if confirm == 'y' or confirm == 'yes':
                                config_file.unlink()
                                print("  Configuration deleted.")
                                print("\n  To rediscover, run:")
                                print("    ./cluster_health_check.py <hostname>")
                                print("    ./cluster_health_check.py -s sosreports/")
                            else:
                                print("  Cancelled.")
                        except (EOFError, KeyboardInterrupt):
                            print("\n  Cancelled.")
                    else:
                        print("  No configuration file found.")
                elif choice == 'q' or choice == 'quit' or choice == 'exit':
                    # Save PDF before quitting (if available)
                    if generate_pdf and health_check.check_results:
                        try:
                            # Get cluster name for filename
                            cluster_name = '(unknown)'
                            if health_check.access_config and health_check.access_config.clusters:
                                for cname in health_check.access_config.clusters.keys():
                                    if cname != '(unknown)':
                                        cluster_name = cname
                                        break
                            cluster_name_safe = re.sub(r'[^\w\-]', '_', cluster_name)

                            # Generate filename
                            pdf_timestamp = datetime.now().strftime('%Y%m%d')
                            pdf_time = datetime.now().strftime('%H%M')
                            pdf_file = health_check.config_dir / f"{pdf_timestamp}_health_check_report_{cluster_name_safe}_{pdf_time}.pdf"

                            # Generate PDF
                            from report_generator import generate_health_check_report
                            report_data = health_check._build_cluster_report_data()
                            generate_health_check_report(
                                report_data.get_results_list(),
                                report_data.get_summary_dict(),
                                report_data.to_cluster_info(),
                                str(pdf_file),
                                report_data.get_install_status() or None,
                                verbose=verbose_pdf
                            )
                            print(f"\n  PDF report saved: {pdf_file}")

                            # Open PDF with default viewer
                            import subprocess
                            import platform
                            try:
                                system = platform.system()
                                if system == 'Linux':
                                    subprocess.Popen(['xdg-open', str(pdf_file)],
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                elif system == 'Darwin':  # macOS
                                    subprocess.Popen(['open', str(pdf_file)],
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                elif system == 'Windows':
                                    os.startfile(str(pdf_file))
                                print("  Opening PDF...")
                            except Exception:
                                pass  # Silently ignore if can't open
                        except Exception as e:
                            print(f"\n  [WARN] Could not save PDF: {e}")
                    print("  Goodbye!")
                    break
                else:
                    print(f"  Invalid choice: {choice}")

            cleanup_temp_file()
            sys.exit(exit_code)

    except KeyboardInterrupt:
        cleanup_temp_file()
        print("\n\n[INTERRUPTED] Health check aborted by user.")
        sys.exit(130)


if __name__ == '__main__':
    main()
