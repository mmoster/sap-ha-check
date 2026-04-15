# How to Use SAP HANA Cluster Health Check

A quick guide to validating your SAP HANA Pacemaker cluster configuration.

## What It Does

This tool runs 22 automated health checks against your SAP HANA HA cluster, covering:

- Cluster quorum and node status
- STONITH/fencing configuration
- SAP HANA System Replication status
- HA/DR provider hooks
- Package consistency across nodes

It works with **live clusters** (via SSH) or **offline analysis** (via SOSreports).

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

## Example 4: Interactive Mode

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
| `-L` | List all available health checks |
| `-S` | Show discovered cluster config |
| `-d` | Debug mode (verbose output) |
| `--no-pdf` | Skip PDF report generation |
| `-D` | Delete cached config, start fresh |

---

## Cluster Types Detected

The tool automatically detects:

- **Scale-Up**: 2 HANA nodes (standard HA)
- **Scale-Out**: Multiple HANA nodes + majority maker

Different validation rules apply to each type.

---

## Tips

1. **First run takes longer** - it discovers and caches cluster topology
2. **Use `-f`** to force re-discovery if nodes changed
3. **SOSreport analysis is safe** - no SSH access needed
4. **PDF reports** are great for sharing with support teams

---

## Quick Reference

```bash
# On a cluster node
./cluster_health_check.py --local

# Remote check
./cluster_health_check.py hana01 hana02

# SOSreport analysis
./cluster_health_check.py -s ./sosreports/

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
