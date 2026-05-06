# How to Use SAP HANA Cluster Health Check

A quick guide to validating your SAP HANA Pacemaker cluster configuration.

## What It Does

This tool runs 22 automated health checks against your SAP HANA HA cluster, covering:

- Cluster quorum and node status
- STONITH/fencing configuration
- SAP HANA System Replication status
- HA/DR provider hooks
- Package consistency across nodes

**Key features:**
- Works with **live clusters** (via SSH), **local execution**, or **offline analysis** (via SOSreports)
- **Detects cluster status** - warns if Pacemaker/Corosync not running
- **Multi-cluster support** - prompts for selection if multiple clusters found
- **Version detection** - automatically detects RHEL and Pacemaker versions
- **HANA status detection** - identifies SID, instance, sidadm user, and running processes
- **Progress indicators** - animated spinner shows work in progress
- **Auto-saves PDF** - reports saved and opened automatically on exit

---

## Installation

### Option 1: Using git (recommended)

```bash
# Install git if not available
sudo dnf install git    # RHEL/Fedora
sudo yum install git    # RHEL 7

# Clone and run
git clone https://github.com/mmoster/sap-ha-check.git
cd sap-ha-check
pip install pyyaml fpdf2  # fpdf2 is optional for PDF reports
./cluster_health_check.py --local
```

### Option 2: Download without git

```bash
# Download and extract
curl -L https://github.com/mmoster/sap-ha-check/archive/refs/heads/main.tar.gz | tar xz
cd sap-ha-check-main
pip install pyyaml fpdf2  # fpdf2 is optional for PDF reports
./cluster_health_check.py --local
```

---

## Example 1: Check a Live Cluster (Local)

Run directly on a cluster node:

```bash
./cluster_health_check.py --local
```

The tool automatically discovers all cluster nodes from Pacemaker.

---

## Example 2: Check Remote Nodes via SSH

Specify hostnames directly:

```bash
./cluster_health_check.py hana01 hana02
```

Or use a hosts file:

```bash
# hosts.txt
hana01
hana02

./cluster_health_check.py -H hosts.txt
```

---

## Example 3: Analyze SOSreports Offline

Perfect for support cases or post-mortem analysis:

```bash
./cluster_health_check.py -s /path/to/sosreports/
```

The tool extracts and analyzes SOSreport archives (`.tar.xz`, `.tar.gz`) automatically.

---

## Example 4: Fetch SOSreports from Cluster

Download existing SOSreports from cluster nodes:

```bash
# Fetch from all nodes in a cluster
./cluster_health_check.py -F mycluster

# Fetch from specific nodes
./cluster_health_check.py -F hana01 hana02
```

If no SOSreports exist on the nodes, the tool prompts you to create them:

```
  [hana01] ✗ No SOSreport found
  [hana02] ✗ No SOSreport found

Missing SOSreports on 2 node(s): hana01, hana02

Create SOSreports on these nodes? [y/N]: y
```

To auto-create without prompting:

```bash
./cluster_health_check.py -F mycluster --create-sosreports
```

### Complete SOSreport Collection Workflow

For a comprehensive workflow that discovers the cluster, configures SAP extensions,
creates and fetches SOSreports in one command:

```bash
# Provide any cluster node - all others will be discovered
./cluster_health_check.py -R hana01

# Auto-configure SAP extensions without prompting
./cluster_health_check.py -R hana01 --configure-extensions
```

This workflow:
1. Discovers cluster name and all nodes from the seed node
2. Checks SSH access to all nodes (skips unreachable ones)
3. Checks and optionally configures SAP SOSreport extensions
4. Creates SOSreports in parallel with cluster name as label
5. Fetches SOSreports via SCP to local `./sosreports/` directory

**SAP Extensions** enhance SOSreport data collection by adding:
- `SAPHanaSR-showAttr` output (critical for SR analysis)
- Cluster state snapshots (`crm_mon`, `pcs status`)
- Resource and constraint configurations

---

## Example 5: Interactive Mode

Don't remember where your sosreports are? Use interactive mode:

```bash
./cluster_health_check.py -u
```

This scans the current directory for:
- SOSreport archives
- Hosts files
- Previous health check results

Then presents a menu to choose what to analyze.

---

## Understanding the Output

A successful run looks like:

```
Health Check Results:
  PASSED:   22  FAILED:   0  SKIPPED:   0  ERROR:   0

  ╔═══════════════════════════════════════════════════════╗
  ║            ✓  CLUSTER IS HEALTHY  ✓                   ║
  ╚═══════════════════════════════════════════════════════╝

  PDF report saved: health_check_report_mycluster_1507.pdf
```

A problem is shown as:

```
  ✗ FAILED: CHK_STONITH_CONFIG
    STONITH is disabled - fencing is required for production clusters
    Severity: CRITICAL
```

### PDF Report Example

The tool auto-generates a PDF report. Here's what the first page looks like for a healthy cluster:

```
╔═══════════════════════════════════════════════════════════════╗
║         SAP Pacemaker Cluster Health Check Report             ║
╚═══════════════════════════════════════════════════════════════╝

  Cluster:          production_hana
  Date:             2026-05-06 14:30:22
  Data Source:      Live cluster analysis
  Nodes:            hana01, hana02
  Cluster Type:     Scale-Up

  RHEL Version:     RHEL 9.4
  Pacemaker:        2.1.7
  SAP HANA SID:     PRD (Instance: 00)

  ╔═══════════════════════════════════════════════════════════╗
  ║                                                           ║
  ║             ✓  CLUSTER IS HEALTHY  ✓                      ║
  ║                                                           ║
  ║      All health checks passed successfully.               ║
  ║      Your SAP HANA cluster is properly configured.        ║
  ║                                                           ║
  ╚═══════════════════════════════════════════════════════════╝

  Summary:
    PASSED:   22    FAILED:   0    SKIPPED:   0    ERROR:   0
```

The following pages contain a detailed results table:

```
  Health Check Results
  ─────────────────────────────────────────────────────────────

  #   Check                    Node     Status   Severity
  ──  ───────────────────────  ───────  ──────   ────────
   1  CHK_NODE_STATUS          cluster  PASSED   CRITICAL
      Verify all cluster nodes are online

   2  CHK_CLUSTER_QUORUM       cluster  PASSED   CRITICAL
      Verify cluster has quorum

   3  CHK_STONITH_CONFIG       cluster  PASSED   CRITICAL
      Verify STONITH/fencing is enabled and configured

   4  CHK_RESOURCE_STATUS      cluster  PASSED   CRITICAL
      Verify SAP HANA cluster resources are running

   5  CHK_HANA_SR_STATUS       cluster  PASSED   CRITICAL
      Verify HANA System Replication status is healthy

   6  CHK_PACKAGE_CONSISTENCY  hana01   PASSED   WARNING
      pacemaker-2.1.7 | corosync-3.1.8 | sap-hana-ha-1.2.12

   7  CHK_PACKAGE_CONSISTENCY  hana02   PASSED   WARNING
      pacemaker-2.1.7 | corosync-3.1.8 | sap-hana-ha-1.2.12
      ...
```

Use `-v` for verbose reports that include all checks with full details — ideal for audits and compliance documentation.

---

## Useful Options

| Option | Description |
|--------|-------------|
| `--local` | Run on current cluster node |
| `-s DIR` | Analyze SOSreports in DIR |
| `-H FILE` | Read hosts from FILE |
| `-u` | Interactive mode |
| `-F CLUSTER` | Fetch SOSreports from nodes (prompts to create if missing) |
| `-R NODE` | Complete SOSreport workflow: discover cluster, configure SAP extensions, create & fetch |
| `--create-sosreports` | Auto-create missing SOSreports (use with `-F`) |
| `--configure-extensions` | Auto-configure SAP extensions (use with `-R`) |
| `-L` | List all available health checks |
| `-S` | Show discovered cluster config |
| `-d` | Debug mode (verbose output) |
| `-v, --verbose` | Verbose PDF - show all checks in detail, not just failures |
| `--no-pdf` | Skip PDF report generation |
| `-D` | Delete cached config, start fresh |

---

## Viewing Cluster Configuration

Use `-S` or `--show-config` to display the discovered cluster configuration:

```bash
./cluster_health_check.py -S hana01
```

**Example Output:**

```
--- Cluster: my_cluster ---
    Nodes: hana01, hana02
    Cluster status: Running

    Cluster Configuration:
    --------------------------------------------
      # Node 1
      node1_hostname: hana01
      node1_fqdn: hana01.example.com
      node1_ip: 192.168.5.232

      # Virtual IP Configuration
      vip: 192.168.5.231
      secondary_vip: 192.168.5.234

      # System Replication
      replication_mode: sync
      operation_mode: logreplay

      # STONITH/Fencing
      stonith_device: my_fence
      pcmk_host_map: hana01:hana01-ipmi;hana02:hana02-ipmi

      # Cluster Properties
      automated_register: true
      prefer_site_takeover: true
      duplicate_primary_timeout: 7200
```

This configuration is also included in verbose PDF reports (`-v`).

---

## Cluster Types Detected

The tool automatically detects:

- **Scale-Up**: 2 HANA nodes (+ optional additional cluster nodes like ASCS servers)
- **Scale-Out**: Multiple HANA nodes + majority maker

Additional cluster nodes that don't run HANA are correctly identified and don't cause failures.

---

## Tips

1. **First run takes longer** - it discovers and caches cluster topology
2. **Use `-f`** to force re-discovery if nodes changed
3. **SOSreport analysis is safe** - no SSH access needed
4. **PDF reports** are great for sharing with support teams
5. **Use `-v` for detailed PDFs** - shows all checks, not just failures (great for audits)
6. **Cluster not running?** - tool detects this and falls back to static config from corosync.conf
7. **Multiple clusters?** - tool prompts you to select which cluster to analyze
8. **HANA status** - detects sidadm user and runs `HDB info` to show process count

---

## Quick Reference

```bash
# On a cluster node
./cluster_health_check.py --local

# Remote check
./cluster_health_check.py hana01 hana02

# SOSreport analysis
./cluster_health_check.py -s ./sosreports/

# Fetch SOSreports (prompts to create if missing)
./cluster_health_check.py -F mycluster

# Auto-create and fetch SOSreports
./cluster_health_check.py -F mycluster --create-sosreports

# Complete SOSreport collection (discover + configure + create + fetch)
./cluster_health_check.py -R hana01

# Interactive
./cluster_health_check.py -u

# Verbose PDF (show all checks in detail)
./cluster_health_check.py --local -v

# List checks
./cluster_health_check.py -L

# Debug mode
./cluster_health_check.py -d --local
```

---

## Next Steps

- See [README.md](../README.md) for full documentation
- See [EXTENDING_HEALTH_CHECKS.md](EXTENDING_HEALTH_CHECKS.md) to create custom rules
