#!/bin/bash
#
# SAP Cluster Discovery Tool - Setup Script
#
# Dieses Skript richtet ein neues Discovery-Verzeichnis ein.
#
# Verwendung:
#   curl -sL <URL>/setup.sh | bash -s /pfad/zum/ziel
#   oder
#   ./setup.sh /pfad/zum/ziel
#

set -e

TARGET_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo " SAP Cluster Discovery Tool - Setup"
echo "=============================================="

# Prüfe Abhängigkeiten
check_dependencies() {
    echo ""
    echo "Prüfe Abhängigkeiten..."

    local missing=0

    # Python3
    if command -v python3 &> /dev/null; then
        echo "  [OK] python3: $(python3 --version 2>&1)"
    else
        echo "  [FEHLT] python3"
        missing=1
    fi

    # PyYAML
    if python3 -c "import yaml" 2>/dev/null; then
        echo "  [OK] python3-yaml"
    else
        echo "  [FEHLT] python3-yaml (PyYAML)"
        missing=1
    fi

    # SSH
    if command -v ssh &> /dev/null; then
        echo "  [OK] ssh"
    else
        echo "  [FEHLT] ssh"
        missing=1
    fi

    if [ $missing -eq 1 ]; then
        echo ""
        echo "Fehlende Pakete installieren:"
        echo ""
        echo "  RHEL 8/9/10:"
        echo "    sudo dnf install python3 python3-pyyaml openssh-clients"
        echo ""
        return 1
    fi

    echo ""
    echo "[OK] Alle Abhängigkeiten erfüllt"
    return 0
}

# Hauptlogik
main() {
    if [ "$TARGET_DIR" != "." ]; then
        echo "Zielverzeichnis: $TARGET_DIR"
        mkdir -p "$TARGET_DIR"
    fi

    check_dependencies || exit 1

    echo ""
    echo "Verzeichnisstruktur:"
    echo "  $TARGET_DIR/"
    echo "  ├── discovery_runner.py    # Hauptskript"
    echo "  ├── discover_access.py     # Access-Discovery Modul"
    echo "  ├── run_discovery.sh       # Wrapper-Script"
    echo "  ├── hosts.txt              # Hosts-Liste (anpassen!)"
    echo "  └── discovery_rules/       # YAML-Regeldateien"
    echo ""
    echo "Nächste Schritte:"
    echo "  1. cd $TARGET_DIR"
    echo "  2. hosts.txt anpassen (Ziel-Hosts eintragen)"
    echo "  3. ./run_discovery.sh --list-rules"
    echo "  4. ./run_discovery.sh"
    echo ""
}

main "$@"
