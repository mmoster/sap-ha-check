"""Tests for RulesEngine._validate_clone_max()."""

from sap_ha_check.rules.engine import RulesEngine, RuleDefinition, CheckStatus, Severity


def _validate(parsed, rule=None):
    """Helper: call _validate_clone_max on a fresh engine."""
    engine = RulesEngine()
    if rule is None:
        rule = RuleDefinition(
            check_id="CHK_CLONE_CONFIG",
            description="Validate clone configuration",
            severity="WARNING",
        )
    return engine._validate_clone_max(rule, parsed, "node1")


class TestValidConfig:
    def test_all_correct(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.PASSED
        assert "valid" in result.message.lower()

    def test_scale_up_valid(self):
        parsed = {
            "controller_clone_max": "2",
            "topology_clone_max": "2",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.PASSED


class TestInvalidCloneNodeMax:
    def test_controller_clone_node_max_not_1(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "2",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED
        assert "clone-node-max=2" in result.message

    def test_topology_clone_node_max_not_1(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "3",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED
        assert "Topology" in result.message


class TestInvalidInterleave:
    def test_controller_interleave_not_true(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "1",
            "controller_interleave": "false",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED
        assert "interleave=false" in result.message

    def test_topology_interleave_not_true(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "false",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED


class TestInvalidPromotable:
    def test_controller_promotable_not_true(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "false",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED
        assert "promotable=false" in result.message


class TestCloneMaxMismatch:
    def test_controller_topology_mismatch(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "6",
            "controller_clone_node_max": "1",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED
        assert "mismatch" in result.message.lower()
        assert "Controller=4" in result.message
        assert "Topology=6" in result.message


class TestNoCloneConfig:
    def test_no_clone_config_passes_with_info(self):
        parsed = {
            "controller_clone_max": None,
            "topology_clone_max": None,
            "controller_clone_node_max": None,
            "topology_clone_node_max": None,
            "controller_interleave": None,
            "topology_interleave": None,
            "controller_promotable": None,
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.PASSED
        assert result.severity == Severity.INFO
        assert "not available" in result.message.lower()


class TestMultipleIssues:
    def test_multiple_issues_combined(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "6",
            "controller_clone_node_max": "2",
            "topology_clone_node_max": "1",
            "controller_interleave": "false",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.status == CheckStatus.FAILED
        # Should report multiple issues
        assert "clone-node-max=2" in result.message
        assert "interleave=false" in result.message
        assert "mismatch" in result.message.lower()

    def test_failed_result_has_warning_severity(self):
        parsed = {
            "controller_clone_max": "4",
            "topology_clone_max": "4",
            "controller_clone_node_max": "2",
            "topology_clone_node_max": "1",
            "controller_interleave": "true",
            "topology_interleave": "true",
            "controller_promotable": "true",
        }
        result = _validate(parsed)
        assert result.severity == Severity.WARNING
