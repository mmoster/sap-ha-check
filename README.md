# SAP HANA Pacemaker Cluster Health Check

A comprehensive health check tool for SAP HANA Pacemaker clusters on Red Hat Enterprise Linux (RHEL 8/9/10).

## Quick Start

### On a Cluster Node (Recommended)

```bash
# Clone and run locally
git clone https://github.com/mmoster/sap-ha-check.git
cd sap-ha-check
./cluster_health_check.py --local
```

### Remote Check

```bash
# Check specific nodes
./cluster_health_check.py hana01 hana02

# Use a hosts file
./cluster_health_check.py -H hosts.txt

# Analyze SOSreports offline
./cluster_health_check.py -s /path/to/sosreports/

# Verbose PDF (show all checks in detail, not just failures)
./cluster_health_check.py hana01 -v

# Collect SOSreports from cluster (auto-discovers all nodes)
./cluster_health_check.py -R hana01
```

### Interactive Mode

```bash
# Scan directory for sosreports/inventory/results
./cluster_health_check.py -u
```

This scans the current directory for:
- SOSreport archives (`.tar.xz`, `.tar.gz`)
- Hosts files (`hosts.txt`, `inventory`)
- Previous health check results (`.yaml`)

Then presents an interactive menu:

```
Found resources:
  [1] SOSreports: ./sosreports/ (3 archives)
  [2] Hosts file: ./hosts.txt (2 hosts)
  [3] Previous result: cluster2 (2026-04-16)
  [4] Run on local cluster node
  [5] Enter hostnames manually

Select option [1-5/q]:
```

This is useful when you don't remember where your SOSreports are stored or want a guided setup.

## Features

- **Multiple Access Methods**: SSH, Ansible inventory, or SOSreport analysis
- **Multithreaded Execution**: Parallel node connectivity checks and rule execution
- **22 Built-in Health Checks**: Cluster configuration, Pacemaker/Corosync, and SAP-specific validations
- **Automatic Cluster Discovery**: Discovers all nodes from Pacemaker configuration
- **Cluster Status Detection**: Warns if cluster services are not running, falls back to static config
- **Multi-Cluster Support**: Prompts for selection when multiple clusters are discovered
- **Version Detection**: Automatically detects RHEL and Pacemaker versions
- **HANA Status Detection**: Identifies SID, instance, sidadm user, and running processes
- **Progress Indicators**: Animated spinner shows work is in progress
- **PDF Reports**: Auto-generated PDF reports with optional verbose mode (requires fpdf2)

## Installation

### Option 1: Using git (recommended)

```bash
# Install git if not available
sudo dnf install git    # RHEL/Fedora
sudo yum install git    # RHEL 7

# Clone and run
git clone https://github.com/mmoster/sap-ha-check.git
cd sap-ha-check
./cluster_health_check.py --local
```

### Option 2: Download without git

```bash
# Download and extract
curl -L https://github.com/mmoster/sap-ha-check/archive/refs/heads/main.tar.gz | tar xz
cd sap-ha-check-main
./cluster_health_check.py --local
```

### Requirements

- Python 3.6+ (included in RHEL 8/9)
- PyYAML (`pip install pyyaml` or `dnf install python3-pyyaml`)
- fpdf2 (optional, for PDF reports): `pip install fpdf2`

## Usage

```
./cluster_health_check.py [OPTIONS] [NODES...]

Options:
  -u, --usage           Interactive mode - scan directory for resources
  -H, --hosts-file      File containing list of hosts (one per line)
  -s, --sosreport-dir   Directory containing SOSreport archives/directories
  --local               Run locally on this cluster node
  -f, --force           Force rediscovery (ignore existing config)
  -D, --delete-reports  Delete reports and restart
  -S, --show-config [CLUSTER|NODE]  Display configuration (optionally filter by cluster or node)
  -L, --list-rules      List available health check rules
  -d, --debug           Enable debug mode
  -v, --verbose         Verbose PDF - show all checks in detail (not just failures)
  --no-pdf              Skip PDF report generation
  --no-update-check     Skip software update check

SOSreport Collection:
  -F, --fetch-sosreports [CLUSTER|node1 node2...]  Fetch existing SOSreports from nodes
  -R, --collect-sosreports NODE  Full SOSreport workflow: discover cluster from NODE,
                                 configure SAP extensions, create and fetch SOSreports
  --create-sosreports    Auto-create SOSreports on nodes where missing (use with -F)
  --configure-extensions Auto-configure SAP extensions without prompting (use with -R)
```

## Health Check Steps

| Step | Description |
|------|-------------|
| 1. Access Discovery | Discovers SSH/Ansible/SOSreport access to cluster nodes |
| 2. Cluster Configuration | Node status, quorum, clone config, package consistency |
| 3. Pacemaker/Corosync | STONITH, resources, fencing, master/slave roles |
| 4. SAP-Specific | HANA SR status, replication mode, HA/DR hooks, systemd |
| 5. Report Generation | Summary YAML and PDF reports |

## Included Health Checks

### Cluster Configuration
| Check ID | Severity | Description |
|----------|----------|-------------|
| CHK_CLUSTER_READY | WARNING | Check if cluster is fully started (not in transition) |
| CHK_CLUSTER_TYPE | INFO | Detect Scale-Up vs Scale-Out configuration |
| CHK_NODE_STATUS | CRITICAL | Verify all cluster nodes are online |
| CHK_CLUSTER_QUORUM | CRITICAL | Verify cluster has quorum |
| CHK_QUORUM_CONFIG | CRITICAL | Validate quorum configuration |
| CHK_CLONE_CONFIG | CRITICAL | Validate clone resource configuration |
| CHK_SETUP_VALIDATION | CRITICAL | Validate against SAP HANA HA best practices |
| CHK_CIB_TIME_SYNC | WARNING | Verify CIB updates are synchronized |
| CHK_PACKAGE_CONSISTENCY | WARNING | Verify package versions across nodes |

### Pacemaker/Corosync
| Check ID | Severity | Description |
|----------|----------|-------------|
| CHK_STONITH_CONFIG | CRITICAL | Verify STONITH/fencing is enabled |
| CHK_RESOURCE_STATUS | CRITICAL | Verify SAP HANA resources are running |
| CHK_RESOURCE_FAILURES | WARNING | Detect failed resource operations |
| CHK_ALERT_FENCING | WARNING | Validate SAPHanaSR-alert-fencing |
| CHK_MASTER_SLAVE_ROLES | CRITICAL | Verify master/slave role consistency |
| CHK_MAJORITY_MAKER | CRITICAL | Validate majority maker constraints |

### SAP-Specific
| Check ID | Severity | Description |
|----------|----------|-------------|
| CHK_HANA_INSTALLED | INFO | Detect HANA installation, SID, instance, sidadm user, and running status |
| CHK_HANA_SR_STATUS | CRITICAL | Verify HANA System Replication status |
| CHK_REPLICATION_MODE | WARNING | Verify replication mode is sync or syncmem |
| CHK_HADR_HOOKS | CRITICAL | Validate HA/DR provider hooks |
| CHK_HANA_AUTOSTART | WARNING | Validate HANA autostart is disabled |
| CHK_SYSTEMD_SAP | WARNING | Validate SAP Host Agent and systemd |
| CHK_SITE_ROLES | CRITICAL | Verify site roles consistency |

## Cluster Types and Packages

### Scale-Up (2 HANA nodes + optional additional cluster nodes)
- Package: `sap-hana-ha` (ANGI, RHEL 9+) or `resource-agents-sap-hana` (classic)
- Resource agent: `SAPHana`
- Additional cluster nodes (ASCS servers, etc.) don't require HANA

### Scale-Out (4+ HANA nodes + 1 majority maker)
- HANA nodes: `sap-hana-ha` (ANGI) or `resource-agents-sap-hana-scaleout` (classic)
- Majority maker: Same packages as HANA nodes, or no SAP HANA packages
- Resource agent: `SAPHanaController`

## Example Output

```
Health Check Results:
  PASSED:   26  FAILED:   0  SKIPPED:   0  ERROR:   0

  ╔═══════════════════════════════════════════════════════╗
  ║            ✓  CLUSTER IS HEALTHY  ✓                   ║
  ╚═══════════════════════════════════════════════════════╝

  PDF report saved: health_check_report_cluster2_1507.pdf
```

## Configuration

Results are stored in `cluster_access_config.yaml`:

```yaml
clusters:
  my_cluster:
    nodes:
    - hana01
    - hana02
nodes:
  hana01:
    hostname: hana01
    ssh_reachable: true
    preferred_method: ssh
```

### Viewing Configuration

```bash
# Show all discovered clusters and nodes
./cluster_health_check.py --show-config

# Show config for a specific cluster
./cluster_health_check.py --show-config my_cluster

# Show config for cluster containing a specific node
./cluster_health_check.py -S hana01
```

**Example Output:**

```
--- Cluster: my_cluster ---
    Nodes: hana01, hana02
    Discovered from: hana01
    Discovered at: 2026-04-16T16:30:40
    Cluster status: Running

    Cluster Configuration:
    --------------------------------------------
      # Node 1
      node1_hostname: hana01
      node1_fqdn: hana01.example.com
      node1_ip: 192.168.5.232

      # Node 2
      node2_hostname: hana02
      node2_fqdn: hana02.example.com
      node2_ip: 192.168.5.233

      # Virtual IP Configuration
      vip: 192.168.5.231
      vip_resource: vip_RH2_HDB00
      secondary_vip: 192.168.5.234

      # System Replication
      replication_mode: sync
      operation_mode: logreplay
      site1_name: DC1

      # STONITH/Fencing
      stonith_device: my_fence
      pcmk_host_map: hana01:hana01-ipmi;hana02:hana02-ipmi

      # Cluster Properties
      automated_register: true
      prefer_site_takeover: true
      duplicate_primary_timeout: 7200
      secondary_read: true
```

Delete with `-D` to restart the investigation from scratch.

## Extending Health Checks

See [docs/EXTENDING_HEALTH_CHECKS.md](docs/EXTENDING_HEALTH_CHECKS.md) for details on creating custom health check rules.

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
