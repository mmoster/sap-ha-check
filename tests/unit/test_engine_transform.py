"""Tests for RulesEngine._transform_pcs_for_cib()."""

from tool.sap_cluster_checks.rules.engine import RulesEngine


def _transform(cmd):
    """Helper: call _transform_pcs_for_cib on a fresh engine."""
    engine = RulesEngine()
    return engine._transform_pcs_for_cib(cmd)


class TestTransformPcsForCib:
    def test_pcs_property(self):
        result = _transform("pcs property config")
        assert result is not None
        assert f"-f {RulesEngine.CIB_PATH}" in result
        assert "property" in result

    def test_pcs_resource_config(self):
        result = _transform("pcs resource config")
        assert result is not None
        assert f"-f {RulesEngine.CIB_PATH}" in result
        assert "resource" in result

    def test_pcs_stonith_config(self):
        result = _transform("pcs stonith config")
        assert result is not None
        assert f"-f {RulesEngine.CIB_PATH}" in result
        assert "stonith" in result

    def test_pcs_constraint(self):
        result = _transform("pcs constraint")
        assert result is not None
        assert f"-f {RulesEngine.CIB_PATH}" in result
        assert "constraint" in result

    def test_non_pcs_command_returns_none(self):
        result = _transform("systemctl status pacemaker")
        assert result is None

    def test_pcs_status_returns_none(self):
        result = _transform("pcs status")
        assert result is None

    def test_pcs_cluster_returns_none(self):
        result = _transform("pcs cluster status")
        assert result is None

    def test_transformed_command_format(self):
        result = _transform("pcs resource config")
        expected = f"pcs -f {RulesEngine.CIB_PATH} resource config"
        assert result == expected
