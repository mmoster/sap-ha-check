# SAP HA Cluster Health Check: Analysis and Troubleshooting Made Easy

If you're responsible for the smooth operation of SAP systems, you know: High Availability (HA) clusters based on Pacemaker and Corosync — commonly used for SAP HANA System Replication or ASCS/ERS — are complex. When something goes wrong, troubleshooting requires deep knowledge and hours of sifting through log files.

This is exactly where the open-source tool [sap-ha-check](https://github.com/mmoster/sap-ha-check) comes in.

---

## What Does sap-ha-check Do?

The tool automates the inspection and analysis of SAP HA clusters. It scans the cluster configuration, node status, SAP-specific resources, and system parameters — uncovering potential issues, misconfigurations, or deviations from best practices. Instead of manually parsing hundreds of lines of `crm_mon` or `corosync.conf` output, the tool delivers structured results and even generates PDF reports.

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
