"""Tests for RulesEngine.get_summary() and get_data_source_info()."""

from tool.sap_cluster_checks.rules.engine import RulesEngine, CheckResult, CheckStatus, Severity


class TestGetSummary:
    def test_empty_results(self):
        engine = RulesEngine()
        summary = engine.get_summary()
        assert summary["total"] == 0
        assert summary["passed"] == 0
        assert summary["failed"] == 0
        assert summary["skipped"] == 0
        assert summary["errors"] == 0
        assert summary["critical_failures"] == []
        assert summary["warnings"] == []

    def test_all_passed(self):
        engine = RulesEngine()
        engine.results = [
            CheckResult(check_id="CHK_1", status=CheckStatus.PASSED, severity=Severity.INFO),
            CheckResult(check_id="CHK_2", status=CheckStatus.PASSED, severity=Severity.INFO),
        ]
        summary = engine.get_summary()
        assert summary["total"] == 2
        assert summary["passed"] == 2
        assert summary["failed"] == 0

    def test_mixed_results(self):
        engine = RulesEngine()
        engine.results = [
            CheckResult(check_id="CHK_1", status=CheckStatus.PASSED, severity=Severity.INFO),
            CheckResult(check_id="CHK_2", status=CheckStatus.FAILED, severity=Severity.CRITICAL),
            CheckResult(check_id="CHK_3", status=CheckStatus.FAILED, severity=Severity.WARNING),
            CheckResult(check_id="CHK_4", status=CheckStatus.SKIPPED, severity=Severity.INFO),
            CheckResult(check_id="CHK_5", status=CheckStatus.ERROR, severity=Severity.CRITICAL),
        ]
        summary = engine.get_summary()
        assert summary["total"] == 5
        assert summary["passed"] == 1
        assert summary["failed"] == 2
        assert summary["skipped"] == 1
        assert summary["errors"] == 1

    def test_critical_failures_collected(self):
        engine = RulesEngine()
        critical = CheckResult(
            check_id="CHK_CRIT", status=CheckStatus.FAILED, severity=Severity.CRITICAL
        )
        engine.results = [critical]
        summary = engine.get_summary()
        assert len(summary["critical_failures"]) == 1
        assert summary["critical_failures"][0].check_id == "CHK_CRIT"

    def test_warnings_collected(self):
        engine = RulesEngine()
        warning = CheckResult(
            check_id="CHK_WARN", status=CheckStatus.FAILED, severity=Severity.WARNING
        )
        engine.results = [warning]
        summary = engine.get_summary()
        assert len(summary["warnings"]) == 1
        assert summary["warnings"][0].check_id == "CHK_WARN"

    def test_info_failures_go_to_warnings(self):
        engine = RulesEngine()
        info_fail = CheckResult(
            check_id="CHK_INFO", status=CheckStatus.FAILED, severity=Severity.INFO
        )
        engine.results = [info_fail]
        summary = engine.get_summary()
        assert len(summary["warnings"]) == 1
        assert len(summary["critical_failures"]) == 0


class TestGetDataSourceInfo:
    def test_no_methods_returns_no_data(self):
        engine = RulesEngine()
        info = engine.get_data_source_info()
        assert info["primary_method"] == "unknown"
        assert info["description"] == "No data collected"
        assert info["used_cib_xml"] is False
        assert info["access_methods"] == {}

    def test_ssh_method(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "ssh", "node2": "ssh"}
        info = engine.get_data_source_info()
        assert info["primary_method"] == "ssh"
        assert info["description"] == "Live cluster via SSH"

    def test_sosreport_with_cib_xml(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "sosreport"}
        engine._used_cib_xml = True
        info = engine.get_data_source_info()
        assert info["primary_method"] == "sosreport"
        assert "cluster was stopped" in info["description"]
        assert info["used_cib_xml"] is True

    def test_sosreport_without_cib_xml(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "sosreport"}
        engine._used_cib_xml = False
        info = engine.get_data_source_info()
        assert info["primary_method"] == "sosreport"
        assert "offline" in info["description"].lower()

    def test_local_method(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "local"}
        info = engine.get_data_source_info()
        assert info["primary_method"] == "local"
        assert "Local" in info["description"]

    def test_ansible_method(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "ansible"}
        info = engine.get_data_source_info()
        assert info["primary_method"] == "ansible"
        assert "Ansible" in info["description"]

    def test_mixed_methods_uses_most_common(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "ssh", "node2": "ssh", "node3": "sosreport"}
        info = engine.get_data_source_info()
        assert info["primary_method"] == "ssh"

    def test_unknown_method(self):
        engine = RulesEngine()
        engine._access_methods_used = {"node1": "custom_method"}
        info = engine.get_data_source_info()
        assert info["primary_method"] == "custom_method"
        assert "custom_method" in info["description"]
