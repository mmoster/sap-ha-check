#!/usr/bin/env python3
"""
Rules Engine for SAP Pacemaker Cluster Health Check

Loads and executes health check rules from YAML files.
Supports both live command execution and SOSreport parsing.
"""

import os
import re
import yaml
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

# Python 3.6 compatibility for dataclasses
try:
    from dataclasses import dataclass, field
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


class Severity(Enum):
    """Check severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class CheckStatus(Enum):
    """Check result status."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class CheckResult:
    """Result of a single health check."""
    check_id: str = None
    description: str = None
    status: CheckStatus = None
    severity: Severity = None
    message: str = None
    details: Dict[str, Any] = None
    node: Optional[str] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


@dataclass
class RuleDefinition:
    """Parsed rule definition from YAML."""
    check_id: str = None
    version: str = None
    severity: str = None
    description: str = None
    enabled: bool = True
    optional: bool = False  # If True, failures are warnings in non-strict mode
    source_definitions: Dict[str, Any] = None
    parser: Dict[str, Any] = None
    validation_logic: Dict[str, Any] = None
    topology_filter: Optional[str] = None
    requires: Optional[str] = None  # Check ID that must pass before this one runs
    raw_yaml: Dict[str, Any] = None

    def __post_init__(self):
        if self.raw_yaml is None:
            self.raw_yaml = {}


class RulesEngine:
    """Engine for loading and executing health check rules."""

    # TODO: Add CHK_*.yaml health check rules to this directory
    DEFAULT_RULES_PATH = str(Path(__file__).parent / "health_checks")
    CMD_TIMEOUT = 15  # Reduced from 30 to avoid long waits
    MAX_WORKERS = 5
    CIB_PATH = "/var/lib/pacemaker/cib/cib.xml"

    def __init__(self, rules_path: str = None, access_config: dict = None, strict_mode: bool = False):
        self.rules_path = Path(rules_path) if rules_path else Path(self.DEFAULT_RULES_PATH)
        self.access_config = access_config or {}
        self.rules: List[RuleDefinition] = []
        self.results: List[CheckResult] = []
        self.strict_mode = strict_mode
        # Track cluster running state and cib.xml availability per node
        self._cluster_running: Dict[str, bool] = {}
        self._cib_available: Dict[str, bool] = {}

    def load_rules(self) -> List[RuleDefinition]:
        """Load all CHK_*.yaml rule files."""
        self.rules = []

        if not self.rules_path.exists():
            print(f"[WARNING] Rules path does not exist: {self.rules_path}")
            return self.rules

        rule_files = sorted(self.rules_path.glob("CHK_*.yaml"))
        print(f"Found {len(rule_files)} rule files in {self.rules_path}")

        for rule_file in rule_files:
            try:
                with open(rule_file, 'r') as f:
                    data = yaml.safe_load(f)

                if not data or not data.get('enabled', True):
                    print(f"  [SKIP] {rule_file.name} (disabled)")
                    continue

                rule = RuleDefinition(
                    check_id=data.get('check_id', rule_file.stem),
                    version=data.get('version', '1.0'),
                    severity=data.get('severity', 'WARNING'),
                    description=data.get('description', ''),
                    enabled=data.get('enabled', True),
                    optional=data.get('optional', False),
                    source_definitions=data.get('source_definitions', {}),
                    parser=data.get('parser', {}),
                    validation_logic=data.get('validation_logic', {}),
                    topology_filter=data.get('topology_filter'),
                    requires=data.get('requires'),
                    raw_yaml=data
                )
                self.rules.append(rule)
                print(f"  [LOAD] {rule.check_id}: {rule.description[:50]}...")

            except Exception as e:
                print(f"  [ERROR] Failed to load {rule_file.name}: {e}")

        return self.rules

    def list_rules(self) -> List[Dict[str, str]]:
        """Return a summary list of loaded rules."""
        return [
            {
                'check_id': r.check_id,
                'severity': r.severity,
                'description': r.description,
                'enabled': r.enabled
            }
            for r in self.rules
        ]

    def _check_cluster_status(self, node: str, method: str = 'ssh', user: str = None) -> Tuple[bool, bool]:
        """
        Check if cluster is running and if cib.xml exists on a node.
        Returns (cluster_running, cib_available) tuple.
        Caches results per node.
        """
        if node in self._cluster_running:
            return self._cluster_running[node], self._cib_available.get(node, False)

        # Check if pacemaker is running
        cluster_running = False
        cib_available = False

        check_cmd = "systemctl is-active pacemaker 2>/dev/null"
        success, output = self._execute_command_raw(check_cmd, node, method, user)
        # Check for exact 'active' status (not 'inactive')
        cluster_running = success and output.strip() == 'active'

        # Check if cib.xml exists
        cib_check_cmd = f"test -f {self.CIB_PATH} && echo 'exists'"
        success, output = self._execute_command_raw(cib_check_cmd, node, method, user)
        cib_available = success and 'exists' in output

        self._cluster_running[node] = cluster_running
        self._cib_available[node] = cib_available

        return cluster_running, cib_available

    def _transform_pcs_for_cib(self, cmd: str) -> str:
        """
        Transform pcs commands to use -f cib.xml for offline cluster queries.
        Only transforms commands that can work with -f flag.
        """
        # Commands that support -f flag for offline queries
        pcs_offline_cmds = ['pcs property', 'pcs resource', 'pcs stonith', 'pcs constraint']

        for pcs_cmd in pcs_offline_cmds:
            if pcs_cmd in cmd:
                # Insert -f cib.xml after 'pcs'
                # Handle: pcs property -> pcs -f /path/cib.xml property
                # Also handle: pcs resource config -> pcs -f /path/cib.xml resource config
                transformed = cmd.replace(pcs_cmd, f"pcs -f {self.CIB_PATH} {pcs_cmd.split()[1]}")
                return transformed

        return None  # Command cannot be transformed

    def _execute_command_raw(self, cmd: str, node: str = None,
                             method: str = 'ssh', user: str = None) -> Tuple[bool, str]:
        """Execute a command without fallback logic (internal use)."""
        try:
            if method == 'local':
                full_cmd = cmd
            elif node and method == 'ssh':
                ssh_user = user or os.environ.get('USER', 'root')
                if ssh_user != 'root':
                    cmd = f"sudo {cmd}"
                escaped_cmd = cmd.replace("'", "'\"'\"'")
                full_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_user}@{node} '{escaped_cmd}'"
            elif node and method == 'ansible':
                escaped_cmd = cmd.replace("'", "'\"'\"'")
                full_cmd = f"ansible {node} -m shell -a '{escaped_cmd}' -o"
            else:
                full_cmd = cmd

            result = subprocess.run(
                full_cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=self.CMD_TIMEOUT
            )

            output = result.stdout
            if method == 'ansible' and node:
                if '|' in output and '>>' in output:
                    output = output.split('>>', 1)[-1].strip()

            return result.returncode == 0, output

        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {self.CMD_TIMEOUT}s"
        except Exception as e:
            return False, str(e)

    def _execute_command(self, cmd: str, node: str = None,
                        method: str = 'ssh', user: str = None) -> Tuple[bool, str]:
        """Execute a command locally, via SSH, or via Ansible.
        Uses pcs -f cib.xml if cluster is not running but cib.xml exists."""
        # For pcs commands, pre-check if cluster is running
        # If not running but cib.xml exists, use -f cib.xml from the start
        if 'pcs ' in cmd and node:
            cluster_running, cib_available = self._check_cluster_status(node, method, user)

            if not cluster_running and cib_available:
                # Transform pcs command to use -f cib.xml
                transformed_cmd = self._transform_pcs_for_cib(cmd)
                if transformed_cmd:
                    return self._execute_command_raw(transformed_cmd, node, method, user)

        # Execute the original command
        return self._execute_command_raw(cmd, node, method, user)

    def _read_sosreport(self, sos_path: str, node: str, sos_base: str) -> Tuple[bool, str]:
        """Read data from SOSreport directory."""
        import glob as glob_module

        sos_base_path = Path(sos_base)

        # If sos_base is a direct sosreport path (contains etc/ dir), use it directly
        if (sos_base_path / "etc").exists():
            node_sos = sos_base_path
        else:
            # Build full path - sos_base is a directory containing sosreports
            node_sos = sos_base_path / node
            if not node_sos.exists():
                # Try to find matching sosreport directory
                for item in sos_base_path.iterdir():
                    if item.is_dir() and node in item.name:
                        node_sos = item
                        break

        # Check if sos_path contains glob patterns
        if '*' in sos_path or '?' in sos_path:
            # Use glob to find matching files
            pattern = str(node_sos / sos_path)
            matches = glob_module.glob(pattern)
            if matches:
                # Use first matching file
                try:
                    with open(matches[0], 'r') as f:
                        return True, f.read()
                except Exception as e:
                    return False, str(e)
            return False, f"No files matching pattern: {pattern}"

        file_path = node_sos / sos_path
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    return True, f.read()
            except Exception as e:
                return False, str(e)

        return False, f"File not found: {file_path}"

    def _parse_output(self, output: str, parser_config: Dict) -> Dict[str, Any]:
        """Parse command output using configured parser."""
        parsed = {}

        if parser_config.get('type') != 'regex':
            return {'raw': output}

        patterns = parser_config.get('search_patterns', [])
        flags = re.MULTILINE if parser_config.get('multiline', False) else 0

        for pattern in patterns:
            name = pattern.get('name')
            regex = pattern.get('regex')
            group = pattern.get('group', 0)

            if not name or not regex:
                continue

            try:
                match = re.search(regex, output, flags)
                if match:
                    if group == 0:
                        parsed[name] = match.group(0)
                    else:
                        parsed[name] = match.group(group) if group <= len(match.groups()) else None
                else:
                    parsed[name] = None
            except Exception as e:
                parsed[name] = None
                parsed[f'{name}_error'] = str(e)

        return parsed

    def _handle_detection_check(self, rule: RuleDefinition, parsed: Dict, node: str) -> CheckResult:
        """Handle detection-type checks that gather information rather than validate."""
        if rule.check_id == 'CHK_CLUSTER_TYPE':
            return self._detect_cluster_type(rule, parsed, node)

        # Default: return parsed data as info
        return CheckResult(
            check_id=rule.check_id,
            description=rule.description,
            status=CheckStatus.PASSED,
            severity=Severity.INFO,
            message="Detection completed",
            details={'parsed': parsed},
            node=node
        )

    def _detect_cluster_type(self, rule: RuleDefinition, parsed: Dict, node: str) -> CheckResult:
        """Detect SAP HANA HA cluster configuration type.

        Configuration types:
        - Scale-Up: Exactly 2 nodes, NO majority maker, uses SAPHana resource
        - Scale-Out: 4+ HANA nodes (2+ per site) + 1 majority maker, uses SAPHanaController

        Majority maker node should NOT have sap-hana-ha or resource-agents-sap-hana-scaleout.
        If it does, location constraints and resource-discovery=never must be configured.
        """
        # Extract parsed values
        node_count_str = parsed.get('node_count')
        saphana_resource = parsed.get('saphana_resource')  # SAPHana_* = Scale-Up
        saphana_controller = parsed.get('saphana_controller')  # SAPHanaController_* = Scale-Out
        majority_maker = parsed.get('majority_maker')

        # Count nodes
        try:
            node_count = int(node_count_str) if node_count_str else 0
        except (ValueError, TypeError):
            node_count = 0

        # Detect based on resource agent type (the definitive indicator)
        has_saphana = saphana_resource is not None  # Scale-Up uses SAPHana resource
        has_controller = saphana_controller is not None  # Scale-Out uses SAPHanaController
        has_majority_maker = majority_maker is not None and majority_maker != 'none'

        # Determine cluster type
        cluster_type = "Unknown"
        details = {
            'node_count': node_count,
            'has_saphana_resource': has_saphana,
            'has_saphana_controller': has_controller,
            'has_majority_maker': has_majority_maker,
            'parsed': parsed
        }

        if node_count == 0:
            cluster_type = "Not detected"
            message = "Could not detect cluster configuration (cluster may not be running)"
        elif has_controller:
            # SAPHanaController = Scale-Out (2+ HANA nodes per site + majority maker)
            cluster_type = "Scale-Out"
            if has_majority_maker:
                # Expected: 4+ HANA nodes + 1 majority maker = 5+ total
                hana_nodes = node_count - 1  # Subtract majority maker
                message = f"Scale-Out configuration ({hana_nodes} HANA nodes + majority maker)"
            else:
                message = f"Scale-Out configuration ({node_count} nodes) - WARNING: no majority maker detected"
        elif has_saphana:
            # SAPHana resource = Scale-Up (exactly 2 nodes, no majority maker)
            cluster_type = "Scale-Up"
            if node_count == 2 and not has_majority_maker:
                message = "Scale-Up configuration (2 nodes, standard HA)"
            elif has_majority_maker:
                # Scale-Up should NOT have majority maker
                message = f"Scale-Up with {node_count} nodes - WARNING: majority maker detected but Scale-Up should be 2 nodes only"
            else:
                message = f"Scale-Up configuration ({node_count} nodes) - WARNING: expected 2 nodes"
        elif node_count == 1:
            # 1 node - single node (no HA)
            cluster_type = "Single Node"
            message = "Single node configuration (no HA)"
        else:
            # No HANA resources detected but cluster exists
            cluster_type = "Unknown"
            message = f"Cluster detected ({node_count} nodes) but no SAP HANA resources found"

        details['cluster_type'] = cluster_type

        return CheckResult(
            check_id=rule.check_id,
            description=rule.description,
            status=CheckStatus.PASSED,
            severity=Severity.INFO,
            message=message,
            details=details,
            node=node
        )

    def _validate_clone_max(self, rule: RuleDefinition, parsed: Dict, node: str) -> CheckResult:
        """Validate clone-max setting for SAPHanaController and SAPHanaTopology.

        For Scale-Out clusters:
        - clone-max should equal the number of HANA nodes (total nodes - majority makers)
        - clone-node-max should be 1
        - interleave should be true
        """
        issues = []
        info = []

        # Get clone-max values
        controller_clone_max = parsed.get('controller_clone_max')
        topology_clone_max = parsed.get('topology_clone_max')
        controller_clone_node_max = parsed.get('controller_clone_node_max')
        topology_clone_node_max = parsed.get('topology_clone_node_max')
        controller_interleave = parsed.get('controller_interleave')
        topology_interleave = parsed.get('topology_interleave')
        controller_promotable = parsed.get('controller_promotable')

        # Check if we have any data
        if not controller_clone_max and not topology_clone_max:
            # No clone config found - might be using pcs -f cib.xml or cluster not running
            return CheckResult(
                check_id=rule.check_id,
                description=rule.description,
                status=CheckStatus.PASSED,
                severity=Severity.INFO,
                message="Clone configuration not available (cluster may be stopped)",
                details={'parsed': parsed},
                node=node
            )

        # Validate clone-node-max = 1
        if controller_clone_node_max and controller_clone_node_max != '1':
            issues.append(f"SAPHanaController clone-node-max={controller_clone_node_max} (should be 1)")
        if topology_clone_node_max and topology_clone_node_max != '1':
            issues.append(f"SAPHanaTopology clone-node-max={topology_clone_node_max} (should be 1)")

        # Validate interleave = true
        if controller_interleave and controller_interleave != 'true':
            issues.append(f"SAPHanaController interleave={controller_interleave} (should be true)")
        if topology_interleave and topology_interleave != 'true':
            issues.append(f"SAPHanaTopology interleave={topology_interleave} (should be true)")

        # Validate promotable = true for controller
        if controller_promotable and controller_promotable != 'true':
            issues.append(f"SAPHanaController promotable={controller_promotable} (should be true)")

        # Report clone-max values (informational - we can't validate without knowing HANA node count)
        if controller_clone_max:
            info.append(f"SAPHanaController clone-max={controller_clone_max}")
        if topology_clone_max:
            info.append(f"SAPHanaTopology clone-max={topology_clone_max}")

        # Check if controller and topology have matching clone-max
        if controller_clone_max and topology_clone_max and controller_clone_max != topology_clone_max:
            issues.append(f"clone-max mismatch: Controller={controller_clone_max}, Topology={topology_clone_max}")

        if issues:
            return CheckResult(
                check_id=rule.check_id,
                description=rule.description,
                status=CheckStatus.FAILED,
                severity=Severity.WARNING,
                message="; ".join(issues),
                details={'parsed': parsed, 'issues': issues},
                node=node
            )

        # All checks passed
        message = "Clone configuration valid"
        if info:
            message += f" ({'; '.join(info)})"

        return CheckResult(
            check_id=rule.check_id,
            description=rule.description,
            status=CheckStatus.PASSED,
            severity=Severity.INFO,
            message=message,
            details={'parsed': parsed, 'info': info},
            node=node
        )

    def _evaluate_expectation(self, parsed: Dict, expectation: Dict) -> Tuple[bool, str, str]:
        """Evaluate a single expectation against parsed data.

        Returns: (passed, fail_message, pass_message)

        Special operators:
        - info_if_exists: Always passes, but shows pass_message if key exists (informational)
        """
        key = expectation.get('key')
        operator = expectation.get('operator')
        expected = expectation.get('value')
        message = expectation.get('message', f"Check failed for {key}")
        pass_message = expectation.get('pass_message')  # Optional message shown when expectation passes

        actual = parsed.get(key)

        # Handle info_if_exists: always passes, shows message if key exists
        if operator == 'info_if_exists':
            if actual is not None and pass_message:
                return True, message, pass_message
            return True, message, None

        if operator == 'exists':
            # 'exists' checks if the key has a non-None value
            # If value is specified as False, check that key does NOT exist
            if expected is False:
                passed = actual is None
            else:
                # Default: pass if actual exists (is not None)
                passed = actual is not None
        elif operator == 'not_exists':
            passed = actual is None
        elif operator == 'eq':
            passed = actual == expected
        elif operator == 'ne':
            passed = actual != expected
        elif operator == 'in':
            passed = actual in expected if isinstance(expected, list) else actual == expected
        elif operator == 'not_in':
            passed = actual not in expected if isinstance(expected, list) else actual != expected
        elif operator == 'contains':
            passed = expected in str(actual) if actual else False
        elif operator == 'regex':
            passed = bool(re.search(expected, str(actual))) if actual else False
        elif operator == 'gt':
            try:
                passed = float(actual) > float(expected)
            except (TypeError, ValueError):
                passed = False
        elif operator == 'lt':
            try:
                passed = float(actual) < float(expected)
            except (TypeError, ValueError):
                passed = False
        else:
            passed = False
            message = f"Unknown operator: {operator}"

        return passed, message, pass_message if passed else None

    def _check_command_available(self, cmd: str, node: str, method: str, user: str = None) -> tuple:
        """
        Quick check if any command in a pipeline/fallback chain is available.
        Returns (available: bool, reason: str)

        Handles:
        - Simple commands: 'SAPHanaSR-showAttr'
        - Pipelines: 'cmd1 | grep foo'
        - Fallbacks: 'cmd1 || cmd2' (if cmd1 not available, check cmd2)
        - Multi-line scripts with comments
        - Shell constructs (if/for/while)
        """
        builtins = ['grep', 'cat', 'echo', 'awk', 'sed', 'head', 'tail', 'cut', 'tr', 'sort', 'timeout',
                    'if', 'for', 'while', 'then', 'else', 'fi', 'do', 'done', 'case', 'esac', 'ls', 'test', '[']

        def extract_cmd_name(cmd_part: str) -> str:
            """Extract the primary command name from a command string."""
            # Remove leading whitespace
            cmd_part = cmd_part.strip()

            # Skip empty parts and comments
            if not cmd_part or cmd_part.startswith('#'):
                return ''

            # For multi-line commands, find first non-comment, non-empty line
            lines = cmd_part.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Split on pipe to get first command in pipeline
                    first_part = line.split('|')[0].split(';')[0].split('&&')[0].strip()
                    # Get the command name (first word)
                    cmd_name = first_part.split()[0] if first_part else ''
                    if cmd_name and not cmd_name.startswith('#'):
                        return cmd_name
            return ''

        # Split on '||' to handle fallback commands
        fallback_parts = cmd.split('||')

        for part in fallback_parts:
            cmd_name = extract_cmd_name(part)

            # Skip empty command names
            if not cmd_name:
                continue

            # Skip check for built-in commands and common utilities
            if cmd_name in builtins or cmd_name.startswith('/'):
                return True, "builtin/path"

            # Check if command exists (locally or on remote node)
            check_cmd = f"command -v {cmd_name} >/dev/null 2>&1 && echo 'OK' || echo 'MISSING'"
            success, output = self._execute_command(check_cmd, node, method, user)

            if success and 'OK' in output:
                return True, f"{cmd_name} available"

        # If we get here, either all commands were builtins (which is fine) or none were found
        all_cmds = [extract_cmd_name(p) for p in fallback_parts if extract_cmd_name(p)]
        if not all_cmds:
            # All commands were builtins/shell constructs
            return True, "shell script"
        return False, f"Commands not found on {node}: {', '.join(all_cmds)}"

    def _run_check_on_node(self, rule: RuleDefinition, node: str,
                          method: str, user: str = None,
                          sos_base: str = None) -> CheckResult:
        """Run a single check on a specific node."""
        source_defs = rule.source_definitions

        # Get data based on access method
        if method == 'sosreport' and sos_base:
            sos_path = source_defs.get('sos_path')
            alternates = source_defs.get('sos_path_alternates', [])
            success, output = self._read_sosreport(sos_path, node, sos_base)
            # Also try alternates if output contains error indicators (cluster was stopped)
            if not success or (success and output.strip().startswith('Error:')):
                for alt_path in alternates:
                    alt_success, alt_output = self._read_sosreport(alt_path, node, sos_base)
                    if alt_success and not alt_output.strip().startswith('Error:'):
                        success, output = alt_success, alt_output
                        break
        else:
            cmd = source_defs.get('live_cmd')
            if not cmd:
                return CheckResult(
                    check_id=rule.check_id,
                    description=rule.description,
                    status=CheckStatus.SKIPPED,
                    severity=Severity[rule.severity],
                    message="No live command defined",
                    node=node
                )

            # Pre-flight check: verify primary command is available
            preflight = source_defs.get('preflight_check', True)
            if preflight:
                cmd_available, reason = self._check_command_available(cmd, node, method, user)
                if not cmd_available:
                    return CheckResult(
                        check_id=rule.check_id,
                        description=rule.description,
                        status=CheckStatus.SKIPPED,
                        severity=Severity[rule.severity],
                        message=f"Skipped: {reason}",
                        node=node
                    )

            success, output = self._execute_command(cmd, node, method, user)

        if not success:
            return CheckResult(
                check_id=rule.check_id,
                description=rule.description,
                status=CheckStatus.ERROR,
                severity=Severity[rule.severity],
                message=f"Failed to get data: {output[:100]}",
                node=node
            )

        # Parse output
        parsed = self._parse_output(output, rule.parser)

        # Handle detection-type checks (e.g., CHK_CLUSTER_TYPE)
        validation = rule.validation_logic
        if validation.get('type') == 'detection':
            return self._handle_detection_check(rule, parsed, node)

        # Handle custom checks (e.g., clone_max_validation)
        custom_check = validation.get('custom_check')
        if custom_check == 'clone_max_validation':
            return self._validate_clone_max(rule, parsed, node)

        # Evaluate expectations
        expectations = validation.get('expectations', [])
        match_mode = validation.get('match_mode', 'all')  # 'all' (default) or 'any'

        failed_expectations = []
        passed_expectations = []
        info_messages = []  # Collect informational messages from passing expectations
        for exp in expectations:
            passed, message, pass_msg = self._evaluate_expectation(parsed, exp)
            if not passed:
                failed_expectations.append({
                    'key': exp.get('key'),
                    'severity': exp.get('severity', rule.severity),
                    'message': message
                })
            else:
                passed_expectations.append(exp)
                if pass_msg:
                    info_messages.append(pass_msg)

        # match_mode: any - pass if at least one expectation passes
        # match_mode: all (default) - fail if any expectation fails
        check_failed = False
        if match_mode == 'any':
            # Pass if ANY expectation passed
            check_failed = len(passed_expectations) == 0
        else:
            # Fail if ANY expectation failed
            check_failed = len(failed_expectations) > 0

        if check_failed:
            # Use highest severity from failed expectations
            max_severity = rule.severity
            for fe in failed_expectations:
                if fe['severity'] == 'CRITICAL':
                    max_severity = 'CRITICAL'
                    break
                elif fe['severity'] == 'WARNING' and max_severity != 'CRITICAL':
                    max_severity = 'WARNING'

            # In non-strict mode, downgrade optional checks from CRITICAL to WARNING
            if rule.optional and not self.strict_mode and max_severity == 'CRITICAL':
                max_severity = 'WARNING'

            return CheckResult(
                check_id=rule.check_id,
                description=rule.description,
                status=CheckStatus.FAILED,
                severity=Severity[max_severity],
                message="; ".join(fe['message'] for fe in failed_expectations),
                details={'parsed': parsed, 'failed': failed_expectations, 'optional': rule.optional},
                node=node
            )

        # Build result message - include info messages if any
        result_message = "All checks passed"
        if info_messages:
            result_message = "; ".join(info_messages)

        return CheckResult(
            check_id=rule.check_id,
            description=rule.description,
            status=CheckStatus.PASSED,
            severity=Severity[rule.severity],
            message=result_message,
            details={'parsed': parsed, 'info_messages': info_messages},
            node=node
        )

    def run_check(self, rule: RuleDefinition, nodes: Dict[str, dict]) -> List[CheckResult]:
        """
        Run a check across nodes based on scope.

        Scope modes:
        - per_node: Check each node independently (default)
        - any_node: Pass if at least one node passes
        - all_nodes_equal: All nodes must return the same parsed values
        - cluster: Run only on one node (cluster-wide info)
        """
        results = []
        scope = rule.validation_logic.get('scope', 'per_node')
        compare_keys = rule.validation_logic.get('compare_keys', [])

        # For 'cluster' scope, only run on first accessible node
        if scope == 'cluster':
            for node_name, node_info in nodes.items():
                method = node_info.get('preferred_method')
                if method:
                    user = node_info.get('ssh_user') or node_info.get('ansible_user')
                    sos_base = self.access_config.get('sosreport_directory')
                    result = self._run_check_on_node(rule, node_name, method, user, sos_base)
                    result.node = f"{node_name} (cluster)"
                    return [result]
            # No accessible node
            return [CheckResult(
                check_id=rule.check_id,
                description=rule.description,
                status=CheckStatus.SKIPPED,
                severity=Severity[rule.severity],
                message="No accessible node for cluster check",
                node=None
            )]

        # Run on all nodes (multithreaded)
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {}

            for node_name, node_info in nodes.items():
                method = node_info.get('preferred_method')
                if not method:
                    results.append(CheckResult(
                        check_id=rule.check_id,
                        description=rule.description,
                        status=CheckStatus.SKIPPED,
                        severity=Severity[rule.severity],
                        message="No access method available",
                        node=node_name
                    ))
                    continue

                user = node_info.get('ssh_user') or node_info.get('ansible_user')
                # Use node's specific sosreport_path if available, otherwise fall back to sosreport_directory
                sos_path = node_info.get('sosreport_path') or self.access_config.get('sosreport_directory')

                future = executor.submit(
                    self._run_check_on_node,
                    rule, node_name, method, user, sos_path
                )
                futures[future] = node_name

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append(CheckResult(
                        check_id=rule.check_id,
                        description=rule.description,
                        status=CheckStatus.ERROR,
                        severity=Severity[rule.severity],
                        message=str(e),
                        node=futures[future]
                    ))

        # Handle scope-specific logic
        if scope == 'any_node':
            # Pass if at least one node passed
            passed = [r for r in results if r.status == CheckStatus.PASSED]
            if passed:
                return [CheckResult(
                    check_id=rule.check_id,
                    description=rule.description,
                    status=CheckStatus.PASSED,
                    severity=Severity[rule.severity],
                    message=f"Passed on {len(passed)}/{len(results)} node(s)",
                    details={'passed_nodes': [r.node for r in passed]},
                    node=None
                )]
            else:
                return [CheckResult(
                    check_id=rule.check_id,
                    description=rule.description,
                    status=CheckStatus.FAILED,
                    severity=Severity[rule.severity],
                    message="Failed on all nodes",
                    details={'results': [{'node': r.node, 'message': r.message} for r in results]},
                    node=None
                )]

        elif scope == 'all_nodes_equal':
            # All nodes must have the same values for compare_keys
            passed_results = [r for r in results if r.status == CheckStatus.PASSED]
            if len(passed_results) < 2:
                return results  # Not enough nodes to compare

            # Get values to compare
            if not compare_keys:
                # Use all parsed keys
                compare_keys = list(passed_results[0].details.get('parsed', {}).keys())

            # Compare values across nodes
            mismatches = []
            reference_node = passed_results[0].node
            reference_values = passed_results[0].details.get('parsed', {})

            for result in passed_results[1:]:
                node_values = result.details.get('parsed', {})
                for key in compare_keys:
                    ref_val = reference_values.get(key)
                    node_val = node_values.get(key)
                    if ref_val != node_val:
                        mismatches.append({
                            'key': key,
                            'node': result.node,
                            'expected': ref_val,
                            'actual': node_val
                        })

            if mismatches:
                # SAP HANA package keys - differences in these on majority maker nodes are expected
                sap_hana_package_keys = {
                    'sap_hana_ha_version', 'resource_agents_sap_hana',
                    'resource_agents_sap_hana_scaleout', 'saphanasr_version'
                }

                # Build detailed message about differences
                missing_packages = []  # Package exists on some nodes but not others
                version_diffs = []     # Same package, different versions
                critical_mismatches = []  # Non-SAP-HANA package mismatches (always report)
                sap_hana_mismatches = []  # SAP HANA package mismatches (may be expected on majority maker)

                for m in mismatches:
                    key = m['key']
                    expected = m.get('expected')
                    actual = m.get('actual')
                    is_sap_hana_pkg = key in sap_hana_package_keys

                    if expected is None and actual is not None:
                        # Package only on this node (extra package)
                        msg = f"{key}: only on {m['node']} ({actual})"
                        missing_packages.append(msg)
                        if is_sap_hana_pkg:
                            sap_hana_mismatches.append(m)
                        else:
                            critical_mismatches.append(m)
                    elif expected is not None and actual is None:
                        # Package missing on this node
                        msg = f"{key}: missing on {m['node']} (reference: {expected})"
                        missing_packages.append(msg)
                        if is_sap_hana_pkg:
                            sap_hana_mismatches.append(m)
                        else:
                            critical_mismatches.append(m)
                    elif expected != actual:
                        # Different versions
                        msg = f"{key}: {m['node']} has {actual} (reference: {expected})"
                        version_diffs.append(msg)
                        if is_sap_hana_pkg:
                            sap_hana_mismatches.append(m)
                        else:
                            critical_mismatches.append(m)

                # Determine status: if only SAP HANA package differences, it's INFO (expected for majority maker)
                only_sap_hana_diffs = len(critical_mismatches) == 0 and len(sap_hana_mismatches) > 0

                # Build message with details
                msg_parts = []
                if version_diffs:
                    msg_parts.append(f"Version mismatch: {'; '.join(version_diffs[:3])}")
                    if len(version_diffs) > 3:
                        msg_parts.append(f"...and {len(version_diffs) - 3} more")
                if missing_packages:
                    msg_parts.append(f"Package differences: {'; '.join(missing_packages[:3])}")
                    if len(missing_packages) > 3:
                        msg_parts.append(f"...and {len(missing_packages) - 3} more")

                if only_sap_hana_diffs:
                    # Only SAP HANA package differences - expected for majority maker nodes
                    msg_parts.append("(expected for MajorityMaker nodes)")
                    message = " | ".join(msg_parts)
                    results.append(CheckResult(
                        check_id=rule.check_id,
                        description=rule.description,
                        status=CheckStatus.PASSED,
                        severity=Severity.INFO,
                        message=message,
                        details={'mismatches': mismatches, 'reference_node': reference_node, 'majority_maker_expected': True},
                        node="(comparison)"
                    ))
                else:
                    message = " | ".join(msg_parts) if msg_parts else f"Values differ across nodes: {', '.join(set(m['key'] for m in mismatches))}"
                    # Add a comparison failure result
                    results.append(CheckResult(
                        check_id=rule.check_id,
                        description=rule.description,
                        status=CheckStatus.FAILED,
                        severity=Severity[rule.severity],
                        message=message,
                        details={'mismatches': mismatches, 'reference_node': reference_node},
                        node="(comparison)"
                    ))

        return results

    def run_all_checks(self, nodes: Dict[str, dict]) -> List[CheckResult]:
        """Run all loaded checks on all nodes."""
        self.results = []

        if not self.rules:
            self.load_rules()

        print(f"\nRunning {len(self.rules)} checks on {len(nodes)} node(s)...")

        for rule in self.rules:
            print(f"\n  [{rule.severity}] {rule.check_id}: {rule.description[:40]}...")
            check_results = self.run_check(rule, nodes)

            for result in check_results:
                self.results.append(result)
                status_icon = {
                    CheckStatus.PASSED: "✓",
                    CheckStatus.FAILED: "✗",
                    CheckStatus.SKIPPED: "○",
                    CheckStatus.ERROR: "!"
                }.get(result.status, "?")
                node_str = f" ({result.node})" if result.node else ""
                print(f"    {status_icon} {result.status.value}{node_str}: {result.message[:60]}")

        return self.results

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all check results."""
        summary = {
            'total': len(self.results),
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0,
            'critical_failures': [],
            'warnings': []
        }

        for result in self.results:
            if result.status == CheckStatus.PASSED:
                summary['passed'] += 1
            elif result.status == CheckStatus.FAILED:
                summary['failed'] += 1
                if result.severity == Severity.CRITICAL:
                    summary['critical_failures'].append(result)
                else:
                    summary['warnings'].append(result)
            elif result.status == CheckStatus.SKIPPED:
                summary['skipped'] += 1
            elif result.status == CheckStatus.ERROR:
                summary['errors'] += 1

        return summary

    def print_summary(self):
        """Print formatted summary of results."""
        summary = self.get_summary()

        print("\n" + "=" * 63)
        print(" Health Check Results Summary")
        print("=" * 63)
        print(f"  Total checks:  {summary['total']}")
        print(f"  Passed:        {summary['passed']}")
        print(f"  Failed:        {summary['failed']}")
        print(f"  Skipped:       {summary['skipped']}")
        print(f"  Errors:        {summary['errors']}")

        if summary['critical_failures']:
            print("\n  CRITICAL FAILURES:")
            for r in summary['critical_failures']:
                print(f"    - [{r.check_id}] {r.message[:50]}")

        if summary['warnings']:
            print("\n  WARNINGS:")
            for r in summary['warnings'][:5]:  # Show first 5
                print(f"    - [{r.check_id}] {r.message[:50]}")
            if len(summary['warnings']) > 5:
                print(f"    ... and {len(summary['warnings']) - 5} more")
