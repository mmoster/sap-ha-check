"""Tests for the collector (output parser)."""

from pathlib import Path

from hadr_provider.collector import parse_collected_output, _parse_ini_sections


FIXTURES = Path(__file__).parent / 'fixtures'


def _build_raw(global_ini='', sudoers='', provider_files='',
               packages='', rhel=''):
    """Build a combined command output from individual sections."""
    parts = []
    parts.append('=== GLOBAL_INI ===')
    parts.append(global_ini)
    parts.append('=== SUDOERS ===')
    parts.append(sudoers)
    parts.append('=== PROVIDER_FILES ===')
    parts.append(provider_files)
    parts.append('=== PACKAGES ===')
    parts.append(packages)
    parts.append('=== RHEL ===')
    parts.append(rhel)
    return '\n'.join(parts)


class TestParseIniSections:
    def test_parses_hadr_sections(self):
        text = (FIXTURES / 'global_ini_angi_ok.txt').read_text()
        sections = _parse_ini_sections(text)
        assert 'ha_dr_provider_hanasr' in sections
        assert sections['ha_dr_provider_hanasr']['provider'] == 'HanaSR'

    def test_parses_trace(self):
        text = (FIXTURES / 'global_ini_angi_ok.txt').read_text()
        sections = _parse_ini_sections(text)
        assert 'trace' in sections
        assert sections['trace']['ha_dr_hanasr'] == 'info'

    def test_ignores_non_hadr_sections(self):
        text = (FIXTURES / 'global_ini_missing.txt').read_text()
        sections = _parse_ini_sections(text)
        # persistence and system_replication should be filtered out
        assert 'persistence' not in sections
        assert 'system_replication' not in sections

    def test_legacy_sections(self):
        text = (FIXTURES / 'global_ini_legacy_ok.txt').read_text()
        sections = _parse_ini_sections(text)
        assert 'ha_dr_provider_SAPHanaSR' in sections
        assert sections['ha_dr_provider_SAPHanaSR']['provider'] == 'SAPHanaSR'
        assert sections['ha_dr_provider_SAPHanaSR']['path'] == '/usr/share/SAPHanaSR'


class TestParseCollectedOutput:
    def test_angi_complete(self):
        global_ini = (FIXTURES / 'global_ini_angi_ok.txt').read_text()
        sudoers = (FIXTURES / 'sudoers_angi.txt').read_text()
        raw = _build_raw(
            global_ini=global_ini,
            sudoers=sudoers,
            provider_files='/usr/share/sap-hana-ha/HanaSR.py',
            packages='sap-hana-ha-1.0.0-1.el9',
            rhel='Red Hat Enterprise Linux release 9.4 (Plow)',
        )

        actual = parse_collected_output(raw, 'node1', 'S4D')
        assert actual.node == 'node1'
        assert actual.sid == 'S4D'
        assert actual.sidadm == 's4dadm'
        assert 'ha_dr_provider_hanasr' in actual.global_ini_sections
        assert actual.trace_settings.get('ha_dr_hanasr') == 'info'
        assert len(actual.sudoers_lines) >= 2
        assert '/usr/share/sap-hana-ha/HanaSR.py' in actual.provider_files_found
        assert 'sap-hana-ha-1.0.0-1.el9' in actual.installed_packages
        assert '9.4' in actual.rhel_version

    def test_missing_hooks(self):
        global_ini = (FIXTURES / 'global_ini_missing.txt').read_text()
        raw = _build_raw(global_ini=global_ini)

        actual = parse_collected_output(raw, 'node1', 'S4D')
        # No ha_dr_provider sections should be found
        hadr_sections = {k: v for k, v in actual.global_ini_sections.items()
                         if k.startswith('ha_dr_provider')}
        assert len(hadr_sections) == 0

    def test_provider_files_ls_errors(self):
        raw = _build_raw(
            provider_files=(
                "ls: cannot access '/usr/share/sap-hana-ha/HanaSR.py': "
                "No such file or directory\n"
                "/usr/share/SAPHanaSR/SAPHanaSR.py"
            ),
        )
        actual = parse_collected_output(raw, 'node1', 'S4D')
        assert '/usr/share/SAPHanaSR/SAPHanaSR.py' in actual.provider_files_found
        assert '/usr/share/sap-hana-ha/HanaSR.py' not in actual.provider_files_found

    def test_packages_filters_not_installed(self):
        raw = _build_raw(
            packages=(
                "sap-hana-ha-1.0.0-1.el9\n"
                "package resource-agents-sap-hana is not installed\n"
                "package resource-agents-sap-hana-scaleout is not installed"
            ),
        )
        actual = parse_collected_output(raw, 'node1', 'S4D')
        assert len(actual.installed_packages) == 1
        assert actual.installed_packages[0] == 'sap-hana-ha-1.0.0-1.el9'

    def test_empty_output(self):
        actual = parse_collected_output('', 'node1', 'S4D')
        assert actual.node == 'node1'
        assert len(actual.global_ini_sections) == 0
        assert len(actual.sudoers_lines) == 0
