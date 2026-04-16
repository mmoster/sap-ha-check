#!/usr/bin/env python3
"""
SAP Pacemaker Cluster Health Check - Access Discovery Module

Discovers available access methods to cluster nodes:
1. SSH direct access (preferred)
2. Ansible inventory
3. SOSreport files

Results are stored in a YAML config file for incremental investigation.
"""

import os
import sys
import subprocess
import yaml
import argparse
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any
from datetime import datetime

# Python 3.6 compatibility for dataclasses
try:
    from dataclasses import dataclass, field, asdict
except ImportError:
    # Fallback for Python < 3.7
    def field(default=None, default_factory=None):
        return default_factory() if default_factory else default

    def dataclass(cls):
        """Simple dataclass decorator fallback"""
        def __init__(self, **kwargs):
            # Set defaults from class annotations first
            if hasattr(cls, '__annotations__'):
                for name in cls.__annotations__:
                    default = getattr(cls, name, None)
                    setattr(self, name, default)
            # Override with provided kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)
            # Call __post_init__ if defined
            if hasattr(self, '__post_init__'):
                self.__post_init__()
        cls.__init__ = __init__
        return cls

    def asdict(obj):
        """Simple asdict fallback"""
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
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


class AccessDiscovery:
    """Discovers and validates access methods to cluster nodes."""

    CONFIG_FILE = "cluster_access_config.yaml"
    ANSIBLE_CFG_LOCATIONS = [
        "./ansible.cfg",
        os.path.expanduser("~/.ansible.cfg"),
        "/etc/ansible/ansible.cfg"
    ]
    DEFAULT_ANSIBLE_INVENTORY = "/etc/ansible/hosts"
    SSH_TIMEOUT = 5
    MAX_WORKERS = 10

    def __init__(self, config_dir: str = ".", sosreport_dir: Optional[str] = None,
                 hosts_file: Optional[str] = None, force_rediscover: bool = False,
                 debug: bool = False, ansible_group: Optional[str] = None,
                 skip_ansible: bool = False, cluster_name: Optional[str] = None,
                 local_mode: bool = False):
        self.config_dir = Path(config_dir)
        self.config_path = self.config_dir / self.CONFIG_FILE
        self.sosreport_dir = sosreport_dir
        self.hosts_file = hosts_file
        self.force_rediscover = force_rediscover
        self.debug = debug
        self.ansible_group = ansible_group
        self.skip_ansible = skip_ansible
        self.cluster_name = cluster_name
        self.local_mode = local_mode
        self.local_hostname = None
        self.config = self._load_or_create_config()

    def _load_or_create_config(self) -> AccessConfig:
        """Load existing config or create new one."""
        if self.config_path.exists() and not self.force_rediscover:
            print(f"Loading existing config from {self.config_path}")
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
                config = AccessConfig(**data)
                # Clear old nodes if hosts file specified (fresh discovery for those hosts)
                if self.hosts_file:
                    if self.debug:
                        print("  [DEBUG] Clearing old nodes for fresh cluster discovery")
                    config.nodes = {}
                return config
        if self.force_rediscover:
            print("Starting fresh discovery (--force)")
        return AccessConfig()

    def save_config(self):
        """Save current configuration to YAML file."""
        self.config.discovery_timestamp = datetime.now().isoformat()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            yaml.dump(asdict(self.config), f, default_flow_style=False)
        print(f"Configuration saved to {self.config_path}")

    def discover_ansible_inventory(self) -> Optional[str]:
        """
        Discover Ansible inventory location.
        Priority:
        1. $ANSIBLE_INVENTORY environment variable
        2. ansible.cfg inventory = setting
        3. Default /etc/ansible/hosts
        """
        print("\n=== Discovering Ansible Inventory ===")

        # Check environment variable
        env_inventory = os.environ.get('ANSIBLE_INVENTORY')
        if env_inventory and os.path.exists(env_inventory):
            print(f"Found via $ANSIBLE_INVENTORY: {env_inventory}")
            self.config.ansible_inventory_source = "environment"
            self.config.ansible_inventory_path = env_inventory
            return env_inventory

        # Check ansible.cfg files
        for cfg_path in self.ANSIBLE_CFG_LOCATIONS:
            cfg_path = os.path.expanduser(cfg_path)
            if os.path.exists(cfg_path):
                print(f"Checking {cfg_path}...")
                try:
                    with open(cfg_path, 'r') as f:
                        content = f.read()
                    # Look for inventory = <path> in [defaults] section
                    match = re.search(r'^\s*inventory\s*=\s*(.+?)\s*$', content, re.MULTILINE)
                    if match:
                        inv_path = os.path.expanduser(match.group(1).strip())
                        if os.path.exists(inv_path):
                            print(f"Found via {cfg_path}: {inv_path}")
                            self.config.ansible_inventory_source = cfg_path
                            self.config.ansible_inventory_path = inv_path
                            return inv_path
                except Exception as e:
                    print(f"  Error reading {cfg_path}: {e}")

        # Check default location
        if os.path.exists(self.DEFAULT_ANSIBLE_INVENTORY):
            print(f"Using default: {self.DEFAULT_ANSIBLE_INVENTORY}")
            self.config.ansible_inventory_source = "default"
            self.config.ansible_inventory_path = self.DEFAULT_ANSIBLE_INVENTORY
            return self.DEFAULT_ANSIBLE_INVENTORY

        print("No Ansible inventory found")
        return None

    def get_ansible_hosts(self) -> Dict[str, Dict[str, Any]]:
        """Get hosts from Ansible inventory using ansible-inventory command."""
        print("\n=== Retrieving Ansible Hosts ===")
        hosts = {}

        try:
            cmd = ["ansible-inventory", "--list", "--yaml"]
            if self.config.ansible_inventory_path:
                cmd.extend(["-i", self.config.ansible_inventory_path])

            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)

            if result.returncode == 0:
                inventory = yaml.safe_load(result.stdout)
                hosts = self._parse_ansible_inventory(inventory)
                print(f"Found {len(hosts)} hosts in Ansible inventory")
            else:
                print(f"ansible-inventory failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            print("ansible-inventory timed out")
        except FileNotFoundError:
            print("ansible-inventory command not found")
        except Exception as e:
            print(f"Error getting Ansible hosts: {e}")

        return hosts

    def _parse_ansible_inventory(self, inventory: dict, hosts: dict = None) -> Dict[str, Dict[str, Any]]:
        """Recursively parse Ansible inventory structure."""
        if hosts is None:
            hosts = {}

        if not isinstance(inventory, dict):
            return hosts

        # Parse 'all' group structure
        if 'all' in inventory:
            return self._parse_ansible_inventory(inventory['all'], hosts)

        # Parse hosts at current level
        if 'hosts' in inventory and isinstance(inventory['hosts'], dict):
            for hostname, hostvars in inventory['hosts'].items():
                hosts[hostname] = {
                    'ansible_host': hostvars.get('ansible_host', hostname) if hostvars else hostname,
                    'ansible_user': hostvars.get('ansible_user') if hostvars else None,
                }

        # Recursively parse children groups
        if 'children' in inventory and isinstance(inventory['children'], dict):
            for group_name, group_data in inventory['children'].items():
                self._parse_ansible_inventory(group_data, hosts)

        return hosts

    def get_hosts_from_file(self) -> List[str]:
        """Read hosts from a simple hosts file (one host per line)."""
        hosts = []
        if self.hosts_file and os.path.exists(self.hosts_file):
            print(f"\n=== Reading hosts from {self.hosts_file} ===")
            with open(self.hosts_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        hosts.append(line.split()[0])  # Take first column
            print(f"Found {len(hosts)} hosts")
            self.config.hosts_file = self.hosts_file
        return hosts

    def _extract_sosreport(self, archive_path: str) -> tuple:
        """
        Extract a single SOSreport archive if not already extracted.
        Returns (success: bool, extracted_dir: str or error_msg: str)
        """
        archive_name = os.path.basename(archive_path)
        base_dir = os.path.dirname(archive_path)

        # Determine the expected directory name (remove .tar.xz, .tar.gz, etc.)
        dir_name = archive_name
        for ext in ['.tar.xz', '.tar.gz', '.tar.bz2', '.tgz', '.txz']:
            if dir_name.endswith(ext):
                dir_name = dir_name[:-len(ext)]
                break

        expected_dir = os.path.join(base_dir, dir_name)

        # Check if already extracted
        if os.path.isdir(expected_dir):
            return (True, expected_dir)

        # Determine extraction command based on extension
        if archive_path.endswith('.tar.xz') or archive_path.endswith('.txz'):
            cmd = ['tar', 'xJf', archive_path, '-C', base_dir]
        elif archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
            cmd = ['tar', 'xzf', archive_path, '-C', base_dir]
        elif archive_path.endswith('.tar.bz2'):
            cmd = ['tar', 'xjf', archive_path, '-C', base_dir]
        else:
            return (False, f"Unknown archive format: {archive_name}")

        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=300  # 5 minute timeout for large archives
            )
            if result.returncode == 0:
                # Find the extracted directory
                if os.path.isdir(expected_dir):
                    return (True, expected_dir)
                # Sometimes the directory name differs slightly, look for it
                for item in os.listdir(base_dir):
                    item_path = os.path.join(base_dir, item)
                    if os.path.isdir(item_path) and item.startswith('sosreport-') and dir_name.startswith(item[:20]):
                        return (True, item_path)
                return (True, expected_dir)  # Assume it worked
            else:
                return (False, f"Extract failed: {result.stderr[:100]}")
        except subprocess.TimeoutExpired:
            return (False, "Extract timed out (>5 min)")
        except Exception as e:
            return (False, str(e))

    def discover_sosreports(self) -> Dict[str, str]:
        """Discover SOSreport directories and map to hostnames."""
        sosreports = {}
        if not self.sosreport_dir or not os.path.exists(self.sosreport_dir):
            return sosreports

        print(f"\n=== Discovering SOSreports in {self.sosreport_dir} ===")
        self.config.sosreport_directory = self.sosreport_dir

        # First, find and extract any compressed SOSreports (multithreaded)
        archives = []
        archive_extensions = ('.tar.xz', '.tar.gz', '.tar.bz2', '.tgz', '.txz')
        for item in os.listdir(self.sosreport_dir):
            if item.startswith('sosreport-') and item.endswith(archive_extensions):
                archive_path = os.path.join(self.sosreport_dir, item)
                archives.append(archive_path)

        if archives:
            print(f"  Found {len(archives)} compressed SOSreport(s), checking/extracting...")
            with ThreadPoolExecutor(max_workers=min(len(archives), 4)) as executor:
                futures = {executor.submit(self._extract_sosreport, arch): arch for arch in archives}
                for future in as_completed(futures):
                    archive = futures[future]
                    archive_name = os.path.basename(archive)
                    try:
                        success, result = future.result()
                        if success:
                            print(f"    [OK] {archive_name}")
                        else:
                            print(f"    [FAIL] {archive_name}: {result}")
                    except Exception as e:
                        print(f"    [ERROR] {archive_name}: {e}")

        # Look for sosreport directories (pattern: sosreport-<hostname>-<id>)
        for item in os.listdir(self.sosreport_dir):
            item_path = os.path.join(self.sosreport_dir, item)
            if os.path.isdir(item_path) and item.startswith('sosreport-'):
                # Extract hostname from sosreport directory name
                parts = item.split('-')
                if len(parts) >= 2:
                    hostname = parts[1]
                    sosreports[hostname] = item_path
                    print(f"  Found: {hostname} -> {item}")

        # Also check for extracted sosreports by reading etc/hostname
        for item in os.listdir(self.sosreport_dir):
            item_path = os.path.join(self.sosreport_dir, item)
            hostname_file = os.path.join(item_path, 'etc/hostname')
            if os.path.isdir(item_path) and os.path.exists(hostname_file):
                with open(hostname_file, 'r') as f:
                    hostname = f.read().strip().split('.')[0]  # Get short hostname
                if hostname and hostname not in sosreports:
                    sosreports[hostname] = item_path
                    print(f"  Found: {hostname} -> {item}")

        print(f"Found {len(sosreports)} SOSreports")

        # Check for extended SAP HANA HA data and suggest configuration if missing
        if sosreports:
            self._check_sosreport_extended_data(sosreports)

        return sosreports

    def _check_sosreport_extended_data(self, sosreports: Dict[str, str]) -> None:
        """
        Check if SOSreports have extended SAP HANA HA data.
        Print suggestions if the data is missing.
        """
        missing_extended = []
        has_extended = []

        for hostname, sos_path in sosreports.items():
            extras_path = Path(sos_path) / "sos_commands/sos_extras/sap_hana_ha"
            saphana_path = Path(sos_path) / "sos_commands/saphana"

            # Check for SAPHanaSR-showAttr in extras
            has_sr_attr = (extras_path / "SAPHanaSR-showAttr").exists() if extras_path.exists() else False

            if has_sr_attr:
                has_extended.append(hostname)
            else:
                missing_extended.append(hostname)

        if missing_extended and not has_extended:
            # All SOSreports are missing extended data
            print("\n" + "=" * 63)
            print(" [SUGGESTION] SOSreports missing extended SAP HANA HA data")
            print("=" * 63)
            print("""
  The SOSreports do not contain SAPHanaSR-showAttr output, which is
  critical for analyzing SAP HANA System Replication cluster state.

  To collect extended SAP HANA HA data in future SOSreports, deploy
  the following configuration to all cluster nodes:

  1. Update /etc/sos/sos.conf:
     ─────────────────────────────────────────────────────────────
     [report]
     enable-plugins = saphana, sapnw, pacemaker, corosync, sos_extras

     [plugin_options]
     pacemaker.crm-scrub = on
     ─────────────────────────────────────────────────────────────

  2. Create /etc/sos/extras.d/sap_hana_ha:
     ─────────────────────────────────────────────────────────────
     SAPHanaSR-showAttr
     SAPHanaSR-showAttr --format=script
     crm_mon -1 -r -n
     pcs status --full
     pcs resource config
     pcs constraint config
     cibadmin --query --scope resources
     cibadmin --query --scope constraints
     ─────────────────────────────────────────────────────────────

  Then regenerate SOSreports with: sos report --batch
""")
            print("=" * 63)

    def scan_sosreports_recursive(self, base_dir: str = ".") -> Dict[str, str]:
        """
        Recursively scan base_dir and subdirectories for SOSreport directories.
        Returns dict mapping hostname -> sosreport_path.
        """
        sosreports = {}
        base_path = Path(base_dir).resolve()

        # Walk through all subdirectories
        for root, dirs, files in os.walk(base_path):
            # Skip hidden directories and common non-sosreport dirs
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'venv', '.git']]

            for d in dirs:
                if d.startswith('sosreport-'):
                    dir_path = os.path.join(root, d)
                    # Extract hostname from directory name
                    parts = d.split('-')
                    if len(parts) >= 2:
                        hostname = parts[1]
                        if hostname not in sosreports:
                            sosreports[hostname] = dir_path

                    # Also try reading etc/hostname for accurate hostname
                    hostname_file = os.path.join(dir_path, 'etc/hostname')
                    if os.path.exists(hostname_file):
                        try:
                            with open(hostname_file, 'r') as f:
                                hostname = f.read().strip().split('.')[0]
                            if hostname and hostname not in sosreports:
                                sosreports[hostname] = dir_path
                        except Exception:
                            pass

        return sosreports

    def was_cluster_running_in_sosreport(self, sosreport_path: str) -> tuple:
        """
        Check if the cluster was running when the SOSreport was captured.
        Returns tuple: (was_running, reason_message)
        """
        sos_path = Path(sosreport_path)

        # Check pcs status output for connection errors
        for pcs_file in ["sos_commands/pacemaker/pcs_status", "sos_commands/pacemaker/pcs_status_--full"]:
            pcs_status = sos_path / pcs_file
            if pcs_status.exists():
                try:
                    content = pcs_status.read_text()
                    # Check for connection failure messages
                    if "Connection to cluster failed" in content or "Error: cluster is not currently running" in content:
                        return (False, "pcs status shows cluster connection failed")
                    if "error:" in content.lower() and "cluster" in content.lower():
                        return (False, "pcs status shows cluster error")
                    # If we have normal cluster output, it was running
                    if "Cluster name:" in content or "nodes configured" in content:
                        return (True, "pcs status shows cluster was running")
                except Exception:
                    pass

        # Check crm_mon output
        crm_mon = sos_path / "sos_commands/pacemaker/crm_mon_-1"
        if crm_mon.exists():
            try:
                content = crm_mon.read_text()
                if "Connection to cluster failed" in content or "Could not connect" in content:
                    return (False, "crm_mon shows cluster connection failed")
                if "error:" in content.lower() and "cluster" in content.lower():
                    return (False, "crm_mon shows cluster error")
                # Normal output indicates cluster was running
                if "nodes configured" in content.lower() or "online" in content.lower():
                    return (True, "crm_mon shows cluster was running")
            except Exception:
                pass

        # Check systemd service status if available
        systemd_dir = sos_path / "sos_commands/systemd"
        if systemd_dir.exists():
            for service_file in systemd_dir.glob("systemctl_status_*pacemaker*"):
                try:
                    content = service_file.read_text()
                    if "Active: active (running)" in content:
                        return (True, "systemctl shows pacemaker was running")
                    if "Active: inactive" in content or "Active: failed" in content:
                        return (False, "systemctl shows pacemaker was not running")
                except Exception:
                    pass

        # Default: unknown, assume running (to avoid false positives)
        return (True, "cluster status unknown from sosreport")

    def get_cluster_name_from_sosreport(self, sosreport_path: str) -> Optional[str]:
        """Extract cluster name from a sosreport's corosync.conf or pcs status output."""
        sos_path = Path(sosreport_path)

        # Try corosync.conf first
        corosync_conf = sos_path / "etc/corosync/corosync.conf"
        if corosync_conf.exists():
            try:
                content = corosync_conf.read_text()
                # Look for cluster_name: <name> in totem section
                match = re.search(r'cluster_name:\s*(\S+)', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # Try pcs status output
        pcs_status = sos_path / "sos_commands/pacemaker/pcs_status"
        if pcs_status.exists():
            try:
                content = pcs_status.read_text()
                match = re.search(r'Cluster name:\s*(\S+)', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # Try crm_mon output
        crm_mon = sos_path / "sos_commands/pacemaker/crm_mon_-1"
        if crm_mon.exists():
            try:
                content = crm_mon.read_text()
                # Some versions show cluster name in the header
                match = re.search(r'Cluster\s+(\S+)\s+status', content, re.IGNORECASE)
                if match:
                    return match.group(1)
            except Exception:
                pass

        return None

    def get_cluster_nodes_from_sosreport(self, sosreport_path: str) -> List[str]:
        """Extract cluster node list from a sosreport's corosync.conf."""
        sos_path = Path(sosreport_path)
        nodes = []

        # Try corosync.conf
        corosync_conf = sos_path / "etc/corosync/corosync.conf"
        if corosync_conf.exists():
            try:
                content = corosync_conf.read_text()
                # Look for ring0_addr or name in nodelist section
                # Pattern: ring0_addr: <hostname/ip> or name: <hostname>
                ring_matches = re.findall(r'ring0_addr:\s*(\S+)', content)
                name_matches = re.findall(r'^\s*name:\s*(\S+)', content, re.MULTILINE)

                # Prefer name matches as they're usually hostnames
                if name_matches:
                    nodes = name_matches
                elif ring_matches:
                    nodes = ring_matches
            except Exception:
                pass

        return nodes

    def _discover_cluster_from_sosreports(self, available_sosreports: Dict[str, str]) -> Dict[str, str]:
        """
        From the SOSreports of nodes we already have, discover other cluster nodes
        and find their matching SOSreports. Also extracts cluster name.

        Args:
            available_sosreports: Dict of hostname -> sosreport_path for all available sosreports

        Returns:
            Dict of newly discovered hostname -> sosreport_path
        """
        discovered = {}
        cluster_name = None

        # Get cluster nodes from existing node's sosreport
        for hostname, node_info in self.config.nodes.items():
            sos_path = node_info.get('sosreport_path')
            if not sos_path:
                continue

            # Get cluster name from this sosreport (if not already found)
            if not cluster_name:
                cluster_name = self.get_cluster_name_from_sosreport(sos_path)
                if cluster_name:
                    # Add cluster to config
                    if cluster_name not in self.config.clusters:
                        self.config.clusters[cluster_name] = {
                            'nodes': [hostname],
                            'discovered_from': f'sosreport:{hostname}'
                        }
                        print(f"  [CLUSTER] Detected cluster name: {cluster_name}")
                    # Add existing node to cluster
                    if hostname not in self.config.clusters[cluster_name].get('nodes', []):
                        self.config.clusters[cluster_name].setdefault('nodes', []).append(hostname)

            # Get cluster nodes from this sosreport
            cluster_nodes = self.get_cluster_nodes_from_sosreport(sos_path)
            if not cluster_nodes:
                continue

            # Find matching sosreports for cluster nodes
            for cluster_node in cluster_nodes:
                if cluster_node in self.config.nodes:
                    continue  # Already have this node
                if cluster_node in discovered:
                    continue  # Already discovered

                # Look for matching sosreport
                if cluster_node in available_sosreports:
                    discovered[cluster_node] = available_sosreports[cluster_node]
                    # Add to cluster nodes list
                    if cluster_name and cluster_name in self.config.clusters:
                        if cluster_node not in self.config.clusters[cluster_name].get('nodes', []):
                            self.config.clusters[cluster_name].setdefault('nodes', []).append(cluster_node)
                else:
                    # Try partial match (hostname might be short vs FQDN)
                    for sos_hostname, sos_path_match in available_sosreports.items():
                        if cluster_node in sos_hostname or sos_hostname in cluster_node:
                            discovered[cluster_node] = sos_path_match
                            # Add to cluster nodes list
                            if cluster_name and cluster_name in self.config.clusters:
                                if cluster_node not in self.config.clusters[cluster_name].get('nodes', []):
                                    self.config.clusters[cluster_name].setdefault('nodes', []).append(cluster_node)
                            break

        return discovered

    def discover_sosreports_with_clusters(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover SOSreports and group them by cluster.
        Returns dict: {cluster_name: {'nodes': {hostname: sosreport_path}}}
        """
        clusters = {}  # cluster_name -> {'nodes': {hostname: path}}
        unassigned = {}  # hostname -> path (for sosreports without cluster info)

        # First discover all sosreports
        sosreports = self.discover_sosreports()

        if not sosreports:
            return clusters

        print("\n=== Detecting cluster membership from SOSreports ===")

        for hostname, sos_path in sosreports.items():
            cluster_name = self.get_cluster_name_from_sosreport(sos_path)

            if cluster_name:
                if cluster_name not in clusters:
                    clusters[cluster_name] = {'nodes': {}}
                clusters[cluster_name]['nodes'][hostname] = sos_path
                print(f"  {hostname}: cluster '{cluster_name}'")
            else:
                unassigned[hostname] = sos_path
                print(f"  {hostname}: (no cluster info)")

        # If there are unassigned nodes, try to match them to existing clusters
        # by checking if their hostnames appear in any cluster's nodelist
        if unassigned and clusters:
            for cluster_name, cluster_info in clusters.items():
                # Get expected nodes from first sosreport in this cluster
                # Use CIBParser for accurate node list from cib.xml
                first_sos_path = list(cluster_info['nodes'].values())[0]
                expected_nodes = self.get_cluster_nodes_from_sosreport(first_sos_path)

                # Also try to get nodes from cib.xml for more accurate matching
                try:
                    from lib.cib_parser import CIBParser
                    parser = CIBParser.from_sosreport(first_sos_path)
                    if parser and parser.is_available():
                        cib_nodes = parser.get_nodes()
                        if cib_nodes.get('success') and cib_nodes.get('nodes'):
                            expected_nodes = cib_nodes['nodes']
                except Exception:
                    pass  # Fall back to corosync.conf nodes

                for hostname, sos_path in list(unassigned.items()):
                    # Check if hostname exactly matches any expected node
                    if hostname in expected_nodes:
                        clusters[cluster_name]['nodes'][hostname] = sos_path
                        del unassigned[hostname]
                        print(f"  {hostname}: matched to cluster '{cluster_name}' (from nodelist)")
                        continue

        # Put remaining unassigned in 'unknown' cluster
        if unassigned:
            clusters['(unknown)'] = {'nodes': unassigned}

        return clusters

    def prompt_cluster_selection(self, clusters: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """
        Prompt user to select which cluster to analyze when multiple clusters are found.
        Returns selected cluster name or None if user cancels.
        """
        if len(clusters) <= 1:
            return list(clusters.keys())[0] if clusters else None

        print("\n" + "=" * 60)
        print(" Multiple clusters detected in SOSreports")
        print("=" * 60)

        cluster_list = list(clusters.keys())
        for i, cluster_name in enumerate(cluster_list, 1):
            nodes = list(clusters[cluster_name]['nodes'].keys())
            print(f"\n  [{i}] Cluster: {cluster_name}")
            print(f"      Nodes ({len(nodes)}): {', '.join(sorted(nodes))}")

        print("\n  [a] Analyze all clusters together")
        print("  [q] Quit")

        while True:
            try:
                choice = input("\nSelect cluster to analyze [1-{}/a/q]: ".format(len(cluster_list))).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return None

            if choice == 'q':
                return None
            elif choice == 'a':
                return '__all__'  # Special value to indicate all clusters
            elif choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(cluster_list):
                    selected = cluster_list[idx - 1]
                    print(f"\n  Selected: {selected}")
                    return selected

            print(f"  Invalid choice. Enter 1-{len(cluster_list)}, 'a' for all, or 'q' to quit.")

    def discover_cluster_name(self, host: str, user: str = None) -> Optional[str]:
        """Discover cluster name from a node."""
        ssh_user = user or 'root'
        # Use sudo for non-root users (cluster commands need root)
        sudo_prefix = "sudo " if ssh_user != 'root' else ""

        # Commands to try for getting cluster name
        name_commands = [
            "crm_attribute -G -n cluster-name -q 2>/dev/null",
            "pcs property show cluster-name 2>/dev/null | grep cluster-name | awk '{print $2}'",
            "corosync-cmapctl totem.cluster_name 2>/dev/null | cut -d= -f2 | tr -d ' '",
            "grep -oP 'cluster_name:\\s*\\K\\S+' /etc/corosync/corosync.conf 2>/dev/null",
        ]

        for cmd in name_commands:
            try:
                ssh_cmd = [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                    "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{host}",
                    f"{sudo_prefix}{cmd}"
                ]
                result = subprocess.run(ssh_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        universal_newlines=True, timeout=self.SSH_TIMEOUT + 2)

                if result.returncode == 0 and result.stdout.strip():
                    cluster_name = result.stdout.strip()
                    if cluster_name and cluster_name != '(null)':
                        return cluster_name
            except Exception:
                continue

        return None

    def discover_hana_info(self, host: str, user: str = None, cluster_nodes: list = None) -> dict:
        """
        Discover SAP HANA cluster configuration parameters.

        Returns Ansible-compatible parameters for sap_hana_ha_pacemaker role:
        - Core: sid, instance_number
        - Nodes: node1_fqdn, node1_ip, node2_fqdn, node2_ip
        - VIP: virtual_ip, secondary_vip
        - Cluster: cluster_name, secondary_read
        - Resources: resource_name, topology_resource, vip_resource
        - STONITH: stonith_device, stonith_type
        - Replication: replication_mode, operation_mode, sites
        """
        ssh_user = user or 'root'
        sudo_prefix = "sudo " if ssh_user != 'root' else ""
        hana_info = {}

        def run_ssh_cmd(cmd: str, target_host: str = None) -> str:
            """Helper to run SSH command and return output."""
            target = target_host or host
            try:
                ssh_cmd = [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                    "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{target}",
                    f"{sudo_prefix}{cmd}"
                ]
                result = subprocess.run(ssh_cmd, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       universal_newlines=True, timeout=self.SSH_TIMEOUT + 2)
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass
            return ""

        import re

        # === Core SAP HANA Parameters ===
        # Discover SID and instance from resource names
        resource_commands = [
            "pcs resource status 2>/dev/null | grep -oE 'SAPHana_[A-Z0-9]+_[0-9]+' | head -1",
            "pcs resource status 2>/dev/null | grep -oE 'SAPHanaController_[A-Z0-9]+_[0-9]+' | head -1",
            "crm resource status 2>/dev/null | grep -oE 'SAPHana_[A-Z0-9]+_[0-9]+' | head -1",
        ]

        for cmd in resource_commands:
            output = run_ssh_cmd(cmd)
            if output:
                match = re.match(r'(SAPHana(?:Controller)?)_([A-Z0-9]+)_(\d+)', output)
                if match:
                    hana_info['resource_type'] = match.group(1)
                    hana_info['sid'] = match.group(2)
                    hana_info['instance_number'] = match.group(3)
                    hana_info['resource_name'] = output
                    break

        # Get topology resource
        topo_output = run_ssh_cmd("pcs resource status 2>/dev/null | grep -oE 'SAPHanaTopology_[A-Z0-9]+_[0-9]+' | head -1")
        if topo_output:
            hana_info['topology_resource'] = topo_output

        # === Cluster Node Information ===
        nodes = cluster_nodes or []
        if len(nodes) >= 2:
            # Get FQDN for node1
            node1_fqdn = run_ssh_cmd("hostname -f 2>/dev/null || hostname", nodes[0])
            if node1_fqdn:
                hana_info['node1_fqdn'] = node1_fqdn
            hana_info['node1_hostname'] = nodes[0]

            # Get IP for node1
            node1_ip = run_ssh_cmd("hostname -i 2>/dev/null | awk '{print $1}'", nodes[0])
            if node1_ip:
                hana_info['node1_ip'] = node1_ip

            # Get FQDN for node2
            node2_fqdn = run_ssh_cmd("hostname -f 2>/dev/null || hostname", nodes[1])
            if node2_fqdn:
                hana_info['node2_fqdn'] = node2_fqdn
            hana_info['node2_hostname'] = nodes[1]

            # Get IP for node2
            node2_ip = run_ssh_cmd("hostname -i 2>/dev/null | awk '{print $1}'", nodes[1])
            if node2_ip:
                hana_info['node2_ip'] = node2_ip

        # === Virtual IP Configuration ===
        # Get all VIP resources and addresses
        vip_output = run_ssh_cmd("pcs resource config 2>/dev/null | grep -B2 -A5 'IPaddr2' | grep -oE 'ip=[0-9.]+' | cut -d= -f2")
        if vip_output:
            vips = [v.strip() for v in vip_output.split('\n') if v.strip()]
            if vips:
                hana_info['virtual_ip'] = vips[0]
                if len(vips) > 1:
                    hana_info['secondary_vip'] = vips[1]

        # Get VIP resource names
        vip_names = run_ssh_cmd("pcs resource status 2>/dev/null | grep -oE 'vip[-_][A-Za-z0-9_]+|rsc_ip_[A-Za-z0-9_]+|ip[-_][A-Za-z0-9_]+'")
        if vip_names:
            vip_list = [v.strip() for v in vip_names.split('\n') if v.strip()]
            if vip_list:
                hana_info['vip_resource'] = vip_list[0]
                if len(vip_list) > 1:
                    hana_info['secondary_vip_resource'] = vip_list[1]

        # Check if secondary read is enabled (look for second VIP or AUTOMATED_REGISTER)
        auto_reg = run_ssh_cmd("pcs resource config 2>/dev/null | grep -i 'AUTOMATED_REGISTER' | grep -oE 'true|false' | head -1")
        if auto_reg:
            hana_info['automated_register'] = auto_reg.lower() == 'true'

        # Check for secondary read (multiple VIPs or specific config)
        hana_info['secondary_read'] = 'secondary_vip' in hana_info

        # === STONITH/Fencing Configuration ===
        # Get STONITH device name and type
        stonith_name = run_ssh_cmd("pcs stonith status 2>/dev/null | grep -oE '^[[:space:]]*\\*[[:space:]]+[A-Za-z0-9_-]+' | awk '{print $2}' | head -1")
        if stonith_name:
            hana_info['stonith_device'] = stonith_name

        # Get STONITH device type (agent)
        stonith_type = run_ssh_cmd(f"pcs stonith config {stonith_name} 2>/dev/null | grep -oE 'stonith:[a-z_]+' | head -1" if stonith_name else "echo ''")
        if stonith_type:
            hana_info['stonith_type'] = stonith_type.replace('stonith:', '')

        # Get fence device parameters (for VMware, Azure, etc.)
        if stonith_name:
            fence_params = run_ssh_cmd(f"pcs stonith config {stonith_name} 2>/dev/null | grep -E 'ipaddr|login|passwd|ssl|pcmk_host' | head -5")
            if fence_params:
                params = {}
                for line in fence_params.split('\n'):
                    if '=' in line or ':' in line:
                        # Parse key=value or key: value
                        parts = re.split(r'[=:]', line.strip(), 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip()
                            # Don't store passwords
                            if 'pass' not in key.lower():
                                params[key] = val
                if params:
                    hana_info['stonith_params'] = params

        # === Cluster Properties ===
        # Get resource-stickiness
        stickiness = run_ssh_cmd("pcs property show 2>/dev/null | grep -i 'resource-stickiness' | grep -oE '[0-9]+' | head -1")
        if stickiness:
            hana_info['resource_stickiness'] = int(stickiness)

        # Get migration-threshold
        migration = run_ssh_cmd("pcs resource config 2>/dev/null | grep -i 'migration-threshold' | grep -oE '[0-9]+' | head -1")
        if migration:
            hana_info['migration_threshold'] = int(migration)

        # === SAP HANA System Replication ===
        # Get replication mode from SAPHanaSR
        repl_mode = run_ssh_cmd("SAPHanaSR-showAttr 2>/dev/null | grep -oE 'sync|syncmem|async' | head -1")
        if repl_mode:
            hana_info['replication_mode'] = repl_mode

        # Get operation mode
        op_mode = run_ssh_cmd("SAPHanaSR-showAttr 2>/dev/null | grep -oE 'logreplay|delta_datashipping' | head -1")
        if op_mode:
            hana_info['operation_mode'] = op_mode

        # Get site names from SAPHanaSR or crm_attribute
        sites_output = run_ssh_cmd("SAPHanaSR-showAttr 2>/dev/null | awk '/^Host/ {next} /^-/ {next} {print $4}' | sort -u | head -2")
        if not sites_output:
            # Try alternative: get from pcs resource config
            sid = hana_info.get('sid', '')
            if sid:
                sites_output = run_ssh_cmd("pcs resource config 2>/dev/null | grep -oE 'PREFER_SITE_TAKEOVER|site=[A-Za-z0-9]+' | grep -oE '[A-Z][A-Z0-9]+' | sort -u | head -2")
        if sites_output:
            # Filter out non-site values and extract clean site names
            sites = []
            for s in sites_output.split('\n'):
                s = s.strip()
                # Extract just the site name (e.g., DC1, DC2, SITE1, etc.)
                if s and s not in ['', '-', 'true', 'false', 'PREFER', 'SITE', 'TAKEOVER']:
                    # If it contains 'value=', extract just the value
                    if 'value=' in s:
                        s = s.split('value=')[-1].strip()
                    if s and len(s) <= 20:  # Reasonable site name length
                        sites.append(s)
            sites = list(dict.fromkeys(sites))  # Remove duplicates while preserving order
            if sites:
                hana_info['sites'] = sites
                if len(sites) >= 1:
                    hana_info['site1_name'] = sites[0]
                if len(sites) >= 2:
                    hana_info['site2_name'] = sites[1]

        # Get PREFER_SITE_TAKEOVER
        prefer_takeover = run_ssh_cmd("pcs resource config 2>/dev/null | grep -i 'PREFER_SITE_TAKEOVER' | grep -oE 'true|false' | head -1")
        if prefer_takeover:
            hana_info['prefer_site_takeover'] = prefer_takeover.lower() == 'true'

        # Get DUPLICATE_PRIMARY_TIMEOUT
        dup_timeout = run_ssh_cmd("pcs resource config 2>/dev/null | grep -i 'DUPLICATE_PRIMARY_TIMEOUT' | grep -oE '[0-9]+' | head -1")
        if dup_timeout:
            hana_info['duplicate_primary_timeout'] = int(dup_timeout)

        return hana_info

    def get_local_hostname(self) -> str:
        """Get the local hostname (short form)."""
        try:
            result = subprocess.run(
                ['hostname', '-s'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

        # Fallback to socket
        import socket
        return socket.gethostname().split('.')[0]

    def check_cluster_services_running(self, host: str = None, user: str = None) -> tuple:
        """
        Check if cluster services (pacemaker/corosync) are running.
        Returns tuple: (pacemaker_running, corosync_running, service_status_message)
        """
        if host:
            # Remote check via SSH
            ssh_user = user or 'root'
            sudo_prefix = "sudo " if ssh_user != 'root' else ""
            cmd = f"{sudo_prefix}systemctl is-active pacemaker corosync 2>/dev/null"
            try:
                ssh_cmd = [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                    "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{host}",
                    cmd
                ]
                result = subprocess.run(ssh_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        universal_newlines=True, timeout=self.SSH_TIMEOUT + 2)
                lines = result.stdout.strip().split('\n')
                pacemaker_active = len(lines) > 0 and lines[0].strip() == 'active'
                corosync_active = len(lines) > 1 and lines[1].strip() == 'active'
            except Exception:
                return (False, False, "Could not check service status")
        else:
            # Local check
            try:
                result = subprocess.run(
                    "systemctl is-active pacemaker corosync 2>/dev/null",
                    shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=5
                )
                lines = result.stdout.strip().split('\n')
                pacemaker_active = len(lines) > 0 and lines[0].strip() == 'active'
                corosync_active = len(lines) > 1 and lines[1].strip() == 'active'
            except Exception:
                return (False, False, "Could not check service status")

        if pacemaker_active and corosync_active:
            return (True, True, "Cluster services running")
        elif not pacemaker_active and not corosync_active:
            return (False, False, "Cluster is NOT running (pacemaker and corosync are stopped)")
        elif not pacemaker_active:
            return (False, corosync_active, "Pacemaker is NOT running")
        else:
            return (pacemaker_active, False, "Corosync is NOT running")

    def get_nodes_from_corosync_conf(self, host: str = None, user: str = None) -> List[str]:
        """
        Get cluster nodes from /etc/corosync/corosync.conf (static config).
        This works even when cluster services are not running.
        """
        nodes = []
        if host:
            # Remote read via SSH
            ssh_user = user or 'root'
            sudo_prefix = "sudo " if ssh_user != 'root' else ""
            cmd = f"{sudo_prefix}cat /etc/corosync/corosync.conf 2>/dev/null"
            try:
                ssh_cmd = [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                    "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{host}",
                    cmd
                ]
                result = subprocess.run(ssh_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        universal_newlines=True, timeout=self.SSH_TIMEOUT + 2)
                if result.returncode == 0:
                    content = result.stdout
                else:
                    return nodes
            except Exception:
                return nodes
        else:
            # Local read
            try:
                corosync_conf = Path("/etc/corosync/corosync.conf")
                if corosync_conf.exists():
                    content = corosync_conf.read_text()
                else:
                    return nodes
            except Exception:
                return nodes

        # Parse corosync.conf for node names
        # Look for ring0_addr or name in nodelist section
        name_matches = re.findall(r'^\s*name:\s*(\S+)', content, re.MULTILINE)
        if name_matches:
            nodes = name_matches
        else:
            ring_matches = re.findall(r'ring0_addr:\s*(\S+)', content)
            if ring_matches:
                nodes = ring_matches

        return nodes

    def discover_cluster_nodes_local(self) -> tuple:
        """
        Discover cluster members by running commands locally.
        Returns tuple: (cluster_name, list of cluster node hostnames)
        """
        cluster_nodes = []
        cluster_name = None
        cluster_running = True

        print("\n=== Discovering Cluster (local mode) ===")

        # Get local hostname
        self.local_hostname = self.get_local_hostname()
        print(f"  Local hostname: {self.local_hostname}")

        # Check if cluster services are running
        pacemaker_up, corosync_up, status_msg = self.check_cluster_services_running()
        if not pacemaker_up or not corosync_up:
            cluster_running = False
            print(f"\n  ⚠️  WARNING: {status_msg}")
            print("     Cluster commands will fail - falling back to static configuration")
            print("     To start the cluster: pcs cluster start --all\n")

        # Get cluster name locally
        name_commands = [
            "crm_attribute -G -n cluster-name -q 2>/dev/null",
            "pcs property show cluster-name 2>/dev/null | grep cluster-name | awk '{print $2}'",
            "corosync-cmapctl totem.cluster_name 2>/dev/null | cut -d= -f2 | tr -d ' '",
            "grep -oP 'cluster_name:\\s*\\K\\S+' /etc/corosync/corosync.conf 2>/dev/null",
        ]

        for cmd in name_commands:
            try:
                result = subprocess.run(
                    cmd, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=self.SSH_TIMEOUT
                )
                if result.returncode == 0 and result.stdout.strip():
                    name = result.stdout.strip()
                    if name and name != '(null)':
                        cluster_name = name
                        print(f"  Cluster name: {cluster_name}")
                        break
            except Exception:
                continue

        # Discover cluster nodes locally
        discovery_commands = [
            # Pacemaker commands (work on RHEL)
            "crm_node -l | awk '{print $2}'",
            "pcs status nodes | grep -E 'Online|Standby|Offline' | tr ' ' '\\n' | grep -v -E '^$|Online|Standby|Offline|:'",
            "corosync-cmapctl -b nodelist.node | grep 'ring0_addr' | cut -d= -f2 | tr -d ' '",
        ]

        for cmd in discovery_commands:
            try:
                result = subprocess.run(
                    cmd, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=self.SSH_TIMEOUT
                )
                if result.returncode == 0 and result.stdout.strip():
                    nodes = [n.strip() for n in result.stdout.strip().split('\n') if n.strip()]
                    if nodes:
                        cluster_nodes = nodes
                        if self.debug:
                            print(f"  [DEBUG] Found cluster nodes via: {cmd[:40]}...")
                        print(f"  Found {len(cluster_nodes)} cluster node(s): {', '.join(cluster_nodes)}")
                        break
            except Exception as e:
                if self.debug:
                    print(f"  [DEBUG] Command failed: {e}")
                continue

        if not cluster_nodes:
            # Try static fallback from corosync.conf
            static_nodes = self.get_nodes_from_corosync_conf()
            if static_nodes:
                cluster_nodes = static_nodes
                if not cluster_running:
                    print(f"  Found {len(cluster_nodes)} node(s) from corosync.conf: {', '.join(cluster_nodes)}")
                else:
                    print(f"  Found {len(cluster_nodes)} cluster node(s) (static): {', '.join(cluster_nodes)}")
            else:
                if not cluster_running:
                    print("  Could not discover cluster nodes (cluster not running, no corosync.conf)")
                else:
                    print("  Could not discover cluster nodes locally")
                print(f"  Using {self.local_hostname} as only node")
                cluster_nodes = [self.local_hostname]

        # Store cluster info
        if cluster_name:
            self.config.clusters[cluster_name] = {
                'nodes': cluster_nodes,
                'cluster_running': cluster_running,
                'discovered_from': self.local_hostname,
                'discovered_at': datetime.now().isoformat()
            }

        return cluster_name, cluster_nodes

    def discover_cluster_nodes(self, seed_host: str, user: str = None) -> tuple:
        """
        Discover cluster members by connecting to a seed node and querying the cluster.
        Tries multiple methods: crm_node, pcs status, corosync-cmapctl.
        Returns tuple: (cluster_name, list of cluster node hostnames)
        """
        ssh_user = user or 'root'
        # Use sudo for non-root users (cluster commands need root)
        sudo_prefix = "sudo " if ssh_user != 'root' else ""
        cluster_nodes = []
        cluster_name = None
        cluster_running = True

        print(f"\n=== Discovering Cluster from {seed_host} ===")

        # Check if cluster services are running on the seed host
        pacemaker_up, corosync_up, status_msg = self.check_cluster_services_running(seed_host, ssh_user)
        if not pacemaker_up or not corosync_up:
            cluster_running = False
            print(f"\n  ⚠️  WARNING: {status_msg}")
            print("     Cluster commands will fail - falling back to static configuration")
            print("     To start the cluster: pcs cluster start --all\n")

        # First get cluster name
        cluster_name = self.discover_cluster_name(seed_host, ssh_user)
        if cluster_name:
            print(f"  Cluster name: {cluster_name}")
        else:
            if self.debug:
                print("  [DEBUG] Could not determine cluster name")

        # Commands to try for discovering cluster nodes (RHEL)
        discovery_commands = [
            # crm_node (Pacemaker command)
            "crm_node -l | awk '{print $2}'",
            # pcs status (RHEL primary method)
            "pcs status nodes | grep -E 'Online|Standby|Offline' | tr ' ' '\\n' | grep -v -E '^$|Online|Standby|Offline|:'",
            # corosync-cmapctl
            "corosync-cmapctl -b nodelist.node | grep 'ring0_addr' | cut -d= -f2 | tr -d ' '",
        ]

        for cmd in discovery_commands:
            try:
                ssh_cmd = [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                    "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{seed_host}",
                    f"{sudo_prefix}{cmd}"
                ]
                result = subprocess.run(ssh_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        universal_newlines=True, timeout=self.SSH_TIMEOUT + 2)

                if result.returncode == 0 and result.stdout.strip():
                    nodes = [n.strip() for n in result.stdout.strip().split('\n') if n.strip()]
                    if nodes:
                        cluster_nodes = nodes
                        if self.debug:
                            print(f"  [DEBUG] Found cluster nodes via: {cmd[:40]}...")
                        print(f"  Found {len(cluster_nodes)} cluster node(s): {', '.join(cluster_nodes)}")
                        break
            except subprocess.TimeoutExpired:
                continue
            except Exception as e:
                if self.debug:
                    print(f"  [DEBUG] Command failed: {e}")
                continue

        if not cluster_nodes:
            # Try static fallback from corosync.conf on the remote host
            static_nodes = self.get_nodes_from_corosync_conf(seed_host, ssh_user)
            if static_nodes:
                cluster_nodes = static_nodes
                if not cluster_running:
                    print(f"  Found {len(cluster_nodes)} node(s) from corosync.conf: {', '.join(cluster_nodes)}")
                else:
                    print(f"  Found {len(cluster_nodes)} cluster node(s) (static): {', '.join(cluster_nodes)}")
            else:
                if not cluster_running:
                    print(f"  Could not discover cluster nodes (cluster not running, no corosync.conf)")
                else:
                    print(f"  Could not discover cluster nodes from {seed_host}")
                print(f"  Using {seed_host} as only node")
                cluster_nodes = [seed_host]

        # Discover SAP HANA info (pass cluster_nodes for node IP/FQDN discovery)
        hana_info = self.discover_hana_info(seed_host, ssh_user, cluster_nodes)
        if hana_info:
            sid = hana_info.get('sid', '')
            inst = hana_info.get('instance_number', '')
            vip = hana_info.get('virtual_ip', '')
            if sid:
                print(f"  SAP HANA SID: {sid}, Instance: {inst}")
            if vip:
                print(f"  Virtual IP: {vip}")

        # Store cluster info
        if cluster_name:
            cluster_data = {
                'nodes': cluster_nodes,
                'cluster_running': cluster_running,
                'discovered_from': seed_host,
                'discovered_at': datetime.now().isoformat()
            }
            # Add HANA info if discovered
            if hana_info:
                cluster_data.update(hana_info)
            self.config.clusters[cluster_name] = cluster_data

        return cluster_name, cluster_nodes

    def check_ssh_access(self, hostname: str, user: str = None) -> tuple:
        """Check SSH access to a host. Returns (reachable, user)."""
        users_to_try = [user] if user else ['root', os.environ.get('USER', 'root')]

        for try_user in users_to_try:
            if try_user is None:
                continue
            try:
                cmd = [
                    "ssh", "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                    "-o", "StrictHostKeyChecking=no",
                    f"{try_user}@{hostname}",
                    "echo ok"
                ]
                result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=self.SSH_TIMEOUT + 2)
                if result.returncode == 0 and "ok" in result.stdout:
                    return True, try_user
                elif self.debug:
                    print(f"    [DEBUG] SSH {try_user}@{hostname} failed: {result.stderr.strip()[:60]}")
            except subprocess.TimeoutExpired:
                if self.debug:
                    print(f"    [DEBUG] SSH {try_user}@{hostname} timed out")
            except Exception as e:
                if self.debug:
                    print(f"    [DEBUG] SSH {try_user}@{hostname} error: {e}")

        return False, None

    def get_machine_id(self, hostname: str, user: str = None) -> Optional[str]:
        """Get the machine ID from a remote host via SSH."""
        ssh_user = user or 'root'
        try:
            cmd = [
                "ssh", "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={self.SSH_TIMEOUT}",
                "-o", "StrictHostKeyChecking=no",
                f"{ssh_user}@{hostname}",
                "cat /etc/machine-id 2>/dev/null || hostid"
            ]
            result = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=self.SSH_TIMEOUT + 2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[:32]  # machine-id is 32 chars
        except Exception as e:
            if self.debug:
                print(f"    [DEBUG] Failed to get machine-id from {hostname}: {e}")
        return None

    def get_machine_id_ansible(self, hostname: str) -> Optional[str]:
        """Get the machine ID from a remote host via Ansible."""
        try:
            cmd = [
                "ansible", hostname, "-m", "shell",
                "-a", "cat /etc/machine-id 2>/dev/null || hostid",
                "--one-line"
            ]
            result = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                # Ansible output format: "hostname | SUCCESS | rc=0 >> <output>"
                output = result.stdout.strip()
                if '>>' in output:
                    machine_id = output.split('>>')[-1].strip()
                    return machine_id[:32]
        except Exception as e:
            if self.debug:
                print(f"    [DEBUG] Failed to get machine-id via Ansible from {hostname}: {e}")
        return None

    def get_machine_id_sosreport(self, sosreport_path: str) -> Optional[str]:
        """Get the machine ID from a SOSreport."""
        try:
            sos_path = Path(sosreport_path)
            machine_id_file = sos_path / "etc/machine-id"
            if machine_id_file.exists():
                return machine_id_file.read_text().strip()[:32]
        except Exception as e:
            if self.debug:
                print(f"    [DEBUG] Failed to get machine-id from SOSreport: {e}")
        return None

    def check_ansible_access(self, hostname: str, ansible_host: str = None,
                            ansible_user: str = None) -> bool:
        """Check Ansible access to a host using ansible ping."""
        try:
            cmd = ["ansible", hostname, "-m", "ping", "-o"]
            if self.config.ansible_inventory_path:
                cmd.extend(["-i", self.config.ansible_inventory_path])

            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
            return "SUCCESS" in result.stdout
        except Exception:
            return False

    def check_node_access(self, hostname: str, ansible_info: dict = None,
                         sosreport_path: str = None) -> NodeAccess:
        """Check all access methods for a single node (thread-safe)."""
        node = NodeAccess(hostname=hostname)
        node.last_checked = datetime.now().isoformat()

        # Check SSH access (preferred)
        ssh_user = ansible_info.get('ansible_user') if ansible_info else None
        ssh_host = ansible_info.get('ansible_host', hostname) if ansible_info else hostname
        node.ssh_reachable, node.ssh_user = self.check_ssh_access(ssh_host, ssh_user)

        # If SSH is reachable, get the machine ID for verification
        if node.ssh_reachable:
            node.machine_id = self.get_machine_id(ssh_host, node.ssh_user)

        # Check Ansible access
        if ansible_info:
            node.ansible_host = ansible_info.get('ansible_host')
            node.ansible_user = ansible_info.get('ansible_user')
            if not node.ssh_reachable:  # Only check Ansible if SSH failed
                node.ansible_reachable = self.check_ansible_access(hostname,
                    node.ansible_host, node.ansible_user)
                # Get machine ID via Ansible if SSH failed
                if node.ansible_reachable:
                    node.machine_id = self.get_machine_id_ansible(hostname)

        # Record SOSreport path
        if sosreport_path:
            node.sosreport_path = sosreport_path
            # Try to get machine ID from SOSreport
            if not node.machine_id:
                node.machine_id = self.get_machine_id_sosreport(sosreport_path)

        # Determine preferred access method
        if node.ssh_reachable:
            node.preferred_method = 'ssh'
        elif node.ansible_reachable:
            node.preferred_method = 'ansible'
        elif node.sosreport_path:
            node.preferred_method = 'sosreport'

        return node

    def discover_all(self) -> AccessConfig:
        """
        Main discovery routine - discovers all access methods using multithreading.
        """
        print("=" * 60)
        print("SAP Pacemaker Cluster - Access Discovery")
        print("=" * 60)

        # Handle local mode - running on the cluster node itself
        if self.local_mode:
            return self._discover_local_mode()

        # Collect all hosts from different sources
        all_hosts = {}  # hostname -> {ansible_info, sosreport_path}
        file_hosts = []

        # 0. If SOSreport directory specified, discover SOSreports FIRST and use ONLY those nodes
        if self.sosreport_dir:
            # Use cluster-aware discovery
            clusters = self.discover_sosreports_with_clusters()

            if clusters:
                # Determine which sosreports to use
                sosreports = {}

                if len(clusters) > 1:
                    # Multiple clusters detected - prompt for selection
                    selected_cluster = self.prompt_cluster_selection(clusters)

                    if selected_cluster is None:
                        print("\n[INFO] Cluster selection cancelled.")
                        sys.exit(0)
                    elif selected_cluster == '__all__':
                        # Use all sosreports
                        print(f"\n[INFO] Analyzing all {len(clusters)} clusters together")
                        for cluster_info in clusters.values():
                            sosreports.update(cluster_info['nodes'])
                    else:
                        # Use only selected cluster's sosreports
                        sosreports = clusters[selected_cluster]['nodes']
                        print(f"\n[INFO] Analyzing cluster '{selected_cluster}' only")
                        # Store cluster info
                        self.config.clusters[selected_cluster] = {
                            'nodes': list(sosreports.keys()),
                            'discovered_from': 'sosreport',
                            'discovered_at': datetime.now().isoformat()
                        }
                else:
                    # Single cluster - use all sosreports
                    cluster_name = list(clusters.keys())[0]
                    sosreports = clusters[cluster_name]['nodes']
                    if cluster_name != '(unknown)':
                        print(f"\n[INFO] Single cluster detected: {cluster_name}")
                        self.config.clusters[cluster_name] = {
                            'nodes': list(sosreports.keys()),
                            'discovered_from': 'sosreport',
                            'discovered_at': datetime.now().isoformat()
                        }

                if sosreports:
                    print(f"\n[INFO] SOSreport mode: {len(sosreports)} SOSreport(s) found")

                    # Check if cluster was running when SOSreports were captured
                    cluster_was_down = False
                    for hostname, sos_path in sosreports.items():
                        was_running, reason = self.was_cluster_running_in_sosreport(sos_path)
                        if not was_running:
                            cluster_was_down = True
                            print(f"\n  ⚠️  WARNING: Cluster was NOT running when {hostname}'s SOSreport was captured")
                            print(f"     Reason: {reason}")
                            print("     Some health check results may be incomplete or show errors")
                            print("     Consider creating new SOSreports with cluster running\n")
                            break  # Only warn once

                    # Extract all expected cluster nodes from corosync.conf
                    expected_nodes = set()
                    for hostname, sos_path in sosreports.items():
                        nodes_in_cluster = self.get_cluster_nodes_from_sosreport(sos_path)
                        if nodes_in_cluster:
                            expected_nodes.update(nodes_in_cluster)

                    # Add the SOSreport hostnames too (in case extraction failed)
                    expected_nodes.update(sosreports.keys())

                    # Find nodes we don't have SOSreports for
                    missing_sosreports = expected_nodes - set(sosreports.keys())

                    if missing_sosreports:
                        print(f"\n[INFO] Cluster has {len(expected_nodes)} nodes, but only {len(sosreports)} SOSreport(s)")
                        print(f"       Missing SOSreports for: {', '.join(sorted(missing_sosreports))}")
                        print("       Attempting SSH access to get live data...")

                    # Clear old nodes
                    self.config.nodes = {}

                    # Add nodes with SOSreports
                    for hostname, path in sosreports.items():
                        all_hosts[hostname] = {'ansible_info': None, 'sosreport_path': path}

                    # Add nodes without SOSreports (will try SSH)
                    for hostname in missing_sosreports:
                        all_hosts[hostname] = {'ansible_info': None, 'sosreport_path': None}

                    # Check access to all nodes (parallel)
                    print(f"\n=== Checking access to {len(all_hosts)} cluster node(s) ===")
                    with ThreadPoolExecutor(max_workers=min(len(all_hosts), self.MAX_WORKERS)) as executor:
                        futures = {
                            executor.submit(self.check_node_access, hostname, None, info.get('sosreport_path')): hostname
                            for hostname, info in all_hosts.items()
                        }
                        for future in as_completed(futures):
                            hostname = futures[future]
                            try:
                                node = future.result()
                                self.config.nodes[hostname] = asdict(node)
                                if node.sosreport_path and node.ssh_reachable:
                                    print(f"  {hostname}: SOSreport + SSH({node.ssh_user}) -> ssh (live)")
                                elif node.sosreport_path:
                                    print(f"  {hostname}: SOSreport -> sosreport")
                                elif node.ssh_reachable:
                                    print(f"  {hostname}: SSH({node.ssh_user}) -> ssh (live)")
                                else:
                                    print(f"  {hostname}: NO ACCESS")
                            except Exception as e:
                                print(f"  {hostname}: Error - {e}")

                    self.config.sosreport_directory = self.sosreport_dir
                    self.config.discovery_complete = True
                    self.save_config()
                    self._print_summary()
                    return self.config

        # 1. Check if cluster name specified - use saved cluster nodes
        if self.cluster_name:
            if self.cluster_name in self.config.clusters:
                cluster_info = self.config.clusters[self.cluster_name]
                file_hosts = cluster_info.get('nodes', [])
                print(f"\n=== Using saved cluster: {self.cluster_name} ===")
                print(f"  Nodes: {', '.join(file_hosts)}")
                print(f"  Discovered from: {cluster_info.get('discovered_from', 'unknown')}")
                # Clear old nodes - only check this cluster's nodes
                self.config.nodes = {}
            else:
                print(f"\n[WARNING] Cluster '{self.cluster_name}' not found in config")
                print(f"  Known clusters: {', '.join(self.config.clusters.keys()) or '(none)'}")
                print("  Run with a node name first to discover the cluster")

        # 2. Get hosts from file/command line
        if not file_hosts:
            file_hosts = self.get_hosts_from_file()
            if file_hosts:
                # Hosts specified on command line - clear old nodes, only check these
                print("\n[INFO] Host mode: analyzing only specified hosts")
                self.config.nodes = {}

        # 3. If hosts specified, try to discover cluster members from first reachable host
        if file_hosts and not self.cluster_name:
            if self.debug:
                print("  [DEBUG] Hosts specified, attempting cluster auto-discovery")

            # Try to discover cluster nodes from the first specified host
            for seed_host in file_hosts:
                # Quick SSH check
                reachable, ssh_user = self.check_ssh_access(seed_host)
                if reachable:
                    # Discover cluster members (returns cluster_name, nodes)
                    discovered_name, cluster_nodes = self.discover_cluster_nodes(seed_host, ssh_user)
                    # Only use discovered nodes if we found more than what was specified
                    # or if we successfully discovered the cluster
                    if cluster_nodes and len(cluster_nodes) >= len(file_hosts):
                        file_hosts = cluster_nodes
                    elif not cluster_nodes or len(cluster_nodes) < len(file_hosts):
                        # Cluster discovery failed or incomplete, keep original hosts
                        if self.debug:
                            print(f"  [DEBUG] Cluster discovery incomplete, keeping specified hosts")
                    break
                else:
                    if self.debug:
                        print(f"  [DEBUG] {seed_host} not reachable, trying next...")

        # 3. Discover Ansible inventory (skip if hosts provided)
        if not self.skip_ansible and not file_hosts:
            self.discover_ansible_inventory()
            ansible_hosts = self.get_ansible_hosts()

            # Filter by group if specified
            if self.ansible_group:
                filtered_hosts = {}
                for hostname, info in ansible_hosts.items():
                    groups = info.get('groups', [])
                    if self.ansible_group in groups or self.ansible_group == 'all':
                        filtered_hosts[hostname] = info
                if self.debug:
                    print(f"  [DEBUG] Filtered to group '{self.ansible_group}': {len(filtered_hosts)} hosts")
                ansible_hosts = filtered_hosts

            for hostname, info in ansible_hosts.items():
                all_hosts[hostname] = {'ansible_info': info, 'sosreport_path': None}

        # 4. Add hosts from file/cluster discovery
        for hostname in file_hosts:
            if hostname not in all_hosts:
                all_hosts[hostname] = {'ansible_info': None, 'sosreport_path': None}

        # 3. Discover SOSreports
        sosreports = self.discover_sosreports()
        for hostname, path in sosreports.items():
            if hostname in all_hosts:
                all_hosts[hostname]['sosreport_path'] = path
            else:
                all_hosts[hostname] = {'ansible_info': None, 'sosreport_path': path}

        if not all_hosts:
            print("\nNo hosts discovered. Please provide:")
            print("  - Ansible inventory (ansible.cfg or $ANSIBLE_INVENTORY)")
            print("  - Hosts file (--hosts-file)")
            print("  - SOSreport directory (--sosreport-dir)")
            return self.config

        # 4. Check access to all hosts using thread pool
        print(f"\n=== Checking access to {len(all_hosts)} hosts (multithreaded) ===")

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {}
            for hostname, info in all_hosts.items():
                future = executor.submit(
                    self.check_node_access,
                    hostname,
                    info.get('ansible_info'),
                    info.get('sosreport_path')
                )
                futures[future] = hostname

            for future in as_completed(futures):
                hostname = futures[future]
                try:
                    node = future.result()
                    self.config.nodes[hostname] = asdict(node)
                    status = []
                    if node.ssh_reachable:
                        status.append(f"SSH({node.ssh_user})")
                    if node.ansible_reachable:
                        status.append("Ansible")
                    if node.sosreport_path:
                        status.append("SOSreport")
                    machine_id_short = f" [{node.machine_id[:8]}]" if node.machine_id else ""
                    print(f"  {hostname}: {', '.join(status) if status else 'NO ACCESS'}{machine_id_short} "
                          f"-> {node.preferred_method or 'none'}")
                except Exception as e:
                    print(f"  {hostname}: Error - {e}")

        # Scan for SOSreports in subdirectories and update nodes without sosreport_path
        local_sosreports = self.scan_sosreports_recursive(str(self.config_dir))
        if local_sosreports:
            updated_count = 0
            for hostname, node_info in self.config.nodes.items():
                if not node_info.get('sosreport_path') and hostname in local_sosreports:
                    node_info['sosreport_path'] = local_sosreports[hostname]
                    # Set preferred_method to sosreport if no other access method
                    if not node_info.get('preferred_method'):
                        node_info['preferred_method'] = 'sosreport'
                    updated_count += 1
            if updated_count > 0:
                print(f"\n  [INFO] Found {updated_count} matching SOSreport(s) in subdirectories")

            # Discover cluster nodes from SOSreports and find their sosreports
            discovered_nodes = self._discover_cluster_from_sosreports(local_sosreports)
            if discovered_nodes:
                for hostname, sos_path in discovered_nodes.items():
                    if hostname not in self.config.nodes:
                        node_info = {
                            'hostname': hostname,
                            'sosreport_path': sos_path,
                            'preferred_method': 'sosreport',
                            'last_checked': datetime.now().isoformat()
                        }
                        self.config.nodes[hostname] = node_info
                        print(f"  [CLUSTER] Discovered {hostname} from SOSreport cluster info")

        # Check if multiple clusters were discovered - prompt for selection
        if len(self.config.clusters) > 1:
            # Build clusters dict in format expected by prompt_cluster_selection
            clusters_for_selection = {}
            for cname, cinfo in self.config.clusters.items():
                if cname == '(unknown)':
                    continue
                cluster_nodes_list = cinfo.get('nodes', [])
                # Map nodes to their info
                nodes_dict = {}
                for node in cluster_nodes_list:
                    if node in self.config.nodes:
                        nodes_dict[node] = self.config.nodes[node].get('sosreport_path', '')
                    else:
                        nodes_dict[node] = ''
                if nodes_dict:
                    clusters_for_selection[cname] = {'nodes': nodes_dict}

            if len(clusters_for_selection) > 1:
                print("\n" + "=" * 60)
                print(" Multiple clusters discovered from hosts")
                print("=" * 60)
                selected_cluster = self.prompt_cluster_selection(clusters_for_selection)

                if selected_cluster is None:
                    print("\n[INFO] Cluster selection cancelled.")
                    sys.exit(0)
                elif selected_cluster != '__all__':
                    # Filter to only selected cluster's nodes
                    selected_nodes = self.config.clusters[selected_cluster].get('nodes', [])
                    filtered_nodes = {n: self.config.nodes[n] for n in selected_nodes if n in self.config.nodes}

                    print(f"\n[INFO] Analyzing cluster '{selected_cluster}' only")
                    print(f"       Nodes: {', '.join(sorted(filtered_nodes.keys()))}")

                    # Remove nodes not in selected cluster
                    self.config.nodes = filtered_nodes
                    # Keep only selected cluster
                    self.config.clusters = {selected_cluster: self.config.clusters[selected_cluster]}

        self.config.discovery_complete = True
        self.save_config()

        # Print summary
        self._print_summary()

        return self.config

    def _discover_local_mode(self) -> AccessConfig:
        """
        Discovery routine for local mode - running on the cluster node itself.
        The local node uses direct command execution, other nodes use SSH.
        """
        print("\n[INFO] Local mode: running on cluster node")

        # Clear old nodes for fresh discovery
        self.config.nodes = {}

        # Discover cluster nodes locally
        cluster_name, cluster_nodes = self.discover_cluster_nodes_local()

        if not cluster_nodes:
            print("[ERROR] Could not discover any cluster nodes")
            return self.config

        # Get local hostname
        local_hostname = self.local_hostname or self.get_local_hostname()

        print(f"\n=== Checking access to {len(cluster_nodes)} cluster node(s) ===")

        # Process each node
        for node_name in cluster_nodes:
            if node_name == local_hostname:
                # Local node - use local execution
                node = NodeAccess(hostname=node_name)
                node.last_checked = datetime.now().isoformat()
                node.preferred_method = 'local'
                self.config.nodes[node_name] = asdict(node)
                print(f"  {node_name}: LOCAL (this node)")
            else:
                # Remote node - check SSH access
                node = self.check_node_access(node_name, None, None)
                self.config.nodes[node_name] = asdict(node)
                status = []
                if node.ssh_reachable:
                    status.append(f"SSH({node.ssh_user})")
                machine_id_short = f" [{node.machine_id[:8]}]" if node.machine_id else ""
                print(f"  {node_name}: {', '.join(status) if status else 'NO ACCESS'}{machine_id_short} "
                      f"-> {node.preferred_method or 'none'}")

        self.config.discovery_complete = True
        self.save_config()

        # Print summary
        self._print_summary()

        return self.config

    def _print_summary(self):
        """Print discovery summary."""
        print("\n" + "=" * 60)
        print("Discovery Summary")
        print("=" * 60)

        total = len(self.config.nodes)
        local_count = sum(1 for n in self.config.nodes.values() if n.get('preferred_method') == 'local')
        ssh_count = sum(1 for n in self.config.nodes.values() if n.get('ssh_reachable'))
        ansible_count = sum(1 for n in self.config.nodes.values() if n.get('ansible_reachable'))
        sos_count = sum(1 for n in self.config.nodes.values() if n.get('sosreport_path'))
        no_access = sum(1 for n in self.config.nodes.values() if not n.get('preferred_method'))

        print(f"Total nodes:      {total}")
        if local_count > 0:
            print(f"Local (this node):{local_count}")
        print(f"SSH accessible:   {ssh_count}")
        print(f"Ansible access:   {ansible_count}")
        print(f"SOSreport avail:  {sos_count}")
        print(f"No access:        {no_access}")
        print(f"\nConfig saved to: {self.config_path}")

        if self.config.ansible_inventory_path:
            print(f"Ansible inventory: {self.config.ansible_inventory_path}")
            print(f"  (source: {self.config.ansible_inventory_source})")


def show_config(config_path: Path, cluster_or_node: str = None):
    """Display the current configuration in a user-friendly format.

    Args:
        config_path: Path to the configuration file
        cluster_or_node: Optional cluster name or hostname to filter output.
                         If a cluster name is provided, shows that cluster.
                         If a hostname is provided, shows the cluster containing that node.
    """
    if not config_path.exists():
        print(f"No configuration file found at {config_path}")
        print("\nRun discovery first:")
        print("  ./cluster_health_check.py hana01")
        return False

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    clusters = config.get('clusters', {})
    all_nodes = config.get('nodes', {})

    # Resolve cluster_or_node to a cluster name
    cluster_name = None
    if cluster_or_node:
        # First, check if it's a cluster name
        if cluster_or_node in clusters:
            cluster_name = cluster_or_node
        else:
            # Check if it's a hostname - find which cluster contains it
            for cname, cinfo in clusters.items():
                if cluster_or_node in cinfo.get('nodes', []):
                    cluster_name = cname
                    print(f"[INFO] Node '{cluster_or_node}' belongs to cluster '{cluster_name}'")
                    break

            if not cluster_name:
                # Not found as cluster or node in any cluster
                if cluster_or_node in all_nodes:
                    # It's a known node but not in any cluster
                    print(f"\n[INFO] Node '{cluster_or_node}' found but not assigned to any cluster")
                else:
                    print(f"\n[ERROR] '{cluster_or_node}' not found as cluster or node")

                if clusters:
                    print(f"\nAvailable clusters: {', '.join(clusters.keys())}")
                    print(f"Available nodes: {', '.join(list(all_nodes.keys())[:10])}", end='')
                    if len(all_nodes) > 10:
                        print(f" ... and {len(all_nodes) - 10} more")
                    else:
                        print()
                    print("\nTo show all configuration:")
                    print("  ./cluster_health_check.py --show-config")
                else:
                    print("\nNo clusters discovered yet. Run discovery first:")
                    print("  ./cluster_health_check.py hana01")
                return False

    print("\n" + "=" * 60)
    if cluster_name:
        print(f" SAP Cluster Health Check - Cluster: {cluster_name}")
    else:
        print(" SAP Cluster Health Check - Configuration")
    print("=" * 60)
    print(f"Config file: {config_path}")

    # Show clusters (filtered if cluster_name specified)
    if clusters:
        clusters_to_show = {cluster_name: clusters[cluster_name]} if cluster_name else clusters

        if cluster_name:
            print(f"\n--- Cluster: {cluster_name} ---")
        else:
            print("\n--- Discovered Clusters ---")

        for name, info in clusters_to_show.items():
            cluster_nodes = info.get('nodes', [])
            discovered_from = info.get('discovered_from', 'unknown')
            if not cluster_name:
                print(f"\n  Cluster: {name}")
            print(f"    Nodes: {', '.join(cluster_nodes)}")
            print(f"    Discovered from: {discovered_from}")

            # Show SAP HANA info if available (Ansible-compatible parameters)
            sid = info.get('sid')
            if sid:
                inst = info.get('instance_number', '??')
                resource_type = info.get('resource_type', 'SAPHana')

                print("\n    SAP HANA HA Configuration (Ansible-compatible):")
                print("    " + "-" * 40)

                # Cluster name and nodes
                print(f"      cluster_name: {name}")
                print(f"      cluster_nodes: [{', '.join(cluster_nodes)}]")

                # Core Parameters
                print(f"      hana_sid: {sid}")
                print(f"      hana_instance_number: \"{inst}\"")

                # Cluster type
                cluster_type = "Scale-Up" if resource_type == "SAPHana" else "Scale-Out"
                print(f"      cluster_type: {cluster_type}")

                # Node Information
                node1_fqdn = info.get('node1_fqdn', '')
                node1_ip = info.get('node1_ip', '')
                node2_fqdn = info.get('node2_fqdn', '')
                node2_ip = info.get('node2_ip', '')
                if node1_fqdn or node1_ip:
                    print("\n      # Node 1")
                    if node1_fqdn:
                        print(f"      node1_fqdn: {node1_fqdn}")
                    if node1_ip:
                        print(f"      node1_ip: {node1_ip}")
                if node2_fqdn or node2_ip:
                    print("\n      # Node 2")
                    if node2_fqdn:
                        print(f"      node2_fqdn: {node2_fqdn}")
                    if node2_ip:
                        print(f"      node2_ip: {node2_ip}")

                # Virtual IP
                virtual_ip = info.get('virtual_ip', '')
                vip_resource = info.get('vip_resource', '')
                secondary_vip = info.get('secondary_vip', '')
                if virtual_ip:
                    print("\n      # Virtual IP Configuration")
                    print(f"      vip: {virtual_ip}")
                    if vip_resource:
                        print(f"      vip_resource: {vip_resource}")
                    if secondary_vip:
                        print(f"      secondary_vip: {secondary_vip}")
                        print("      secondary_read: true")

                # System Replication
                repl_mode = info.get('replication_mode', '')
                op_mode = info.get('operation_mode', '')
                sites = info.get('sites', [])
                site1 = info.get('site1_name', '')
                site2 = info.get('site2_name', '')
                if repl_mode or op_mode or sites:
                    print("\n      # System Replication")
                    if repl_mode:
                        print(f"      replication_mode: {repl_mode}")
                    if op_mode:
                        print(f"      operation_mode: {op_mode}")
                    if site1:
                        print(f"      site1_name: {site1}")
                    if site2:
                        print(f"      site2_name: {site2}")
                    elif sites:
                        print(f"      sites: {', '.join(sites)}")

                # Resource Names
                resource_name = info.get('resource_name', '')
                topology_resource = info.get('topology_resource', '')
                if resource_name or topology_resource:
                    print("\n      # Pacemaker Resources")
                    if resource_name:
                        print(f"      hana_resource: {resource_name}")
                    if topology_resource:
                        print(f"      topology_resource: {topology_resource}")

                # STONITH
                stonith_device = info.get('stonith_device', '')
                stonith_type = info.get('stonith_type', '')
                if stonith_device:
                    print("\n      # STONITH/Fencing")
                    print(f"      stonith_device: {stonith_device}")
                    if stonith_type:
                        print(f"      stonith_type: {stonith_type}")

                # Cluster Properties
                stickiness = info.get('resource_stickiness')
                migration = info.get('migration_threshold')
                auto_reg = info.get('automated_register')
                prefer_takeover = info.get('prefer_site_takeover')
                if stickiness or migration or auto_reg is not None or prefer_takeover is not None:
                    print("\n      # Cluster Properties")
                    if stickiness:
                        print(f"      resource_stickiness: {stickiness}")
                    if migration:
                        print(f"      migration_threshold: {migration}")
                    if auto_reg is not None:
                        print(f"      automated_register: {str(auto_reg).lower()}")
                    if prefer_takeover is not None:
                        print(f"      prefer_site_takeover: {str(prefer_takeover).lower()}")

            print("\n    To check this cluster:")
            print(f"      ./cluster_health_check.py -C {name}")
    else:
        print("\n[INFO] No clusters discovered yet")
        print("  Run: ./cluster_health_check.py hana01")

    # Show node summary (filtered to cluster nodes if cluster_name specified)
    if cluster_name and cluster_name in clusters:
        cluster_node_names = clusters[cluster_name].get('nodes', [])
        nodes = {n: all_nodes[n] for n in cluster_node_names if n in all_nodes}
        node_label = f"Nodes in Cluster '{cluster_name}'"
    else:
        nodes = all_nodes
        node_label = "All Discovered Nodes"

    if nodes:
        print(f"\n--- {node_label} ({len(nodes)}) ---")
        accessible = [n for n, info in nodes.items() if info.get('preferred_method')]
        no_access = [n for n, info in nodes.items() if not info.get('preferred_method')]

        if accessible:
            print(f"\n  Accessible ({len(accessible)}):")
            for name in sorted(accessible)[:10]:  # Show first 10
                info = nodes[name]
                method = info.get('preferred_method', 'none')
                machine_id = info.get('machine_id', '')
                machine_id_short = f" [{machine_id[:8]}]" if machine_id else ""
                print(f"    {name}: {method}{machine_id_short}")
            if len(accessible) > 10:
                print(f"    ... and {len(accessible) - 10} more")

        if no_access:
            print(f"\n  No access ({len(no_access)}): {', '.join(sorted(no_access)[:5])}", end='')
            if len(no_access) > 5:
                print(f" ... and {len(no_access) - 5} more")
            else:
                print()

    # Show other config (only in full view, not cluster-specific)
    if not cluster_name:
        if config.get('sosreport_directory'):
            print("\n--- SOSreport Directory ---")
            print(f"  {config['sosreport_directory']}")

        if config.get('ansible_inventory_path'):
            print("\n--- Ansible Inventory ---")
            print(f"  Path: {config['ansible_inventory_path']}")
            print(f"  Source: {config.get('ansible_inventory_source', 'unknown')}")

    print("\n--- Quick Commands ---")
    if cluster_name:
        print(f"  Check cluster:    ./cluster_health_check.py -C {cluster_name}")
        print("  Show all config:  ./cluster_health_check.py --show-config")
    elif clusters:
        first_cluster = list(clusters.keys())[0]
        print(f"  Check cluster:    ./cluster_health_check.py -C {first_cluster}")
        print(f"  Show one cluster: ./cluster_health_check.py --show-config {first_cluster}")
    print("  Force rediscover: ./cluster_health_check.py -f hana01")
    print("  Delete config:    ./cluster_health_check.py -D")
    print("  Show guide:       ./cluster_health_check.py --guide")

    return True


def export_ansible_vars(config_path: Path, cluster_name: str, output_file: str = None):
    """
    Export cluster configuration as Ansible group_vars YAML file.

    Args:
        config_path: Path to the configuration file
        cluster_name: Name of the cluster to export
        output_file: Optional output file path. If not provided, prints to stdout.
    """
    if not config_path.exists():
        print(f"No configuration file found at {config_path}")
        return False

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    clusters = config.get('clusters', {})

    if cluster_name not in clusters:
        print(f"Cluster '{cluster_name}' not found in configuration.")
        print(f"Available clusters: {', '.join(clusters.keys())}")
        return False

    info = clusters[cluster_name]
    cluster_nodes = info.get('nodes', [])
    sid = info.get('sid', '')

    if not sid:
        print(f"No SAP HANA configuration found for cluster '{cluster_name}'.")
        print("Run discovery with: ./cluster_health_check.py -f <node>")
        return False

    # Build Ansible vars dictionary
    ansible_vars = {
        '# SAP HANA HA Pacemaker Configuration': None,
        f'# Cluster: {cluster_name}': None,
        f'# Generated from: {config_path}': None,
        '': None,
        '# Core SAP HANA Parameters': None,
        'sap_hana_ha_pacemaker_hana_sid': sid,
        'sap_hana_ha_pacemaker_hana_instance_number': f'"{info.get("instance_number", "00")}"',
    }

    # Cluster name
    ansible_vars['sap_hana_ha_pacemaker_cluster_name'] = cluster_name

    # Node information
    if len(cluster_nodes) >= 2:
        ansible_vars['\n# Cluster Node Information'] = None
        node1_fqdn = info.get('node1_fqdn', cluster_nodes[0])
        node1_ip = info.get('node1_ip', '')
        node2_fqdn = info.get('node2_fqdn', cluster_nodes[1])
        node2_ip = info.get('node2_ip', '')

        ansible_vars['sap_hana_ha_pacemaker_node1_fqdn'] = node1_fqdn
        if node1_ip:
            ansible_vars['sap_hana_ha_pacemaker_node1_ip'] = node1_ip
        ansible_vars['sap_hana_ha_pacemaker_node2_fqdn'] = node2_fqdn
        if node2_ip:
            ansible_vars['sap_hana_ha_pacemaker_node2_ip'] = node2_ip

    # Virtual IP
    vip = info.get('virtual_ip', '')
    if vip:
        ansible_vars['\n# Virtual IP Configuration'] = None
        ansible_vars['sap_hana_ha_pacemaker_vip'] = vip
        secondary_vip = info.get('secondary_vip', '')
        if secondary_vip:
            ansible_vars['sap_hana_ha_pacemaker_secondary_vip'] = secondary_vip
            ansible_vars['sap_hana_ha_pacemaker_secondary_read'] = 'true'

    # Cluster password placeholder
    ansible_vars['\n# Pacemaker & HA Service Setup'] = None
    ansible_vars['sap_hana_ha_pacemaker_hacluster_password'] = '"{{ vault_hacluster_password }}"  # Store in Ansible Vault'

    # System Replication
    repl_mode = info.get('replication_mode', '')
    op_mode = info.get('operation_mode', '')
    site1 = info.get('site1_name', '')
    site2 = info.get('site2_name', '')
    if repl_mode or op_mode or site1:
        ansible_vars['\n# SAP HANA System Replication'] = None
        if repl_mode:
            ansible_vars['sap_hana_ha_pacemaker_replication_mode'] = repl_mode
        if op_mode:
            ansible_vars['sap_hana_ha_pacemaker_operation_mode'] = op_mode
        if site1:
            ansible_vars['sap_hana_ha_pacemaker_site1_name'] = site1
        if site2:
            ansible_vars['sap_hana_ha_pacemaker_site2_name'] = site2

    # Cluster Properties
    auto_reg = info.get('automated_register')
    prefer_takeover = info.get('prefer_site_takeover')
    stickiness = info.get('resource_stickiness')
    migration = info.get('migration_threshold')
    if auto_reg is not None or prefer_takeover is not None or stickiness or migration:
        ansible_vars['\n# Cluster Properties'] = None
        if auto_reg is not None:
            ansible_vars['sap_hana_ha_pacemaker_automated_register'] = str(auto_reg).lower()
        if prefer_takeover is not None:
            ansible_vars['sap_hana_ha_pacemaker_prefer_site_takeover'] = str(prefer_takeover).lower()
        if stickiness:
            ansible_vars['sap_hana_ha_pacemaker_resource_stickiness'] = stickiness
        if migration:
            ansible_vars['sap_hana_ha_pacemaker_migration_threshold'] = migration

    # STONITH
    stonith = info.get('stonith_device', '')
    stonith_type = info.get('stonith_type', '')
    if stonith:
        ansible_vars['\n# STONITH/Fencing Configuration'] = None
        ansible_vars['sap_hana_ha_pacemaker_stonith_device'] = stonith
        if stonith_type:
            ansible_vars['sap_hana_ha_pacemaker_stonith_type'] = stonith_type
        ansible_vars['# Add fencing credentials as needed:'] = None
        ansible_vars['# sap_hana_ha_pacemaker_fence_user'] = '"{{ vault_fence_user }}"'
        ansible_vars['# sap_hana_ha_pacemaker_fence_password'] = '"{{ vault_fence_password }}"'

    # Format output
    output_lines = ['---']
    for key, value in ansible_vars.items():
        if key.startswith('#') or key.startswith('\n#'):
            output_lines.append(key.lstrip('\n'))
        elif key == '':
            output_lines.append('')
        elif value is None:
            continue
        else:
            output_lines.append(f'{key}: {value}')

    yaml_content = '\n'.join(output_lines)

    if output_file:
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            f.write(yaml_content + '\n')
        print(f"Ansible vars exported to: {output_path}")
        print("\nUsage:")
        print(f"  1. Move to your Ansible inventory: group_vars/{cluster_name}.yml")
        print("  2. Store passwords in Ansible Vault")
        print("  3. Run playbook: ansible-playbook -i inventory sap_hana_ha.yml --ask-vault-pass")
    else:
        print(yaml_content)

    return True


def delete_config(config_path: Path):
    """Delete health check reports and status files (keeps node access config)."""
    import glob

    config_dir = config_path.parent
    deleted_count = 0

    # Delete last_run_status.yaml
    status_file = config_dir / "last_run_status.yaml"
    if status_file.exists():
        try:
            os.remove(status_file)
            print(f"Deleted: {status_file.name}")
            deleted_count += 1
        except Exception:
            pass

    # Check for health check report files
    report_pattern = str(config_dir / "health_check_report_*.yaml")
    report_files = glob.glob(report_pattern)

    if report_files:
        print(f"\nFound {len(report_files)} health check report file(s):")
        for f in sorted(report_files)[-5:]:  # Show last 5
            print(f"  {Path(f).name}")
        if len(report_files) > 5:
            print(f"  ... and {len(report_files) - 5} more")

        try:
            response = input("\nDelete all health check report files? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = 'n'

        if response == 'y':
            for f in report_files:
                try:
                    os.remove(f)
                    deleted_count += 1
                except Exception:
                    pass
            print(f"Deleted {len(report_files)} report file(s)")
        else:
            print("Report files kept.")
    else:
        print("No health check report files found.")

    # Show info about config file
    if config_path.exists():
        print(f"\nNote: Node access config preserved: {config_path.name}")
        print("      Use -f (--force) to re-discover nodes.")

    if deleted_count > 0:
        print(f"\nTotal files deleted: {deleted_count}")
        return True
    else:
        print("\nNo files deleted.")
        return False


def check_sosreports_on_nodes(nodes: list, ssh_user: str = 'root') -> dict:
    """
    Check which nodes have SOSreports available in /var/tmp.

    Args:
        nodes: List of node hostnames to check
        ssh_user: SSH user for connecting to nodes (default: root)

    Returns:
        Dict mapping hostname -> sosreport path (or None if not found)
    """
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def check_node(hostname: str) -> tuple:
        """Check if a node has a sosreport."""
        try:
            find_cmd = [
                "ssh", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=no",
                f"{ssh_user}@{hostname}",
                "ls -t /var/tmp/sosreport-*.tar.xz /var/tmp/sosreport-*.tar.gz 2>/dev/null | head -1"
            ]

            result = subprocess.run(
                find_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True
            )

            if result.returncode == 0 and result.stdout.strip():
                return (hostname, result.stdout.strip())
            return (hostname, None)
        except Exception:
            return (hostname, None)

    results = {}
    with ThreadPoolExecutor(max_workers=min(len(nodes), 5)) as executor:
        futures = {executor.submit(check_node, node): node for node in nodes}
        for future in as_completed(futures):
            hostname, path = future.result()
            results[hostname] = path

    return results


def create_sosreports(nodes: list, ssh_user: str = 'root', sos_options: str = None) -> dict:
    """
    Create SOSreports on remote cluster nodes.

    Args:
        nodes: List of node hostnames to create sosreports on
        ssh_user: SSH user for connecting to nodes (default: root)
        sos_options: Additional options for sos report command (default: cluster plugins)

    Returns:
        Dict mapping hostname -> (success: bool, message: str)
    """
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Default: include cluster-relevant plugins
    if sos_options is None:
        sos_options = "--batch --all-logs -o pacemaker,corosync,sapnw,saphana,ha_cluster,systemd"

    print(f"\n{'='*60}")
    print(" Creating SOSreports on cluster nodes")
    print(f"{'='*60}")
    print(f"  Nodes: {', '.join(nodes)}")
    print(f"  Command: sos report {sos_options}")
    print()
    print("  This may take several minutes per node...")
    print()

    def create_on_node(hostname: str) -> tuple:
        """Run sos report on a single node."""
        try:
            # Run sos report remotely
            sos_cmd = [
                "ssh", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=30",
                f"{ssh_user}@{hostname}",
                f"sos report {sos_options}"
            ]

            result = subprocess.run(
                sos_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=600,  # 10 minutes timeout
                text=True
            )

            if result.returncode == 0:
                # Extract the generated filename from output
                output = result.stdout
                for line in output.split('\n'):
                    if '/var/tmp/sosreport-' in line and ('.tar.xz' in line or '.tar.gz' in line):
                        # Extract path from line
                        import re
                        match = re.search(r'(/var/tmp/sosreport-[^\s]+\.tar\.[xg]z)', line)
                        if match:
                            return (hostname, True, f"Created: {match.group(1)}")
                return (hostname, True, "SOSreport created successfully")
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                return (hostname, False, f"Failed: {error_msg[:100]}")

        except subprocess.TimeoutExpired:
            return (hostname, False, "Timeout (exceeded 10 minutes)")
        except Exception as e:
            return (hostname, False, f"Error: {str(e)}")

    results = {}
    # Run sequentially to avoid overloading nodes (sosreport is resource-intensive)
    # But use ThreadPoolExecutor for consistent interface
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(create_on_node, node): node for node in nodes}

        for future in as_completed(futures):
            hostname, success, message = future.result()
            results[hostname] = (success, message)
            status = "✓" if success else "✗"
            print(f"  [{hostname}] {status} {message}")

    print()
    success_count = sum(1 for s, _ in results.values() if s)
    print(f"SOSreport creation: {success_count}/{len(nodes)} successful")

    return results


def fetch_sosreports(config_path: Path, cluster_name: str = None, nodes: list = None,
                     output_dir: str = None, ssh_user: str = 'root',
                     auto_create: bool = False, interactive: bool = True):
    """
    Fetch the latest sosreports from cluster nodes via SCP.

    First checks if SOSreports exist on nodes. If missing, prompts user
    to create them (unless auto_create or non-interactive mode).

    Args:
        config_path: Path to the configuration file
        cluster_name: Name of the cluster to fetch sosreports from
        nodes: List of specific node hostnames (alternative to cluster_name)
        output_dir: Directory to save sosreports (default: ./sosreports)
        ssh_user: SSH user for connecting to nodes (default: root)
        auto_create: If True, automatically create missing sosreports without prompting
        interactive: If True, prompt user for missing sosreports; if False, skip missing

    Returns:
        List of downloaded file paths, or empty list on failure
    """
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Determine output directory
    if output_dir:
        sos_dir = Path(output_dir)
    else:
        sos_dir = config_path.parent / 'sosreports'

    sos_dir.mkdir(parents=True, exist_ok=True)

    # Get list of nodes to fetch from
    target_nodes = []

    if nodes:
        # Use specified nodes directly
        target_nodes = nodes
    elif cluster_name:
        # Load nodes from cluster config
        if not config_path.exists():
            print(f"[ERROR] Configuration file not found: {config_path}")
            return []

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        clusters = config.get('clusters', {})
        if cluster_name not in clusters:
            print(f"[ERROR] Cluster '{cluster_name}' not found in configuration.")
            print(f"Available clusters: {', '.join(clusters.keys())}")
            return []

        target_nodes = clusters[cluster_name].get('nodes', [])
    else:
        print("[ERROR] Either cluster_name or nodes must be specified.")
        return []

    if not target_nodes:
        print("[ERROR] No nodes found to fetch sosreports from.")
        return []

    # Step 1: Check which nodes have existing SOSreports
    print(f"\n{'='*60}")
    print(" Checking for existing SOSreports")
    print(f"{'='*60}")
    print(f"  Nodes: {', '.join(target_nodes)}")
    print()

    existing = check_sosreports_on_nodes(target_nodes, ssh_user)

    nodes_with_sos = [n for n, p in existing.items() if p]
    nodes_without_sos = [n for n, p in existing.items() if not p]

    for node in target_nodes:
        if existing.get(node):
            print(f"  [{node}] ✓ Found: {os.path.basename(existing[node])}")
        else:
            print(f"  [{node}] ✗ No SOSreport found")

    print()

    # Step 2: Handle missing SOSreports
    if nodes_without_sos:
        print(f"Missing SOSreports on {len(nodes_without_sos)} node(s): {', '.join(nodes_without_sos)}")

        create_missing = False

        if auto_create:
            create_missing = True
        elif interactive and sys.stdin.isatty():
            print()
            response = input("Create SOSreports on these nodes? [y/N]: ").strip().lower()
            create_missing = response in ('y', 'yes')

        if create_missing:
            create_results = create_sosreports(nodes_without_sos, ssh_user)

            # Re-check for newly created sosreports
            new_existing = check_sosreports_on_nodes(nodes_without_sos, ssh_user)
            existing.update(new_existing)

            # Update lists
            nodes_with_sos = [n for n, p in existing.items() if p]
            nodes_without_sos = [n for n, p in existing.items() if not p]

    # Step 3: Fetch existing SOSreports
    if not nodes_with_sos:
        print("\nNo SOSreports available to download.")
        return []

    print(f"\n{'='*60}")
    print(" Fetching SOSreports from cluster nodes")
    print(f"{'='*60}")
    print(f"  Nodes: {', '.join(nodes_with_sos)}")
    print(f"  Output: {sos_dir}")
    print(f"  SSH user: {ssh_user}")
    print()

    downloaded_files = []

    def fetch_from_node(hostname: str, remote_path: str) -> tuple:
        """Download sosreport from a single node using known path."""
        try:
            filename = os.path.basename(remote_path)
            local_path = sos_dir / filename

            # Check if already downloaded
            if local_path.exists():
                return (hostname, str(local_path), "Already exists (skipped)")

            # Download via SCP
            scp_cmd = [
                "scp", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=no",
                f"{ssh_user}@{hostname}:{remote_path}",
                str(local_path)
            ]

            result = subprocess.run(
                scp_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,  # 5 minutes for large files
                text=True
            )

            if result.returncode == 0:
                # Get file size
                size_mb = local_path.stat().st_size / (1024 * 1024)
                return (hostname, str(local_path), f"Downloaded ({size_mb:.1f} MB)")
            else:
                return (hostname, None, f"SCP failed: {result.stderr.strip()}")

        except subprocess.TimeoutExpired:
            return (hostname, None, "Timeout")
        except Exception as e:
            return (hostname, None, f"Error: {str(e)}")

    # Fetch from nodes with sosreports in parallel (using known paths)
    with ThreadPoolExecutor(max_workers=min(len(nodes_with_sos), 5)) as executor:
        futures = {
            executor.submit(fetch_from_node, node, existing[node]): node
            for node in nodes_with_sos
        }

        for future in as_completed(futures):
            hostname, filepath, message = future.result()
            if filepath:
                downloaded_files.append(filepath)
                print(f"  [{hostname}] ✓ {message}")
            else:
                print(f"  [{hostname}] ✗ {message}")

    print()
    if downloaded_files:
        print(f"Downloaded {len(downloaded_files)} sosreport(s) to: {sos_dir}")
        print("\nTo analyze with health check:")
        print(f"  ./cluster_health_check.py -s {sos_dir}")
    else:
        print("No sosreports were downloaded.")

    return downloaded_files


def main():
    parser = argparse.ArgumentParser(
        description='Discover access methods to SAP Pacemaker cluster nodes'
    )
    parser.add_argument(
        '--config-dir', '-c',
        default='.',
        help='Directory to store configuration (default: current directory)'
    )
    parser.add_argument(
        '--hosts-file', '-H',
        help='File containing list of hosts (one per line)'
    )
    parser.add_argument(
        '--sosreport-dir', '-s',
        help='Directory containing SOSreport archives/directories'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Force rediscovery (ignore existing config)'
    )
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=10,
        help='Number of parallel workers (default: 10)'
    )
    parser.add_argument(
        '--show-config', '-S',
        action='store_true',
        help='Display current configuration and exit'
    )
    parser.add_argument(
        '--delete-config', '-D',
        action='store_true',
        help='Delete configuration file to restart investigation'
    )

    args = parser.parse_args()

    config_path = Path(args.config_dir) / AccessDiscovery.CONFIG_FILE

    # Handle show-config action
    if args.show_config:
        show_config(config_path)
        sys.exit(0)

    # Handle delete-config action
    if args.delete_config:
        delete_config(config_path)
        sys.exit(0)

    discovery = AccessDiscovery(
        config_dir=args.config_dir,
        sosreport_dir=args.sosreport_dir,
        hosts_file=args.hosts_file,
        force_rediscover=args.force
    )
    discovery.MAX_WORKERS = args.workers

    try:
        discovery.discover_all()
        # Show the saved config at the end
        print("\n" + "-" * 60)
        print("Saved Configuration:")
        print("-" * 60)
        show_config(config_path)
    except KeyboardInterrupt:
        print("\nDiscovery interrupted. Saving partial results...")
        discovery.save_config()
        sys.exit(1)


if __name__ == '__main__':
    main()
