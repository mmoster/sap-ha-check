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
        return sosreports

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
                first_sos_path = list(cluster_info['nodes'].values())[0]
                expected_nodes = self.get_cluster_nodes_from_sosreport(first_sos_path)

                for hostname, sos_path in list(unassigned.items()):
                    # Check if hostname matches any expected node
                    for expected in expected_nodes:
                        if hostname in expected or expected in hostname:
                            clusters[cluster_name]['nodes'][hostname] = sos_path
                            del unassigned[hostname]
                            print(f"  {hostname}: matched to cluster '{cluster_name}' (from nodelist)")
                            break

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
                    cmd
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

    def discover_cluster_nodes_local(self) -> tuple:
        """
        Discover cluster members by running commands locally.
        Returns tuple: (cluster_name, list of cluster node hostnames)
        """
        cluster_nodes = []
        cluster_name = None

        print("\n=== Discovering Cluster (local mode) ===")

        # Get local hostname
        self.local_hostname = self.get_local_hostname()
        print(f"  Local hostname: {self.local_hostname}")

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
            print("  Could not discover cluster nodes locally")
            print(f"  Using {self.local_hostname} as only node")
            cluster_nodes = [self.local_hostname]

        # Store cluster info
        if cluster_name:
            self.config.clusters[cluster_name] = {
                'nodes': cluster_nodes,
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
        cluster_nodes = []
        cluster_name = None

        print(f"\n=== Discovering Cluster from {seed_host} ===")

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
                    cmd
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
            print(f"  Could not discover cluster nodes from {seed_host}")
            print(f"  Using {seed_host} as only node")
            cluster_nodes = [seed_host]

        # Store cluster info
        if cluster_name:
            self.config.clusters[cluster_name] = {
                'nodes': cluster_nodes,
                'discovered_from': seed_host,
                'discovered_at': datetime.now().isoformat()
            }

        return cluster_name, cluster_nodes

    def check_ssh_access(self, hostname: str, user: str = None) -> tuple:
        """Check SSH access to a host. Returns (reachable, user)."""
        users_to_try = [user] if user else [os.environ.get('USER', 'root'), 'root']

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
                    # Use cluster nodes instead of just the specified hosts
                    file_hosts = cluster_nodes
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
                    updated_count += 1
            if updated_count > 0:
                print(f"\n  [INFO] Found {updated_count} matching SOSreport(s) in subdirectories")

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
        print(f"  Show all config:  ./cluster_health_check.py --show-config")
    elif clusters:
        first_cluster = list(clusters.keys())[0]
        print(f"  Check cluster:    ./cluster_health_check.py -C {first_cluster}")
        print(f"  Show one cluster: ./cluster_health_check.py --show-config {first_cluster}")
    print("  Force rediscover: ./cluster_health_check.py -f hana01")
    print("  Delete config:    ./cluster_health_check.py -D")
    print("  Show guide:       ./cluster_health_check.py --guide")

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
