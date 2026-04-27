#!/usr/bin/env python3
"""
Cluster Configuration Extractor

Extracts SAP HANA cluster configuration from pcs config output.
Works with:
- SOSreport: reads sos_commands/pacemaker/pcs_config file
- Offline cluster (SSH): runs pcs -f /var/lib/pacemaker/cib/cib.xml config
- Running cluster: runs pcs config (active configuration)

Output: YAML file with standardized cluster configuration for PDF report generation.
"""

import re
import yaml
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime


class ConfigExtractor:
    """Extract cluster configuration from pcs config output."""

    # Default cib.xml location
    DEFAULT_CIB_PATH = "/var/lib/pacemaker/cib/cib.xml"

    def __init__(self):
        self.config = {}
        self._raw_output = ""

    @classmethod
    def from_sosreport(cls, sosreport_path: str) -> Optional['ConfigExtractor']:
        """Create extractor from SOSreport directory.

        Args:
            sosreport_path: Path to extracted SOSreport directory

        Returns:
            ConfigExtractor instance or None if pcs_config not found
        """
        sos_path = Path(sosreport_path)
        pcs_config_path = sos_path / "sos_commands/pacemaker/pcs_config"

        if not pcs_config_path.exists():
            return None

        extractor = cls()
        extractor._raw_output = pcs_config_path.read_text()
        extractor._source = f"sosreport:{sosreport_path}"
        extractor._parse_pcs_config()
        return extractor

    @classmethod
    def from_cib_file(cls, cib_path: str = None) -> Optional['ConfigExtractor']:
        """Create extractor from local cib.xml file (offline cluster).

        Args:
            cib_path: Path to cib.xml file (default: /var/lib/pacemaker/cib/cib.xml)

        Returns:
            ConfigExtractor instance or None if failed
        """
        cib_path = cib_path or cls.DEFAULT_CIB_PATH

        if not Path(cib_path).exists():
            return None

        try:
            result = subprocess.run(
                f"pcs -f {cib_path} config",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                return None

            extractor = cls()
            extractor._raw_output = result.stdout
            extractor._source = f"cib_file:{cib_path}"
            extractor._parse_pcs_config()
            return extractor
        except Exception:
            return None

    @classmethod
    def from_running_cluster(cls, host: str = None, user: str = "root") -> Optional['ConfigExtractor']:
        """Create extractor from running cluster.

        Args:
            host: Remote host (None for local)
            user: SSH user for remote access

        Returns:
            ConfigExtractor instance or None if failed
        """
        try:
            if host:
                cmd = f"ssh {user}@{host} 'pcs config'"
            else:
                cmd = "pcs config"

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                return None

            extractor = cls()
            extractor._raw_output = result.stdout
            extractor._source = f"running_cluster:{host or 'local'}"
            extractor._parse_pcs_config()
            return extractor
        except Exception:
            return None

    @classmethod
    def from_ssh_offline(cls, host: str, user: str = "root", cib_path: str = None) -> Optional['ConfigExtractor']:
        """Create extractor from offline cluster via SSH.

        Args:
            host: Remote host
            user: SSH user
            cib_path: Path to cib.xml on remote host

        Returns:
            ConfigExtractor instance or None if failed
        """
        cib_path = cib_path or cls.DEFAULT_CIB_PATH

        try:
            cmd = f"ssh {user}@{host} 'pcs -f {cib_path} config'"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                return None

            extractor = cls()
            extractor._raw_output = result.stdout
            extractor._source = f"ssh_offline:{host}"
            extractor._parse_pcs_config()
            return extractor
        except Exception:
            return None

    def _parse_pcs_config(self):
        """Parse pcs config output and extract all configuration."""
        self.config = {
            'extracted_at': datetime.now().isoformat(),
            'source': getattr(self, '_source', 'unknown'),
            'cluster': {},
            'sap_hana': {},
            'resources': {},
            'stonith': {},
            'constraints': {},
            'properties': {}
        }

        self._parse_cluster_info()
        self._parse_resources()
        self._parse_stonith()
        self._parse_constraints()
        self._parse_properties()

    def _parse_cluster_info(self):
        """Extract cluster name and basic info."""
        # Cluster Name: from "Cluster Name:" line
        match = re.search(r'Cluster Name:\s*(\S+)', self._raw_output)
        if match:
            self.config['cluster']['name'] = match.group(1)

    def _parse_resources(self):
        """Extract SAP HANA and related resources."""
        lines = self._raw_output.split('\n')

        # Track current resource being parsed
        current_clone = None
        current_resource = None
        current_section = None  # 'attributes', 'meta', 'operations'
        pending_vips = []  # Store VIP resources to update IPs later

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Detect Clone/Promotable resources
            clone_match = re.match(r'\s*Clone:\s*(\S+)', line)
            if clone_match:
                current_clone = clone_match.group(1)
                current_resource = None
                current_section = None
                i += 1
                continue

            # Detect Group (reset clone context)
            group_match = re.match(r'\s*Group:\s*(\S+)', line)
            if group_match:
                current_clone = None
                current_resource = None
                current_section = None
                i += 1
                continue

            # Detect Resource (standalone or within Clone/Group)
            resource_match = re.match(r'\s*Resource:\s*(\S+)\s*\(class=(\S+)\s+(?:provider=(\S+)\s+)?type=(\S+)\)', line)
            if resource_match:
                res_name = resource_match.group(1)
                res_class = resource_match.group(2)
                res_provider = resource_match.group(3) or ''
                res_type = resource_match.group(4)

                current_resource = {
                    'name': res_name,
                    'class': res_class,
                    'provider': res_provider,
                    'type': res_type,
                    'clone': current_clone,
                    'attributes': {},
                    'meta_attributes': {},
                    'operations': []
                }

                # Categorize resource
                if 'SAPHanaController' in res_type:
                    self._store_saphana_resource('controller', current_resource, current_clone)
                elif 'SAPHanaTopology' in res_type:
                    self._store_saphana_resource('topology', current_resource, current_clone)
                elif 'SAPHanaFilesystem' in res_type:
                    self._store_saphana_resource('filesystem', current_resource, current_clone)
                elif 'SAPHana' in res_type and 'Controller' not in res_type and 'Topology' not in res_type:
                    self._store_saphana_resource('saphana', current_resource, current_clone)
                elif 'IPaddr2' in res_type or 'IPaddr' in res_type:
                    # Store VIP resource - will update IP when attributes are parsed
                    pending_vips.append(current_resource)

                current_section = None
                i += 1
                continue

            # Detect Attributes section
            if 'Attributes:' in stripped and current_resource:
                current_section = 'attributes'
                i += 1
                continue

            # Detect Meta Attributes section
            if 'Meta Attributes:' in stripped:
                current_section = 'meta'
                # Check if this is clone meta or resource meta
                if current_resource is None and current_clone:
                    # Clone-level meta attributes
                    self._parse_clone_meta(lines, i, current_clone)
                i += 1
                continue

            # Detect Operations section
            if 'Operations:' in stripped and current_resource:
                current_section = 'operations'
                i += 1
                continue

            # Parse attribute values
            if current_section == 'attributes' and current_resource and '=' in stripped:
                attr_match = re.match(r'(\S+)=(.+)', stripped)
                if attr_match:
                    key = attr_match.group(1)
                    value = attr_match.group(2).strip()
                    current_resource['attributes'][key] = value

                    # Extract key SAP HANA attributes
                    if key == 'SID':
                        self.config['sap_hana']['sid'] = value
                    elif key == 'InstanceNumber':
                        self.config['sap_hana']['instance_number'] = value
                    elif key == 'AUTOMATED_REGISTER':
                        self.config['sap_hana']['automated_register'] = value.lower() == 'true'
                    elif key == 'PREFER_SITE_TAKEOVER':
                        self.config['sap_hana']['prefer_site_takeover'] = value.lower() == 'true'
                    elif key == 'DUPLICATE_PRIMARY_TIMEOUT':
                        try:
                            self.config['sap_hana']['duplicate_primary_timeout'] = int(value)
                        except ValueError:
                            pass

            i += 1

        # Process pending VIP resources (now that attributes are parsed)
        for vip_resource in pending_vips:
            self._store_vip_resource(vip_resource)

    def _store_saphana_resource(self, res_type: str, resource: dict, clone_name: str):
        """Store SAP HANA resource configuration."""
        self.config['sap_hana'][res_type] = {
            'resource_name': resource['name'],
            'clone_name': clone_name,
            'type': resource['type'],
            'attributes': resource['attributes']
        }

        # Set main resource info
        if res_type in ('controller', 'saphana'):
            self.config['sap_hana']['resource_type'] = 'SAPHanaController' if res_type == 'controller' else 'SAPHana'
            self.config['sap_hana']['resource_name'] = resource['name']

    def _store_vip_resource(self, resource: dict):
        """Store VIP resource configuration."""
        if 'vips' not in self.config['resources']:
            self.config['resources']['vips'] = []

        vip_info = {
            'resource_name': resource['name'],
            'ip': resource['attributes'].get('ip', ''),
            'cidr_netmask': resource['attributes'].get('cidr_netmask', ''),
            'nic': resource['attributes'].get('nic', '')
        }
        self.config['resources']['vips'].append(vip_info)

        # Detect SAP HANA VIPs - look for vip_<SID>_<Instance> or vip2_<SID>_<Instance> pattern
        # Get SID if already detected
        sid = self.config['sap_hana'].get('sid', '').lower()
        res_name_lower = resource['name'].lower()

        # Secondary VIP: vip2_<SID> pattern (must contain SID if known)
        is_secondary = 'vip2' in res_name_lower
        if is_secondary:
            # If we know SID, verify this VIP is for this SID
            if not sid or sid in res_name_lower:
                self.config['sap_hana']['secondary_vip'] = vip_info['ip']
                self.config['sap_hana']['secondary_vip_resource'] = resource['name']
        # Primary HANA VIP: vip_<SID> pattern (not vip2, not ascs/ers/pas/aas)
        elif re.match(r'^vip_[a-z0-9]+_\d+$', res_name_lower):
            # Pattern: vip_<SID>_<InstanceNumber> - this is a HANA VIP
            if not sid or sid in res_name_lower:
                self.config['sap_hana']['virtual_ip'] = vip_info['ip']
                self.config['sap_hana']['vip_resource'] = resource['name']

    def _parse_clone_meta(self, lines: List[str], start_idx: int, clone_name: str):
        """Parse clone-level meta attributes."""
        clone_meta = {}
        i = start_idx + 1

        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith('Resource:') or line.startswith('Clone:'):
                break

            match = re.match(r'(\S+)=(\S+)', line)
            if match:
                clone_meta[match.group(1)] = match.group(2)
            i += 1

        # Store clone-max for the appropriate resource
        if 'SAPHanaController' in clone_name or 'SAPHana_' in clone_name:
            if 'clone-max' in clone_meta:
                self.config['sap_hana']['clone_max'] = int(clone_meta['clone-max'])
            if 'promotable' in clone_meta:
                self.config['sap_hana']['promotable'] = clone_meta['promotable'].lower() == 'true'
            if 'interleave' in clone_meta:
                self.config['sap_hana']['interleave'] = clone_meta['interleave'].lower() == 'true'
        elif 'SAPHanaTopology' in clone_name:
            if 'clone-max' in clone_meta:
                self.config['sap_hana']['topology_clone_max'] = int(clone_meta['clone-max'])

    def _parse_stonith(self):
        """Extract STONITH/fencing configuration."""
        lines = self._raw_output.split('\n')

        in_stonith = False
        current_device = None

        for line in lines:
            stripped = line.strip()

            # Detect STONITH resource
            if 'class=stonith' in line:
                match = re.match(r'\s*Resource:\s*(\S+)\s*\(class=stonith\s+type=(\S+)\)', line)
                if match:
                    current_device = {
                        'name': match.group(1),
                        'type': match.group(2),
                        'attributes': {}
                    }
                    self.config['stonith']['device'] = match.group(1)
                    self.config['stonith']['type'] = match.group(2)
                    in_stonith = True
                continue

            # Parse STONITH attributes
            if in_stonith and current_device and '=' in stripped:
                # Stop at next section
                if stripped.startswith('Operations:') or stripped.startswith('Resource:') or stripped.startswith('Clone:'):
                    in_stonith = False
                    continue

                match = re.match(r'(\S+)=(.+)', stripped)
                if match:
                    key = match.group(1)
                    value = match.group(2).strip()
                    current_device['attributes'][key] = value

                    # Extract key STONITH attributes
                    if key == 'pcmk_host_map':
                        self.config['stonith']['pcmk_host_map'] = value
                        # Parse host map into structured format
                        host_map = {}
                        for mapping in value.split(';'):
                            if ':' in mapping:
                                node, target = mapping.split(':', 1)
                                host_map[node.strip()] = target.strip()
                        self.config['stonith']['host_map'] = host_map
                    elif key in ('ip', 'username', 'ssl', 'ssl_insecure', 'power_wait'):
                        self.config['stonith'][key] = value

    def _parse_constraints(self):
        """Extract location, colocation, and order constraints."""
        lines = self._raw_output.split('\n')

        current_section = None
        constraints = {
            'location': [],
            'colocation': [],
            'order': [],
            'hana_excluded_node': None,  # Node with HANA exclusion constraints
            'majority_maker': None       # Only set if clone-max >= 4 (Scale-Out)
        }
        # Track which nodes have both SAPHanaTopology AND SAPHanaController exclusion constraints
        nodes_excluded_from_controller = set()
        nodes_excluded_from_topology = set()

        for line in lines:
            stripped = line.strip()

            if stripped.startswith('Location Constraints:'):
                current_section = 'location'
                continue
            elif stripped.startswith('Colocation Constraints:'):
                current_section = 'colocation'
                continue
            elif stripped.startswith('Ordering Constraints:'):
                current_section = 'order'
                continue
            elif stripped.startswith('Ticket Constraints:') or stripped.startswith('Resources:'):
                current_section = None
                continue

            if current_section and stripped:
                constraints[current_section].append(stripped)

                # Track location constraints that exclude HANA resources from nodes
                if current_section == 'location' and 'avoids node' in stripped and 'INFINITY' in stripped:
                    match = re.search(r"avoids node '([^']+)'", stripped)
                    if match:
                        node = match.group(1)
                        if 'SAPHanaController' in stripped:
                            nodes_excluded_from_controller.add(node)
                        if 'SAPHanaTopology' in stripped:
                            nodes_excluded_from_topology.add(node)

        # A node excluded from BOTH SAPHanaTopology AND SAPHanaController
        # is either an app server (Scale-Up) or majority maker (Scale-Out)
        # The distinction depends on clone-max which is checked later
        excluded_from_both = nodes_excluded_from_controller & nodes_excluded_from_topology
        if excluded_from_both:
            constraints['hana_excluded_node'] = sorted(excluded_from_both)[0]

        self.config['constraints'] = constraints

    def _parse_properties(self):
        """Extract cluster properties."""
        lines = self._raw_output.split('\n')

        in_properties = False
        properties = {}

        for line in lines:
            stripped = line.strip()

            if 'Cluster Properties:' in stripped:
                in_properties = True
                continue

            if in_properties:
                # Stop at next section
                if stripped.startswith('Resource Defaults:') or stripped.startswith('Operation Defaults:'):
                    break

                # Parse property=value (default) or property=value
                match = re.match(r'(\S+)=(\S+)(?:\s+\(default\))?', stripped)
                if match:
                    properties[match.group(1)] = match.group(2)

        self.config['properties'] = properties

        # Extract key properties
        if 'stonith-enabled' in properties:
            self.config['stonith']['enabled'] = properties['stonith-enabled'].lower() == 'true'

        # Extract versions from dc-version (format: 2.1.9-1.el9-49aab9983)
        dc_version = properties.get('dc-version', '')
        if dc_version:
            # Extract Pacemaker version (first part before -)
            pacemaker_match = re.match(r'(\d+\.\d+\.\d+)', dc_version)
            if pacemaker_match:
                self.config['cluster']['pacemaker_version'] = pacemaker_match.group(1)

            # Extract RHEL version from el<N> pattern
            rhel_match = re.search(r'\.el(\d+)', dc_version)
            if rhel_match:
                self.config['cluster']['rhel_version'] = f"RHEL {rhel_match.group(1)}"

    def get_config(self) -> Dict[str, Any]:
        """Return the extracted configuration."""
        return self.config

    def write_yaml(self, output_path: str) -> str:
        """Write configuration to YAML file.

        Args:
            output_path: Path to output YAML file

        Returns:
            Path to written file
        """
        output_path = Path(output_path)

        with open(output_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        return str(output_path)

    def to_cluster_info(self) -> Dict[str, Any]:
        """Convert extracted config to cluster_info format for PDF report.

        Returns:
            Dict compatible with report_generator.generate_report()
        """
        hana = self.config.get('sap_hana', {})
        stonith = self.config.get('stonith', {})
        constraints = self.config.get('constraints', {})

        cluster = self.config.get('cluster', {})

        cluster_info = {
            # Cluster info
            'cluster_name': cluster.get('name', 'Unknown'),
            'rhel_version': cluster.get('rhel_version'),
            'pacemaker_version': cluster.get('pacemaker_version'),

            # SAP HANA info
            'sid': hana.get('sid'),
            'instance_number': hana.get('instance_number'),
            'virtual_ip': hana.get('virtual_ip'),
            'secondary_vip': hana.get('secondary_vip'),
            'vip_resource': hana.get('vip_resource'),
            'secondary_vip_resource': hana.get('secondary_vip_resource'),

            # HA Parameters
            'prefer_site_takeover': hana.get('prefer_site_takeover'),
            'automated_register': hana.get('automated_register'),
            'duplicate_primary_timeout': hana.get('duplicate_primary_timeout'),

            # Resource info
            'resource_type': hana.get('resource_type'),
            'resource_name': hana.get('resource_name'),
            'clone_max': hana.get('clone_max'),

            # Topology resource (Scale-Out)
            'topology_resource': hana.get('topology', {}).get('resource_name') if hana.get('topology') else None,

            # STONITH
            'stonith_device': stonith.get('device'),
            'stonith_params': {
                'pcmk_host_map': stonith.get('pcmk_host_map', ''),
                'ssl': stonith.get('ssl', ''),
                'ssl_insecure': stonith.get('ssl_insecure', ''),
            },

            # Node with HANA exclusion constraints (may be app server or majority maker)
            'hana_excluded_node': constraints.get('hana_excluded_node'),
            # Majority maker only set for Scale-Out (clone-max >= 4)
            'majority_maker': constraints.get('majority_maker'),
        }

        # Determine if the hana_excluded_node is a majority maker or app server
        # Majority maker: only in Scale-Out (clone-max >= 4)
        clone_max = hana.get('clone_max', 2) or 2
        try:
            clone_max = int(clone_max)
        except (ValueError, TypeError):
            clone_max = 2

        excluded_node = constraints.get('hana_excluded_node')
        if excluded_node and clone_max >= 4:
            # Scale-Out: this is a majority maker
            cluster_info['majority_maker'] = excluded_node
        elif excluded_node:
            # Scale-Up: this is an app server, not a majority maker
            cluster_info['majority_maker'] = None

        return cluster_info


def extract_config(source_type: str, source_path: str = None, host: str = None,
                   user: str = "root", output_yaml: str = None) -> Optional[Dict[str, Any]]:
    """Convenience function to extract configuration.

    Args:
        source_type: 'sosreport', 'cib_file', 'running', 'ssh_offline'
        source_path: Path for sosreport or cib_file
        host: Remote host for running or ssh_offline
        user: SSH user
        output_yaml: Optional path to write YAML output

    Returns:
        Extracted configuration dict or None if failed
    """
    extractor = None

    if source_type == 'sosreport':
        extractor = ConfigExtractor.from_sosreport(source_path)
    elif source_type == 'cib_file':
        extractor = ConfigExtractor.from_cib_file(source_path)
    elif source_type == 'running':
        extractor = ConfigExtractor.from_running_cluster(host, user)
    elif source_type == 'ssh_offline':
        extractor = ConfigExtractor.from_ssh_offline(host, user, source_path)

    if not extractor:
        return None

    if output_yaml:
        extractor.write_yaml(output_yaml)

    return extractor.get_config()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: config_extractor.py <sosreport_path> [output.yaml]")
        sys.exit(1)

    sos_path = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "cluster_config.yaml"

    extractor = ConfigExtractor.from_sosreport(sos_path)
    if extractor:
        extractor.write_yaml(output)
        print(f"Configuration extracted to: {output}")

        # Print summary
        config = extractor.get_config()
        print(f"\nCluster: {config.get('cluster', {}).get('name', 'Unknown')}")
        print(f"SID: {config.get('sap_hana', {}).get('sid', 'N/A')}")
        print(f"Instance: {config.get('sap_hana', {}).get('instance_number', 'N/A')}")
        print(f"STONITH: {config.get('stonith', {}).get('device', 'N/A')}")
    else:
        print(f"Failed to extract configuration from: {sos_path}")
        sys.exit(1)
