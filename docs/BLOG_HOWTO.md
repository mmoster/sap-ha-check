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
- Works with **live clusters** (via SSH) or **offline analysis** (via SOSreports)
- **Detects cluster status** - warns if Pacemaker/Corosync not running
- **Multi-cluster support** - prompts for selection if multiple clusters found
- **Progress indicators** - animated spinner shows work in progress
- **Auto-saves PDF** - reports saved and opened automatically on exit

---

## Installation

```bash
git clone https://github.com/mmoster/sap_hana_healthcheck.git
cd sap_hana_healthcheck
pip install pyyaml fpdf2  # fpdf2 is optional for PDF reports
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

---

## Useful Options

| Option | Description |
|--------|-------------|
| `--local` | Run on current cluster node |
| `-s DIR` | Analyze SOSreports in DIR |
| `-H FILE` | Read hosts from FILE |
| `-u` | Interactive mode |
| `-F CLUSTER` | Fetch SOSreports from nodes (prompts to create if missing) |
| `--create-sosreports` | Auto-create missing SOSreports (use with `-F`) |
| `-L` | List all available health checks |
| `-S` | Show discovered cluster config |
| `-d` | Debug mode (verbose output) |
| `--no-pdf` | Skip PDF report generation |
| `-D` | Delete cached config, start fresh |

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
5. **Cluster not running?** - tool detects this and falls back to static config from corosync.conf
6. **Multiple clusters?** - tool prompts you to select which cluster to analyze

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

# Interactive
./cluster_health_check.py -u

# List checks
./cluster_health_check.py -L

# Debug mode
./cluster_health_check.py -d --local
```

---

## Next Steps

- See [README.md](../README.md) for full documentation
- See [EXTENDING_HEALTH_CHECKS.md](EXTENDING_HEALTH_CHECKS.md) to create custom rules
