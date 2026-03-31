# SAP Cluster Health Check - Architecture Analysis

## Health Check YAML Files Location

All health checks are defined in:
```
rules/health_checks/CHK_*.yaml
```

Currently **18 checks** are defined:

| Check ID | Severity | Description |
|----------|----------|-------------|
| `CHK_NODE_STATUS` | CRITICAL | Verify all cluster nodes are online |
| `CHK_PACKAGE_CONSISTENCY` | CRITICAL | Verify package versions across nodes |
| `CHK_CLUSTER_QUORUM` | CRITICAL | Check cluster quorum status |
| `CHK_RESOURCE_STATUS` | CRITICAL | Verify resource status |
| `CHK_QUORUM_CONFIG` | CRITICAL | Quorum configuration |
| `CHK_CIB_TIME_SYNC` | WARNING | CIB time synchronization |
| `CHK_HANA_AUTOSTART` | WARNING | HANA autostart settings |
| `CHK_SYSTEMD_SAP` | WARNING | Systemd SAP service status |
| `CHK_CLUSTER_TYPE` | INFO | Detect Scale-Up vs Scale-Out |
| `CHK_RESOURCE_FAILURES` | CRITICAL | Resource failure count |
| `CHK_MAJORITY_MAKER` | WARNING | Majority maker configuration |
| `CHK_CLONE_CONFIG` | WARNING | Clone resource configuration |
| `CHK_SETUP_VALIDATION` | CRITICAL | SAP HANA HA best practices |
| `CHK_ALERT_FENCING` | WARNING | Alert agent for fencing |
| `CHK_HADR_HOOKS` | WARNING | HADR provider hooks |
| `CHK_MASTER_SLAVE_ROLES` | CRITICAL | Master/slave roles |
| `CHK_SITE_ROLES` | CRITICAL | Site roles |
| `CHK_HANA_SR_STATUS` | CRITICAL | HANA System Replication status |
| `CHK_HANA_INSTALLED` | CRITICAL | HANA installation detection |
| `CHK_STONITH_CONFIG` | CRITICAL | STONITH/fencing configuration |
| `CHK_REPLICATION_MODE` | WARNING | Replication mode (sync/syncmem) |

---

## Architecture Overview

This is a rule-based validation engine that separates:

1. **Data Collection** (`source_definitions`) - how to get data
2. **Parsing** (`parser`) - how to extract values from output
3. **Validation** (`validation_logic`) - what conditions to check

This separation allows checks to work both on **live systems** (via SSH/local commands) and **SOSreports** (offline analysis) with the same validation logic.

---

## How to Extend Existing Tests

### 1. Create a New Health Check YAML

Create a file `rules/health_checks/CHK_YOUR_CHECK.yaml`:

```yaml
# CHK_YOUR_CHECK - Description of what this checks
check_id: CHK_YOUR_CHECK
version: "1.0"
severity: CRITICAL  # CRITICAL | WARNING | INFO
description: Your check description
enabled: true
optional: false  # If true, failures become warnings in non-strict mode

source_definitions:
  # Command to run on live systems
  live_cmd: "your-command-here | grep 'pattern'"
  # Path within SOSreport for offline analysis
  sos_path: "sos_commands/pacemaker/your_file"
  # Optional: alternate paths to try
  sos_path_alternates:
    - "etc/some/config"

parser:
  type: regex
  multiline: true  # Search across multiple lines
  search_patterns:
    - name: my_value
      regex: "pattern_to_match"
      group: 0  # 0 = full match, 1+ = capture group

validation_logic:
  scope: cluster  # See scope options below
  expectations:
    - key: my_value
      operator: exists
      value: true
      message: "Error message when check fails"
```

### 2. Available Scope Options

| Scope | Behavior |
|-------|----------|
| `cluster` | Run on **one node only** (cluster-wide info) |
| `per_node` | Check **each node independently** (default) |
| `any_node` | Pass if **at least one node** passes |
| `all_nodes_equal` | All nodes must have **identical values** |

### 3. Available Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `exists` | Value is not None | Check if pattern was found |
| `not_exists` | Value is None | Ensure error pattern is absent |
| `eq` / `ne` | Equal / Not equal | `value: "expected"` |
| `in` / `not_in` | In list | `value: ["a", "b", "c"]` |
| `contains` | Substring match | `value: "substring"` |
| `regex` | Regex match | `value: "pattern.*"` |
| `gt` / `lt` | Greater/less than | `value: 10` |
| `info_if_exists` | Always passes, shows info | Informational only |

### 4. Advanced Features

#### Override Severity Per-Expectation

```yaml
expectations:
  - key: stonith_disabled
    operator: not_exists
    severity: WARNING  # Override rule's CRITICAL severity
    message: "STONITH disabled (testing only)"
```

#### Match Mode (any vs all)

```yaml
validation_logic:
  match_mode: any  # Pass if ANY expectation passes (default: all)
```

#### Pass Messages (Informational)

```yaml
expectations:
  - key: syncmem_mode
    operator: info_if_exists
    pass_message: "Using syncmem mode (consider sync for max security)"
```

#### Detection-Type Checks (No Pass/Fail)

```yaml
validation_logic:
  type: detection  # Informational gathering only
  expectations: []
```

#### Compare Values Across Nodes

```yaml
validation_logic:
  scope: all_nodes_equal
  compare_keys:
    - pacemaker_version
    - corosync_version
```

---

## Example: Adding a New Check

**Check if cluster has no failed actions:**

```yaml
# rules/health_checks/CHK_FAILED_ACTIONS.yaml
check_id: CHK_FAILED_ACTIONS
version: "1.0"
severity: WARNING
description: Check for failed actions in cluster history
enabled: true

source_definitions:
  live_cmd: "pcs status 2>/dev/null | grep -E 'Failed|failure' || echo 'NO_FAILURES'"
  sos_path: "sos_commands/pacemaker/crm_mon_-1"

parser:
  type: regex
  multiline: true
  search_patterns:
    - name: has_failures
      regex: "(Failed|failure)"
      group: 0
    - name: no_failures
      regex: "NO_FAILURES"
      group: 0

validation_logic:
  scope: cluster
  expectations:
    - key: has_failures
      operator: not_exists
      message: "Cluster has failed actions - review with 'pcs status'"
```

---

## Processing Flow

```
CHK_*.yaml → engine.load_rules() → engine.run_all_checks()
                                           ↓
                    ┌──────────────────────┴──────────────────────┐
                    │ For each rule:                              │
                    │  1. Execute live_cmd OR read sos_path       │
                    │  2. Parse output with regex patterns        │
                    │  3. Evaluate expectations                   │
                    │  4. Return CheckResult (PASSED/FAILED/...)  │
                    └─────────────────────────────────────────────┘
```

---

## Key Files

| File | Purpose |
|------|---------|
| `rules/engine.py` | Rules engine that processes YAML checks |
| `rules/health_checks/CHK_*.yaml` | Health check definitions |
| `cluster_health_check.py` | Main CLI entry point |
| `report_generator.py` | PDF/YAML report generation |

---

## Design Philosophy

The engine uses a **declarative approach** where you describe *what* to check, not *how* to check it. The `rules/engine.py` handles:

- Command execution (local/SSH/Ansible)
- SOSreport file reading
- Regex parsing
- Expectation evaluation
- Result aggregation

This means adding new checks requires **zero Python code** - just YAML configuration.
