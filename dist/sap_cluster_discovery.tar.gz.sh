#!/bin/bash
#
# SAP Cluster Discovery Tool - Self-extracting Installer
#
# Verwendung:
#   ./sap_cluster_discovery.tar.gz.sh [ZIELVERZEICHNIS]
#
# Beispiel:
#   ./sap_cluster_discovery.tar.gz.sh ~/cluster_check
#   ./sap_cluster_discovery.tar.gz.sh /tmp/hana_discovery
#

set -e

TARGET_DIR="${1:-./sap_cluster_discovery}"

echo "=============================================="
echo " SAP Cluster Discovery Tool - Installation"
echo "=============================================="
echo ""
echo "Zielverzeichnis: $TARGET_DIR"
echo ""

# Verzeichnis erstellen
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

# Prüfe Python3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 nicht gefunden!"
    echo "Installation:"
    echo "  RHEL/CentOS: dnf install python3 python3-pyyaml"
    echo "  SUSE:        zypper install python3 python3-PyYAML"
    echo "  Ubuntu:      apt install python3 python3-yaml"
    exit 1
fi

# Prüfe PyYAML
if ! python3 -c "import yaml" 2>/dev/null; then
    echo "[WARNING] PyYAML nicht gefunden, versuche Installation..."
    if command -v dnf &> /dev/null; then
        sudo dnf install -y python3-pyyaml || pip3 install --user pyyaml
    elif command -v zypper &> /dev/null; then
        sudo zypper install -y python3-PyYAML || pip3 install --user pyyaml
    elif command -v apt &> /dev/null; then
        sudo apt install -y python3-yaml || pip3 install --user pyyaml
    else
        pip3 install --user pyyaml
    fi
fi

echo "[OK] Abhängigkeiten geprüft"
echo ""
echo "Extrahiere Dateien..."

# ===== EMBEDDED FILES START =====
