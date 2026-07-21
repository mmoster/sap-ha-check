"""Tests for access data models (NodeAccess, AccessConfig)."""

from dataclasses import asdict

from tool.sap_cluster_checks.access.models import NodeAccess, AccessConfig


class TestNodeAccess:
    def test_defaults(self):
        node = NodeAccess()
        assert node.hostname is None
        assert node.ssh_reachable is False
        assert node.ssh_user is None
        assert node.ansible_reachable is False
        assert node.ansible_host is None
        assert node.ansible_user is None
        assert node.sosreport_path is None
        assert node.preferred_method is None
        assert node.last_checked is None
        assert node.machine_id is None

    def test_keyword_construction(self):
        node = NodeAccess(
            hostname="node1",
            ssh_reachable=True,
            ssh_user="root",
            ansible_reachable=True,
            ansible_host="node1.example.com",
            ansible_user="admin",
            sosreport_path="/tmp/sos/node1",
            preferred_method="ssh",
            last_checked="2025-01-01",
            machine_id="abc123",
        )
        assert node.hostname == "node1"
        assert node.ssh_reachable is True
        assert node.ssh_user == "root"
        assert node.ansible_reachable is True
        assert node.ansible_host == "node1.example.com"
        assert node.ansible_user == "admin"
        assert node.sosreport_path == "/tmp/sos/node1"
        assert node.preferred_method == "ssh"
        assert node.last_checked == "2025-01-01"
        assert node.machine_id == "abc123"

    def test_partial_keyword_construction(self):
        node = NodeAccess(hostname="node2", ssh_reachable=True, preferred_method="ssh")
        assert node.hostname == "node2"
        assert node.ssh_reachable is True
        assert node.preferred_method == "ssh"
        assert node.ansible_reachable is False
        assert node.sosreport_path is None

    def test_asdict_compatibility(self):
        node = NodeAccess(hostname="node1", ssh_reachable=True)
        d = asdict(node)
        assert isinstance(d, dict)
        assert d["hostname"] == "node1"
        assert d["ssh_reachable"] is True


class TestAccessConfig:
    def test_post_init_defaults(self):
        config = AccessConfig()
        assert config.nodes == {}
        assert config.clusters == {}
        assert config.ansible_inventory_source is None
        assert config.ansible_inventory_path is None
        assert config.sosreport_directory is None
        assert config.hosts_file is None
        assert config.discovery_timestamp is None
        assert config.discovery_complete is False

    def test_with_pre_populated_nodes(self):
        nodes = {"node1": {"hostname": "node1"}, "node2": {"hostname": "node2"}}
        config = AccessConfig(nodes=nodes)
        assert len(config.nodes) == 2
        assert config.nodes["node1"]["hostname"] == "node1"
        assert config.nodes["node2"]["hostname"] == "node2"
