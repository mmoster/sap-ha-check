"""Tests for RulesEngine._parse_output()."""

from sap_ha_check.rules.engine import RulesEngine


def _parse(output, parser_config):
    """Helper: call _parse_output on a fresh engine."""
    engine = RulesEngine()
    return engine._parse_output(output, parser_config)


class TestNonRegexType:
    def test_returns_raw_for_non_regex(self):
        result = _parse("hello world", {"type": "text"})
        assert result == {"raw": "hello world"}

    def test_returns_raw_when_type_missing(self):
        result = _parse("hello world", {})
        assert result == {"raw": "hello world"}


class TestRegexPatterns:
    def test_named_group_extraction(self):
        output = "version: 1.2.3"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "version", "regex": r"version:\s+(\S+)", "group": 1},
            ],
        }
        result = _parse(output, config)
        assert result["version"] == "1.2.3"

    def test_group_zero_full_match(self):
        output = "status: active"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "status_line", "regex": r"status:\s+\w+", "group": 0},
            ],
        }
        result = _parse(output, config)
        assert result["status_line"] == "status: active"

    def test_no_match_returns_none(self):
        output = "no version here"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "version", "regex": r"version:\s+(\S+)", "group": 1},
            ],
        }
        result = _parse(output, config)
        assert result["version"] is None

    def test_multiple_patterns(self):
        output = "name: test\nversion: 2.0\nstatus: ok"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "name", "regex": r"name:\s+(\S+)", "group": 1},
                {"name": "version", "regex": r"version:\s+(\S+)", "group": 1},
                {"name": "status", "regex": r"status:\s+(\S+)", "group": 1},
            ],
        }
        result = _parse(output, config)
        assert result["name"] == "test"
        assert result["version"] == "2.0"
        assert result["status"] == "ok"

    def test_invalid_regex_stores_error(self):
        output = "test"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "bad", "regex": r"[invalid", "group": 0},
            ],
        }
        result = _parse(output, config)
        assert result["bad"] is None
        assert "bad_error" in result

    def test_multiline_flag(self):
        output = "line1\nversion: 3.0\nline3"
        config = {
            "type": "regex",
            "multiline": True,
            "search_patterns": [
                {"name": "version", "regex": r"^version:\s+(\S+)", "group": 1},
            ],
        }
        result = _parse(output, config)
        assert result["version"] == "3.0"

    def test_missing_name_skipped(self):
        output = "test"
        config = {
            "type": "regex",
            "search_patterns": [
                {"regex": r"test", "group": 0},
            ],
        }
        result = _parse(output, config)
        assert len(result) == 0

    def test_missing_regex_skipped(self):
        output = "test"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "test", "group": 0},
            ],
        }
        result = _parse(output, config)
        assert len(result) == 0

    def test_group_exceeds_captures_returns_none(self):
        output = "hello"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "val", "regex": r"(hello)", "group": 5},
            ],
        }
        result = _parse(output, config)
        assert result["val"] is None

    def test_empty_output(self):
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "version", "regex": r"version:\s+(\S+)", "group": 1},
            ],
        }
        result = _parse("", config)
        assert result["version"] is None

    def test_empty_search_patterns(self):
        result = _parse("hello", {"type": "regex", "search_patterns": []})
        assert result == {}

    def test_default_group_zero(self):
        output = "status: active"
        config = {
            "type": "regex",
            "search_patterns": [
                {"name": "status_line", "regex": r"status:\s+\w+"},
            ],
        }
        result = _parse(output, config)
        assert result["status_line"] == "status: active"
