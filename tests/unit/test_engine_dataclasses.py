"""Tests for engine dataclasses (CheckResult, RuleDefinition, Dispatch*)."""

from sap_ha_check.rules.engine import (
    CheckResult,
    CheckStatus,
    Severity,
    RuleDefinition,
    DispatchCheckEntry,
    DispatchPhase,
    DispatchStep,
)


class TestCheckResult:
    def test_post_init_initializes_details(self):
        result = CheckResult()
        assert result.details == {}

    def test_details_not_overwritten_when_provided(self):
        result = CheckResult(details={"key": "value"})
        assert result.details == {"key": "value"}

    def test_keyword_construction(self):
        result = CheckResult(
            check_id="CHK_TEST",
            description="Test check",
            status=CheckStatus.PASSED,
            severity=Severity.INFO,
            message="All good",
            details={"foo": "bar"},
            node="node1",
        )
        assert result.check_id == "CHK_TEST"
        assert result.description == "Test check"
        assert result.status == CheckStatus.PASSED
        assert result.severity == Severity.INFO
        assert result.message == "All good"
        assert result.details == {"foo": "bar"}
        assert result.node == "node1"

    def test_defaults_are_none(self):
        result = CheckResult()
        assert result.check_id is None
        assert result.description is None
        assert result.status is None
        assert result.severity is None
        assert result.message is None
        assert result.node is None


class TestRuleDefinition:
    def test_post_init_initializes_raw_yaml(self):
        rule = RuleDefinition()
        assert rule.raw_yaml == {}

    def test_raw_yaml_not_overwritten_when_provided(self):
        rule = RuleDefinition(raw_yaml={"check_id": "CHK_TEST"})
        assert rule.raw_yaml == {"check_id": "CHK_TEST"}

    def test_defaults(self):
        rule = RuleDefinition()
        assert rule.check_id is None
        assert rule.version is None
        assert rule.severity is None
        assert rule.description is None
        assert rule.enabled is True
        assert rule.optional is False
        assert rule.hana_nodes_only is False
        assert rule.source_definitions is None
        assert rule.parser is None
        assert rule.validation_logic is None
        assert rule.topology_filter is None
        assert rule.requires is None

    def test_keyword_construction(self):
        rule = RuleDefinition(
            check_id="CHK_TEST",
            version="2.0",
            severity="CRITICAL",
            description="A test rule",
            enabled=False,
            optional=True,
            hana_nodes_only=True,
            topology_filter="Scale-Up",
            requires="CHK_OTHER",
        )
        assert rule.check_id == "CHK_TEST"
        assert rule.version == "2.0"
        assert rule.severity == "CRITICAL"
        assert rule.enabled is False
        assert rule.optional is True
        assert rule.hana_nodes_only is True
        assert rule.topology_filter == "Scale-Up"
        assert rule.requires == "CHK_OTHER"


class TestDispatchCheckEntry:
    def test_topology_none_normalized_to_all(self):
        entry = DispatchCheckEntry(check_id="CHK_TEST", topology=None)
        assert entry.topology == "all"

    def test_topology_all_stays_all(self):
        entry = DispatchCheckEntry(check_id="CHK_TEST", topology="all")
        assert entry.topology == "all"

    def test_topology_string_normalized_to_list(self):
        entry = DispatchCheckEntry(check_id="CHK_TEST", topology="Scale-Up")
        assert entry.topology == ["Scale-Up"]

    def test_topology_list_stays_list(self):
        entry = DispatchCheckEntry(check_id="CHK_TEST", topology=["Scale-Up", "Scale-Out"])
        assert entry.topology == ["Scale-Up", "Scale-Out"]

    def test_defaults(self):
        entry = DispatchCheckEntry()
        assert entry.check_id is None
        assert entry.topology == "all"
        assert entry.gate is None


class TestDispatchPhase:
    def test_post_init_initializes_checks(self):
        phase = DispatchPhase()
        assert phase.checks == []

    def test_checks_not_overwritten_when_provided(self):
        checks = [DispatchCheckEntry(check_id="CHK_A")]
        phase = DispatchPhase(checks=checks)
        assert len(phase.checks) == 1
        assert phase.checks[0].check_id == "CHK_A"

    def test_defaults(self):
        phase = DispatchPhase()
        assert phase.phase == 1
        assert phase.parallel is True
        assert phase.gate is None


class TestDispatchStep:
    def test_post_init_initializes_phases(self):
        step = DispatchStep()
        assert step.phases == []

    def test_phases_not_overwritten_when_provided(self):
        phases = [DispatchPhase(phase=1)]
        step = DispatchStep(phases=phases)
        assert len(step.phases) == 1

    def test_defaults(self):
        step = DispatchStep()
        assert step.name is None
        assert step.step_number == 0

    def test_keyword_construction(self):
        step = DispatchStep(
            name="Test Step",
            step_number=5,
            phases=[DispatchPhase(phase=1), DispatchPhase(phase=2)],
        )
        assert step.name == "Test Step"
        assert step.step_number == 5
        assert len(step.phases) == 2
