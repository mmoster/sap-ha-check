"""Tests for the configuration matrix."""

import pytest
from hadr_provider.models import ArchType, Topology
from hadr_provider.config_matrix import (
    get_expected_config,
    detect_arch_type,
    validate_rhel_arch_compatibility,
)


# ---------------------------------------------------------------------------
# validate_rhel_arch_compatibility
# ---------------------------------------------------------------------------

class TestRhelArchCompatibility:
    def test_rhel8_legacy_valid(self):
        valid, msg = validate_rhel_arch_compatibility(8, ArchType.LEGACY)
        assert valid is True
        assert msg == ""

    def test_rhel8_angi_invalid(self):
        valid, msg = validate_rhel_arch_compatibility(8, ArchType.ANGI)
        assert valid is False
        assert "RHEL 8" in msg

    def test_rhel9_legacy_valid(self):
        valid, msg = validate_rhel_arch_compatibility(9, ArchType.LEGACY)
        assert valid is True

    def test_rhel9_angi_valid(self):
        valid, msg = validate_rhel_arch_compatibility(9, ArchType.ANGI)
        assert valid is True

    def test_rhel10_angi_valid(self):
        valid, msg = validate_rhel_arch_compatibility(10, ArchType.ANGI)
        assert valid is True

    def test_rhel10_legacy_invalid(self):
        valid, msg = validate_rhel_arch_compatibility(10, ArchType.LEGACY)
        assert valid is False
        assert "RHEL 10" in msg


# ---------------------------------------------------------------------------
# detect_arch_type
# ---------------------------------------------------------------------------

class TestDetectArchType:
    def test_angi_package(self):
        assert detect_arch_type(['sap-hana-ha-1.0.0-1.el9']) == ArchType.ANGI

    def test_legacy_scaleup_package(self):
        assert detect_arch_type(['resource-agents-sap-hana-0.162.3-1.el9']) == ArchType.LEGACY

    def test_legacy_scaleout_package(self):
        assert detect_arch_type(['resource-agents-sap-hana-scaleout-0.180.0-1.el9']) == ArchType.LEGACY

    def test_angi_takes_precedence(self):
        pkgs = ['sap-hana-ha-1.0.0', 'resource-agents-sap-hana-0.162.3']
        assert detect_arch_type(pkgs) == ArchType.ANGI

    def test_no_packages(self):
        assert detect_arch_type([]) is None

    def test_unrelated_packages(self):
        assert detect_arch_type(['pacemaker-2.1.9', 'corosync-3.1.8']) is None


# ---------------------------------------------------------------------------
# get_expected_config -- ANGI combinations
# ---------------------------------------------------------------------------

class TestExpectedConfigAngi:
    @pytest.mark.parametrize("rhel,topo", [
        (9, Topology.SCALE_UP),
        (9, Topology.SCALE_OUT),
        (10, Topology.SCALE_UP),
        (10, Topology.SCALE_OUT),
    ])
    def test_angi_main_hook(self, rhel, topo):
        cfg = get_expected_config(rhel, topo, ArchType.ANGI, 'S4D')
        main = cfg.hooks[0]
        assert main.section_name == 'ha_dr_provider_hanasr'
        assert main.provider == 'HanaSR'
        assert main.path == '/usr/share/sap-hana-ha/'
        assert main.execution_order == 1
        assert main.is_optional is False

    @pytest.mark.parametrize("rhel,topo", [
        (9, Topology.SCALE_UP),
        (10, Topology.SCALE_OUT),
    ])
    def test_angi_chksrv_hook_optional(self, rhel, topo):
        cfg = get_expected_config(rhel, topo, ArchType.ANGI, 'S4D')
        chksrv = cfg.hooks[1]
        assert chksrv.section_name == 'ha_dr_provider_chksrv'
        assert chksrv.provider == 'ChkSrv'
        assert chksrv.is_optional is True
        assert chksrv.action_on_lost == 'stop'

    def test_angi_trace(self):
        cfg = get_expected_config(9, Topology.SCALE_UP, ArchType.ANGI, 'S4D')
        assert 'ha_dr_hanasr' in cfg.trace.entries
        assert 'ha_dr_chksrv' in cfg.trace.entries

    def test_angi_sudoers_requiretty(self):
        cfg = get_expected_config(9, Topology.SCALE_UP, ArchType.ANGI, 'S4D')
        assert any('requiretty' in e.description for e in cfg.sudoers_entries)

    def test_angi_sudoers_crm_attribute_wildcard(self):
        cfg = get_expected_config(9, Topology.SCALE_UP, ArchType.ANGI, 'S4D')
        crm = next(e for e in cfg.sudoers_entries if 'crm_attribute' in e.description)
        assert 'hana_*' in crm.example_line
        # Should NOT have SID-specific wildcard
        assert 'hana_s4d_*' not in crm.example_line

    def test_angi_provider_files(self):
        cfg = get_expected_config(9, Topology.SCALE_UP, ArchType.ANGI, 'S4D')
        assert '/usr/share/sap-hana-ha/HanaSR.py' in cfg.provider_files


# ---------------------------------------------------------------------------
# get_expected_config -- Legacy combinations
# ---------------------------------------------------------------------------

class TestExpectedConfigLegacy:
    @pytest.mark.parametrize("rhel,topo", [
        (8, Topology.SCALE_UP),
        (8, Topology.SCALE_OUT),
        (9, Topology.SCALE_UP),
        (9, Topology.SCALE_OUT),
    ])
    def test_legacy_main_hook(self, rhel, topo):
        cfg = get_expected_config(rhel, topo, ArchType.LEGACY, 'S4D')
        main = cfg.hooks[0]
        assert main.section_name == 'ha_dr_provider_SAPHanaSR'
        assert main.provider == 'SAPHanaSR'
        assert main.path == '/usr/share/SAPHanaSR'
        assert main.execution_order == 1
        assert main.is_optional is False

    def test_legacy_suschksrv_optional(self):
        cfg = get_expected_config(8, Topology.SCALE_UP, ArchType.LEGACY, 'S4D')
        chksrv = cfg.hooks[1]
        assert chksrv.section_name == 'ha_dr_provider_suschksrv'
        assert chksrv.provider == 'susChkSrv'
        assert chksrv.is_optional is True

    def test_legacy_trace(self):
        cfg = get_expected_config(8, Topology.SCALE_UP, ArchType.LEGACY, 'S4D')
        assert 'ha_dr_saphanasr' in cfg.trace.entries
        # Legacy should NOT have ha_dr_hanasr (that's ANGI)
        assert 'ha_dr_hanasr' not in cfg.trace.entries

    def test_legacy_sudoers_sid_specific(self):
        cfg = get_expected_config(8, Topology.SCALE_UP, ArchType.LEGACY, 'S4D')
        crm = next(e for e in cfg.sudoers_entries if 'crm_attribute' in e.description)
        assert 'hana_s4d_*' in crm.example_line

    def test_legacy_sudoers_no_requiretty(self):
        cfg = get_expected_config(8, Topology.SCALE_UP, ArchType.LEGACY, 'S4D')
        assert not any('requiretty' in e.description for e in cfg.sudoers_entries)

    def test_legacy_provider_files(self):
        cfg = get_expected_config(8, Topology.SCALE_UP, ArchType.LEGACY, 'S4D')
        assert '/usr/share/SAPHanaSR/SAPHanaSR.py' in cfg.provider_files


# ---------------------------------------------------------------------------
# Invalid combinations
# ---------------------------------------------------------------------------

class TestInvalidCombinations:
    def test_angi_on_rhel8_raises(self):
        with pytest.raises(ValueError, match="RHEL 8"):
            get_expected_config(8, Topology.SCALE_UP, ArchType.ANGI, 'S4D')

    def test_legacy_on_rhel10_raises(self):
        with pytest.raises(ValueError, match="RHEL 10"):
            get_expected_config(10, Topology.SCALE_UP, ArchType.LEGACY, 'S4D')
