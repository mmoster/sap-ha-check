# SAP HA Cluster Health Check: Analysis and Troubleshooting Made Easy

If you're responsible for the smooth operation of SAP systems, you know: High Availability (HA) clusters based on Pacemaker and Corosync — commonly used for SAP HANA System Replication or ASCS/ERS — are complex. When something goes wrong, troubleshooting requires deep knowledge and hours of sifting through log files.

This is exactly where the open-source tool [sap-ha-check](https://github.com/mmoster/sap-ha-check) comes in.

---

## What Does sap-ha-check Do?

The tool automates the inspection and analysis of SAP HA clusters. It scans the cluster configuration, node status, SAP-specific resources, and system parameters — uncovering potential issues, misconfigurations, or deviations from best practices. Instead of manually parsing hundreds of lines of `crm_mon` or `corosync.conf` output, the tool delivers structured results and even generates PDF reports.

The current version focuses on **SAP HANA Scale-Up** and **Scale-Out** configurations — the most common HA setups in the SAP landscape. Support for **ASCS/ERS** (SAP Central Services) environments is planned for a future release.

---

## Smart Cluster Auto-Discovery

One of the tool's standout features is its intelligent cluster discovery. You don't need to know or specify every node in the cluster — just provide a single seed node, and the tool automatically discovers all remaining cluster members from the Pacemaker configuration. Whether you specify one node or all of them, it contacts every node in the cluster to ensure a complete analysis:

```bash
# Just provide one node - the tool discovers the rest
./cluster_health_check.py hana01

# The tool automatically finds hana02 (and any other members)
# and runs checks across the entire cluster
```

This works across all access methods: SSH, local execution, and even SOSreport analysis, where it reads the `corosync.conf` inside the SOSreport to identify all cluster members and resolves hostname aliases automatically.

---

## How Is It Used? (Maximum Flexibility)

A huge advantage of sap-ha-check is how flexibly it integrates into your daily workflow. You can run it directly on a cluster node, pull data remotely via SSH, or — and this is especially useful for support engineers and consultants — work offline with existing SOSreports.

When you start the tool in interactive mode (e.g., with `./cluster_health_check.py -u`), it immediately demonstrates its intelligence through automatic detection of available resources:

```
[INFO] A newer version is available (2 commit(s) behind)
  Update to latest version? [y/N] (auto-skip in 20s):
  No response, skipping update.

===============================================================
 Scanning for resources...
===============================================================
  Base directory: /home/mmoster/Downloads/cba/sap-ha-check

---------------------------------------------------------------
 Found Resources
---------------------------------------------------------------
  SOSreports (extracted):   2
    - sosreport-ANL0117800957-syz2bns2dbn01-04434954-2026-04-30-llelmqq
    - sosreport-ANL0117800960-syz3bns2dbn01-04434954-2026-04-30-beyfnpx
  Hosts files:              1
    - /home/mmoster/Downloads/cba/sap-ha-check/tests/hana04_discovery/hosts.txt
  Former results:           1
    - last_run_status.yaml
  PDF reports:              4
  Config files:             2

---------------------------------------------------------------
 Options
---------------------------------------------------------------
  [d] Delete former results and config, then run health check
  [c] Continue with existing configuration
  [s] Analyze sosreports in /home/mmoster/Downloads/cba/sap-ha-check/sosreports
  [i] Use inventory/hosts file: /home/mmoster/Downloads/cba/sap-ha-check/tests/hana04_discovery/hosts.txt
  [f] Fetch SOSreports from cluster (enter one node to discover all)
  [n] Enter hostnames manually
  [l] Run locally (on this cluster node)
  [h] Show help and examples
  [q] Quit
---------------------------------------------------------------

  Your choice: s
```

In this example, the user simply selects `s`. The tool picks up the two locally extracted SOSreports and analyzes the cluster state at the exact point in time when the reports were created — completely without access to the actual servers.

---

## What Does the Report Look Like?

After running all checks, the tool generates a PDF report automatically. Here's what the first page of a healthy cluster report looks like:

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

The following pages contain a detailed results table for each check:

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

   6  CHK_QUORUM_CONFIG        hana01   PASSED   CRITICAL
      Validate quorum configuration for 2-node cluster

   7  CHK_QUORUM_CONFIG        hana02   PASSED   CRITICAL
      Validate quorum configuration for 2-node cluster

   8  CHK_PACKAGE_CONSISTENCY  hana01   PASSED   WARNING
      pacemaker-2.1.7 | corosync-3.1.8 | sap-hana-ha-1.2.12

   9  CHK_PACKAGE_CONSISTENCY  hana02   PASSED   WARNING
      pacemaker-2.1.7 | corosync-3.1.8 | sap-hana-ha-1.2.12
      ...
```

When issues are detected, the report clearly highlights them with severity levels and remediation guidance. Use the `-v` flag for verbose reports that include all checks with full details — ideal for audits and compliance documentation.

---

## How Can You Extend the Tool?

Since sap-ha-check is written in Python, it can be adapted to your own or customer-specific requirements. New checks can be added as YAML-based rule files — see [EXTENDING_HEALTH_CHECKS.md](EXTENDING_HEALTH_CHECKS.md) for the full guide.

Here are two simple examples of extensions:

### Example 1: Check a Custom Corosync Parameter

Suppose your company policy requires the Corosync `token` timeout to be set to `30000` (30 seconds). You can add a check that reads the parsed `corosync.conf`:

```python
def check_corosync_token_timeout(corosync_config):
    token_value = corosync_config.get('totem', {}).get('token')
    if token_value != '30000':
        return {"status": "WARNING", "msg": f"Corosync token is {token_value}, expected 30000!"}
    return {"status": "OK", "msg": "Corosync token is correct."}
```

### Example 2: Verify OS-Specific Tuning Tools

For SAP HANA, operating system tuning is essential. You could extend the tool to check whether `saptune` or `sapconf` is active by querying the systemd service:

```python
def check_saptune_active(node_data):
    # node_data contains collected system info (from live query or sosreport)
    if 'saptune' in node_data['services'] and node_data['services']['saptune'] == 'active':
        return {"status": "OK", "msg": "saptune daemon is active"}
    return {"status": "ERROR", "msg": "saptune is not running! Performance issues possible."}
```

---

## Conclusion

If you work in SAP Basis operations and manage Linux clusters, you should definitely take a closer look at sap-ha-check. It saves valuable time, helps proactively prevent errors, and — thanks to its Python foundation — can be extended to match your own policies and guidelines.

**Tip:** You can copy this article into your blog system (e.g., WordPress, Medium, or an internal Confluence page) and add screenshots of the generated PDF reports for illustration.

---

## Getting Started

```bash
git clone https://github.com/mmoster/sap-ha-check.git
cd sap-ha-check
./cluster_health_check.py --local
```

- [Full Documentation (README)](../README.md)
- [How-To Guide (BLOG_HOWTO.md)](BLOG_HOWTO.md)
- [Extending Health Checks](EXTENDING_HEALTH_CHECKS.md)
- [GitHub Repository](https://github.com/mmoster/sap-ha-check)
