#!/usr/bin/env python3
"""
Inject health check training content into the Red Hat template.
Uses the unpacked template structure, duplicating slide7 for content slides.
"""
import os
import sys
import re
import shutil
import subprocess

SCRIPTS_DIR = os.path.expanduser(
    "~/.claude/plugins/cache/anthropic-agent-skills/document-skills/98669c11ca63/skills/pptx/scripts"
)
TEMPLATE_PPTX = os.path.expanduser("~/Downloads/SAP HA Health Check.pptx")
OUTPUT_PPTX = os.path.expanduser(
    "~/projects/SAP_cluster_health_check/docs/SAP_Cluster_Health_Check_Training.pptx"
)
WORK_DIR = "/tmp/rh_template_work"

# ─── Training Content ───
# Each slide: (title, subtitle, body_items)
# body_items is a list of (level, text) tuples. level 0 = ●, level 1 = ○

TITLE_SLIDE_TITLE = "SAP HANA Cluster Health Check"
TITLE_SLIDE_SUBTITLE = "Introduction & Training"

AGENDA_ITEMS = [
    "What Is It? / Architecture Overview",
    "Installation, Prerequisites & First Run",
    "Core Use Cases (8 scenarios)",
    "Understanding Results & Severities",
    "Health Check Reference (22 checks)",
    "Practical Examples & Troubleshooting",
    "Useful Options & Next Steps",
]

CONTENT_SLIDES = [
    # ─── Section 1: Introduction ───
    (
        "SAP HANA Cluster Health Check",
        "What Is It?",
        [
            (0, "Comprehensive, automated health check tool for SAP HANA Pacemaker clusters on RHEL 8/9/10"),
            (0, "Key Features:"),
            (1, "22 automated checks covering cluster config, Pacemaker/Corosync, and SAP-specific validations"),
            (1, "Works with live clusters (via SSH), local execution, or offline analysis (via SOSreports)"),
            (1, "Auto-discovers all cluster nodes from a single seed node"),
            (1, "Auto-generated PDF reports with standard or verbose detail"),
            (1, "Multithreaded execution for parallel node checks"),
            (1, "Version detection for RHEL and Pacemaker"),
            (1, "HANA status detection: SID, instance, sidadm user, running processes"),
        ],
    ),
    (
        "SAP HANA Cluster Health Check",
        "Architecture Overview - 5-Step Pipeline",
        [
            (0, "Step 1 - Access Discovery: Discovers SSH, Ansible, or SOSreport access to cluster nodes"),
            (0, "Step 2 - Cluster Configuration: Node status, quorum, clone config, package consistency (9 checks)"),
            (0, "Step 3 - Pacemaker/Corosync: STONITH, resources, fencing, master/slave roles (6 checks)"),
            (0, "Step 4 - SAP-Specific: HANA SR status, replication mode, HA/DR hooks, systemd (7 checks)"),
            (0, "Step 5 - Report Generation: Summary YAML and PDF reports"),
        ],
    ),
    # ─── Section 2: Getting Started ───
    (
        "Getting Started",
        "Installation",
        [
            (0, "Option 1: Using git (recommended)"),
            (1, "git clone https://github.com/mmoster/sap-ha-check.git"),
            (1, "cd sap-ha-check"),
            (1, "./cluster_health_check.py --local"),
            (0, "Option 2: Download without git"),
            (1, "curl -L https://github.com/mmoster/sap-ha-check/archive/refs/heads/main.tar.gz | tar xz"),
            (1, "cd sap-ha-check-main"),
            (0, "Prerequisites:"),
            (1, "Python 3.6+ (included in RHEL 8/9/10)"),
            (1, "PyYAML: pip install pyyaml (or dnf install python3-pyyaml)"),
            (1, "fpdf2 (optional, for PDF reports): pip install fpdf2"),
            (1, "SSH key-based access for remote checks"),
        ],
    ),
    (
        "Getting Started",
        "First Run",
        [
            (0, "Run locally on a cluster node: ./cluster_health_check.py --local"),
            (0, "What happens on first run:"),
            (1, "1. Discovers cluster nodes from Pacemaker configuration"),
            (1, "2. Checks connectivity to all discovered nodes"),
            (1, "3. Collects configuration data from all nodes"),
            (1, "4. Runs all 22 health checks in parallel"),
            (1, "5. Generates summary + PDF report"),
            (1, "6. Caches topology config for faster subsequent runs"),
            (0, "Example output:"),
            (1, "PASSED: 22  FAILED: 0  SKIPPED: 0  ERROR: 0"),
            (1, "CLUSTER IS HEALTHY"),
            (1, "PDF report saved: health_check_report_mycluster_1507.pdf"),
        ],
    ),
    # ─── Section 3: Use Cases ───
    (
        "Core Use Cases",
        "Use Case 1: Routine Health Check",
        [
            (0, "Run on a live cluster node for a quick validation"),
            (0, "Command: ./cluster_health_check.py --local"),
            (0, "When to use:"),
            (1, "Daily or weekly operational health checks"),
            (1, "After routine maintenance windows"),
            (1, "Quick sanity check before making changes"),
            (0, "What you get:"),
            (1, "Pass/fail summary for all 22 checks"),
            (1, "CRITICAL / WARNING / INFO severity breakdown"),
            (1, "Health status banner (CLUSTER IS HEALTHY / HAS ISSUES)"),
            (1, "Auto-saved PDF report"),
            (0, "Tip: First run caches cluster topology. Subsequent runs are faster."),
        ],
    ),
    (
        "Core Use Cases",
        "Use Case 2: Remote Cluster Check",
        [
            (0, "Check clusters remotely via SSH - auto-discovers all members"),
            (0, "Option A - Specify nodes directly:"),
            (1, "./cluster_health_check.py hana01 hana02"),
            (0, "Option B - Use a hosts file:"),
            (1, "./cluster_health_check.py -H hosts.txt"),
            (0, "Key behaviors:"),
            (1, "Auto-discovers all cluster nodes from any seed node"),
            (1, "Only one node needed - others found via Pacemaker config"),
            (1, "Uses SSH key-based authentication"),
            (1, "Parallel connectivity checks for speed"),
            (1, "Multi-cluster: prompts for selection if multiple clusters found"),
        ],
    ),
    (
        "Core Use Cases",
        "Use Case 3: Offline SOSreport Analysis",
        [
            (0, "Analyze SOSreports without SSH access - ideal for support & post-mortem"),
            (0, "Command: ./cluster_health_check.py -s /path/to/sosreports/"),
            (0, "When to use:"),
            (1, "Support case analysis"),
            (1, "Post-mortem investigations"),
            (1, "No SSH access available to the cluster"),
            (1, "Historical analysis of saved reports"),
            (0, "Supported formats:"),
            (1, ".tar.xz archives (standard SOSreport format)"),
            (1, ".tar.gz archives"),
            (1, "Pre-extracted SOSreport directories"),
            (0, "Tool auto-extracts archives and maps data to the same checks as live analysis."),
        ],
    ),
    (
        "Core Use Cases",
        "Use Case 4: SOSreport Collection Workflow",
        [
            (0, "End-to-end: discover cluster, configure extensions, create & fetch SOSreports"),
            (0, "Full workflow: ./cluster_health_check.py -R hana01"),
            (0, "Auto-configure: ./cluster_health_check.py -R hana01 --configure-extensions"),
            (0, "Workflow steps:"),
            (1, "1. Discovers cluster name and all nodes from the seed node"),
            (1, "2. Checks SSH access to all nodes (skips unreachable ones)"),
            (1, "3. Checks and optionally configures SAP SOSreport extensions"),
            (1, "4. Creates SOSreports in parallel with cluster name as label"),
            (1, "5. Fetches SOSreports via SCP to local ./sosreports/ directory"),
            (0, "SAP Extensions add: SAPHanaSR-showAttr output, cluster state snapshots, resource configs"),
        ],
    ),
    (
        "Core Use Cases",
        "Use Case 5: Pre-Maintenance Validation",
        [
            (0, "Run before and after maintenance windows to verify cluster state"),
            (0, "Before Maintenance:"),
            (1, "./cluster_health_check.py --local -v"),
            (1, "Establishes baseline state with verbose PDF"),
            (1, "Save as pre-maintenance reference"),
            (1, "Identify any pre-existing issues"),
            (0, "After Maintenance:"),
            (1, "./cluster_health_check.py --local -v"),
            (1, "Verify cluster recovered correctly"),
            (1, "Compare with pre-maintenance report"),
            (1, "Detect any regressions introduced"),
            (1, "Document maintenance outcome"),
        ],
    ),
    (
        "Core Use Cases",
        "Use Case 6: Audit & Compliance",
        [
            (0, "Generate detailed PDF reports for compliance documentation"),
            (0, "Command: ./cluster_health_check.py --local -v"),
            (0, "Verbose PDF includes:"),
            (1, "All 22 checks with full details (not just failures)"),
            (1, "Complete cluster topology and configuration"),
            (1, "Node status and IP addresses"),
            (1, "System replication details"),
            (1, "STONITH/fencing configuration"),
            (1, "Package versions across all nodes"),
            (0, "Use for: internal audits, external auditor documentation, management reporting, change management evidence"),
        ],
    ),
    (
        "Core Use Cases",
        "Use Case 7: Multi-Cluster Management",
        [
            (0, "Show all discovered clusters: ./cluster_health_check.py -S"),
            (0, "Filter by node: ./cluster_health_check.py -S hana01"),
            (0, "Key features:"),
            (1, "View all discovered cluster configurations"),
            (1, "Filter by cluster name or node hostname"),
            (1, "Prompts for selection when multiple clusters are found"),
            (1, "Use -D to reset and re-discover all clusters"),
            (0, "Use Case 8: Interactive / Exploratory Mode"),
            (0, "Command: ./cluster_health_check.py -u"),
            (1, "Scans current directory for SOSreport archives, hosts files, previous results"),
            (1, "Presents an interactive menu to choose what to analyze"),
            (1, "Great for guided setup when unsure where SOSreports are stored"),
        ],
    ),
    # ─── Section 4: Understanding Results ───
    (
        "Understanding Results",
        "Reading the Output",
        [
            (0, "Healthy cluster output:"),
            (1, "PASSED: 22  FAILED: 0  SKIPPED: 0  ERROR: 0"),
            (1, "CLUSTER IS HEALTHY"),
            (0, "Issues detected:"),
            (1, "PASSED: 20  FAILED: 2  SKIPPED: 0  ERROR: 0"),
            (1, "FAILED: CHK_STONITH_CONFIG - STONITH is disabled"),
            (0, "Result statuses:"),
            (1, "PASSED - Check completed successfully"),
            (1, "FAILED - Issue detected, action needed"),
            (1, "SKIPPED - Not applicable to this configuration"),
            (1, "ERROR - Check could not complete (missing data or access issue)"),
        ],
    ),
    (
        "Understanding Results",
        "Check Severities",
        [
            (0, "CRITICAL - Immediate action required"),
            (1, "Issues that affect cluster availability or data integrity"),
            (1, "Examples: STONITH disabled, node offline, quorum lost, SR status incorrect"),
            (0, "WARNING - Should be addressed"),
            (1, "Best practice violations or potential issues"),
            (1, "Examples: Package mismatch, cluster not fully started, resource failures"),
            (0, "INFO - Informational"),
            (1, "Context about cluster topology and configuration"),
            (1, "Examples: Cluster type detection (Scale-Up/Scale-Out), HANA installation status"),
        ],
    ),
    # ─── Section 5: Check Reference ───
    (
        "Health Check Reference",
        "Cluster Configuration Checks (9)",
        [
            (0, "CHK_CLUSTER_READY [WARNING] - Check if cluster is fully started (not in transition)"),
            (0, "CHK_CLUSTER_TYPE [INFO] - Detect Scale-Up vs Scale-Out configuration"),
            (0, "CHK_NODE_STATUS [CRITICAL] - Verify all cluster nodes are online"),
            (0, "CHK_CLUSTER_QUORUM [CRITICAL] - Verify cluster has quorum"),
            (0, "CHK_QUORUM_CONFIG [CRITICAL] - Validate quorum configuration (Scale-Up only)"),
            (0, "CHK_CLONE_CONFIG [CRITICAL] - Validate clone resource configuration"),
            (0, "CHK_SETUP_VALIDATION [CRITICAL] - Validate against SAP HANA HA best practices"),
            (0, "CHK_CIB_TIME_SYNC [WARNING] - Verify CIB updates are synchronized"),
            (0, "CHK_PACKAGE_CONSISTENCY [WARNING] - Verify package versions match across nodes"),
        ],
    ),
    (
        "Health Check Reference",
        "Pacemaker/Corosync (6) & SAP-Specific (7) Checks",
        [
            (0, "Pacemaker/Corosync Checks:"),
            (1, "CHK_STONITH_CONFIG [CRITICAL] - Verify STONITH/fencing is enabled"),
            (1, "CHK_RESOURCE_STATUS [CRITICAL] - Verify SAP HANA resources are running"),
            (1, "CHK_RESOURCE_FAILURES [WARNING] - Detect failed resource operations"),
            (1, "CHK_ALERT_FENCING [WARNING] - Validate SAPHanaSR-alert-fencing"),
            (1, "CHK_MASTER_SLAVE_ROLES [CRITICAL] - Verify master/slave role consistency"),
            (1, "CHK_MAJORITY_MAKER [CRITICAL] - Validate majority maker constraints (Scale-Out)"),
            (0, "SAP-Specific Checks:"),
            (1, "CHK_HANA_INSTALLED [INFO] - Detect HANA installation, SID, instance, sidadm"),
            (1, "CHK_HANA_SR_STATUS [CRITICAL] - Verify HANA System Replication status"),
            (1, "CHK_REPLICATION_MODE [WARNING] - Verify replication mode is sync or syncmem"),
            (1, "CHK_HADR_HOOKS [CRITICAL] - Validate HA/DR provider hooks"),
            (1, "CHK_HANA_AUTOSTART [WARNING] - Validate HANA autostart is disabled"),
            (1, "CHK_SYSTEMD_SAP [WARNING] - Validate SAP Host Agent and systemd config"),
            (1, "CHK_SITE_ROLES [CRITICAL] - Verify site roles consistency"),
        ],
    ),
    (
        "Understanding Results",
        "PDF Reports",
        [
            (0, "Standard Report: ./cluster_health_check.py --local"),
            (1, "Shows failed checks with details"),
            (1, "Summary pass/fail counts"),
            (1, "Compact and focused on issues"),
            (0, "Verbose Report: ./cluster_health_check.py --local -v"),
            (1, "Shows ALL checks with full details (not just failures)"),
            (1, "Includes complete cluster configuration"),
            (1, "Ideal for audits, compliance, and documentation"),
            (0, "What's included in every PDF:"),
            (1, "Cluster name and timestamp"),
            (1, "Node list with status"),
            (1, "Check results table with pass/fail"),
            (1, "Health status banner"),
            (1, "RHEL and Pacemaker version information"),
        ],
    ),
    # ─── Section 6: Practical Examples ───
    (
        "Practical Examples",
        "Example: Healthy Cluster Output",
        [
            (0, "Command: ./cluster_health_check.py --local"),
            (0, "Output:"),
            (1, "Discovering cluster from local node..."),
            (1, "Found cluster: production_hana (hana01, hana02)"),
            (1, "RHEL 9.4 | Pacemaker 2.1.7 | ANGI (sap-hana-ha)"),
            (1, "Step 2: Cluster Configuration Check    [9/9 passed]"),
            (1, "Step 3: Pacemaker/Corosync Check       [6/6 passed]"),
            (1, "Step 4: SAP-Specific Checks            [7/7 passed]"),
            (0, "Result:"),
            (1, "PASSED: 22  FAILED: 0  SKIPPED: 0  ERROR: 0"),
            (1, "CLUSTER IS HEALTHY"),
            (1, "PDF report saved: health_check_report_production_hana_1507.pdf"),
        ],
    ),
    (
        "Practical Examples",
        "Example: Failed Check (STONITH Disabled)",
        [
            (0, "Output when issues are detected:"),
            (1, "PASSED: 20  FAILED: 2  SKIPPED: 0  ERROR: 0"),
            (1, "FAILED: CHK_STONITH_CONFIG [CRITICAL] - STONITH is disabled"),
            (1, "FAILED: CHK_RESOURCE_FAILURES [WARNING] - 2 failed resource actions on hana01"),
            (1, "CLUSTER HAS ISSUES - REVIEW FAILED CHECKS"),
            (0, "Fix STONITH:"),
            (1, "1. Enable STONITH in cluster properties"),
            (1, "2. Configure fencing device"),
            (1, "3. Test with: pcs stonith fence <node>"),
            (0, "Fix Resource Failures:"),
            (1, "1. Check pcs status for details"),
            (1, "2. Review /var/log/pacemaker.log"),
            (1, "3. Clear failures: pcs resource cleanup"),
            (0, "Re-run health check to verify fixes."),
        ],
    ),
    (
        "Practical Examples",
        "Example: Scale-Out Cluster & Cluster Not Running",
        [
            (0, "Scale-Out Clusters:"),
            (1, "4+ HANA nodes + 1 majority maker node"),
            (1, "Uses SAPHanaController resource agent (vs SAPHana for Scale-Up)"),
            (1, "CHK_MAJORITY_MAKER runs only on Scale-Out topology"),
            (1, "CHK_QUORUM_CONFIG runs only on Scale-Up topology"),
            (1, "Topology detected automatically via resource agent"),
            (0, "Cluster Not Running:"),
            (1, "Tool detects Pacemaker/Corosync is not running"),
            (1, "Falls back to corosync.conf for node discovery"),
            (1, "Checks requiring a running cluster are SKIPPED (not FAILED)"),
            (1, "Still runs all checks that work with static configuration"),
            (1, "Useful during planned downtime or startup troubleshooting"),
        ],
    ),
    # ─── Section 7: Tips & Advanced ───
    (
        "Tips & Advanced",
        "Useful Options Quick Reference",
        [
            (0, "--local : Run on current cluster node"),
            (0, "-s DIR : Analyze SOSreports in directory"),
            (0, "-H FILE : Read hosts from file"),
            (0, "-u : Interactive mode - scan for resources"),
            (0, "-v : Verbose PDF (all checks, full detail)"),
            (0, "-d : Debug mode (verbose console output)"),
            (0, "-L : List all available health checks"),
            (0, "-S [NAME] : Show discovered cluster config"),
            (0, "-D : Delete cached config, start fresh"),
            (0, "-f : Force rediscovery (ignore cache)"),
            (0, "-R NODE : Full SOSreport collection workflow"),
            (0, "-F [CLUSTER] : Fetch existing SOSreports from nodes"),
            (0, "--no-pdf : Skip PDF report generation"),
        ],
    ),
    (
        "Tips & Advanced",
        "Troubleshooting",
        [
            (0, "SSH connection fails:"),
            (1, "Verify key-based SSH access: ssh -o BatchMode=yes <node> hostname"),
            (0, "PyYAML not found:"),
            (1, "Install: pip install pyyaml  or  dnf install python3-pyyaml"),
            (0, "No PDF generated:"),
            (1, "Install fpdf2: pip install fpdf2 (optional dependency)"),
            (0, "Cluster not detected:"),
            (1, "Pacemaker may not be running. Tool falls back to corosync.conf automatically"),
            (0, "Stale cached config:"),
            (1, "Use -D to delete cache and -f to force rediscovery"),
            (0, "Wrong cluster selected:"),
            (1, "Use --cluster NAME or -D to reset, then re-run"),
            (0, "Tip: Use -d (debug mode) for verbose console output to diagnose issues."),
        ],
    ),
    (
        "Next Steps & Resources",
        "",
        [
            (0, "Full Documentation:"),
            (1, "README.md - Complete reference guide"),
            (1, "github.com/mmoster/sap-ha-check"),
            (0, "Extend the Tool:"),
            (1, "EXTENDING_HEALTH_CHECKS.md - Create custom health check rules"),
            (1, "check_dispatch.yaml - Topology-aware check dispatch manifest"),
            (0, "Quick Start Guide:"),
            (1, "BLOG_HOWTO.md - Step-by-step examples and walkthroughs"),
            (0, "Get started now:"),
            (1, "git clone https://github.com/mmoster/sap-ha-check.git"),
            (1, "cd sap-ha-check && ./cluster_health_check.py --local"),
        ],
    ),
]


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def xml_escape(text):
    """Escape text for XML content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def make_bullet_xml(level, text, is_bold=False):
    """Generate XML string for a bullet paragraph matching the template style."""
    marL = "457200" if level == 0 else "914400"
    char = "&#x25CF;" if level == 0 else "&#x25CB;"
    bold_attr = ' b="1"' if is_bold else ""
    escaped = xml_escape(text)

    return f"""<a:p>
<a:pPr indent="-295275" lvl="{level}" marL="{marL}" rtl="0" algn="l">
<a:lnSpc><a:spcPct val="150000"/></a:lnSpc>
<a:spcBef><a:spcPts val="0"/></a:spcBef>
<a:spcAft><a:spcPts val="0"/></a:spcAft>
<a:buClr><a:srgbClr val="3C3C3C"/></a:buClr>
<a:buSzPts val="1050"/>
<a:buChar char="{char}"/>
</a:pPr>
<a:r>
<a:rPr{bold_attr} lang="en" sz="1050"><a:solidFill><a:srgbClr val="3C3C3C"/></a:solidFill></a:rPr>
<a:t>{escaped}</a:t>
</a:r>
</a:p>"""


def make_title_xml(title, subtitle=""):
    """Generate the title text box XML paragraphs."""
    t_escaped = xml_escape(title)
    xml = f"""<a:p>
<a:pPr indent="0" lvl="0" marL="0" rtl="0" algn="l">
<a:spcBef><a:spcPts val="0"/></a:spcBef>
<a:spcAft><a:spcPts val="0"/></a:spcAft>
<a:buNone/>
</a:pPr>
<a:r>
<a:rPr b="1" lang="en" sz="3500">
<a:solidFill><a:srgbClr val="EE0000"/></a:solidFill>
<a:latin typeface="Red Hat Display"/><a:ea typeface="Red Hat Display"/><a:cs typeface="Red Hat Display"/><a:sym typeface="Red Hat Display"/>
</a:rPr>
<a:t>{t_escaped}</a:t>
</a:r>
</a:p>"""

    if subtitle:
        s_escaped = xml_escape(subtitle)
        xml += f"""
<a:p>
<a:pPr indent="0" lvl="0" marL="0" rtl="0" algn="l">
<a:spcBef><a:spcPts val="0"/></a:spcBef>
<a:spcAft><a:spcPts val="0"/></a:spcAft>
<a:buNone/>
</a:pPr>
<a:r>
<a:rPr lang="en" sz="2200">
<a:solidFill><a:srgbClr val="EE0000"/></a:solidFill>
<a:latin typeface="Red Hat Display"/><a:ea typeface="Red Hat Display"/><a:cs typeface="Red Hat Display"/><a:sym typeface="Red Hat Display"/>
</a:rPr>
<a:t>{s_escaped}</a:t>
</a:r>
</a:p>"""

    return xml


def make_agenda_bullet_xml(text):
    """Generate XML string for an agenda bullet paragraph (22pt, Red Hat Text)."""
    escaped = xml_escape(text)
    return (
        '<a:p>'
        '<a:pPr indent="-368300" lvl="0" marL="457200" rtl="0" algn="l">'
        '<a:lnSpc><a:spcPct val="100000"/></a:lnSpc>'
        '<a:spcBef><a:spcPts val="0"/></a:spcBef>'
        '<a:spcAft><a:spcPts val="0"/></a:spcAft>'
        '<a:buClr><a:schemeClr val="dk1"/></a:buClr>'
        '<a:buSzPts val="2200"/>'
        '<a:buFont typeface="Red Hat Text"/>'
        '<a:buChar char="&#x25CF;"/>'
        '</a:pPr>'
        '<a:r>'
        '<a:rPr lang="en" sz="2200">'
        '<a:solidFill><a:schemeClr val="dk1"/></a:solidFill>'
        '<a:latin typeface="Red Hat Text"/>'
        '<a:ea typeface="Red Hat Text"/>'
        '<a:cs typeface="Red Hat Text"/>'
        '<a:sym typeface="Red Hat Text"/>'
        '</a:rPr>'
        f'<a:t>{escaped}</a:t>'
        '</a:r>'
        '<a:endParaRPr sz="2200">'
        '<a:solidFill><a:schemeClr val="dk1"/></a:solidFill>'
        '<a:latin typeface="Red Hat Text"/>'
        '<a:ea typeface="Red Hat Text"/>'
        '<a:cs typeface="Red Hat Text"/>'
        '<a:sym typeface="Red Hat Text"/>'
        '</a:endParaRPr>'
        '</a:p>'
    )


def replace_agenda_body_in_xml(xml_str, items):
    """Replace the bullet content in the agenda slide (slide2).

    The agenda slide has a single title shape (anchor="t") containing both
    the title "Agenda" and the bullet items. We replace all <a:p> elements
    that contain <a:buChar> to swap the existing agenda for our new items,
    while preserving the Agenda title paragraph.
    """
    # Find individual <a:p>...</a:p> blocks using negative lookahead
    # to prevent crossing paragraph boundaries
    para_pattern = r'<a:p>(?:(?!</a:p>).)*</a:p>'

    bullet_indices = []
    for m in re.finditer(para_pattern, xml_str, re.DOTALL):
        if '<a:buChar' in m.group():
            bullet_indices.append((m.start(), m.end()))

    if not bullet_indices:
        print("  WARNING: No bullet paragraphs found in agenda slide")
        return xml_str

    start = bullet_indices[0][0]
    end = bullet_indices[-1][1]

    new_bullets = "\n".join(make_agenda_bullet_xml(item) for item in items)
    return xml_str[:start] + new_bullets + xml_str[end:]


def replace_title_in_xml(xml_str, title, subtitle):
    """Replace the title text box content in a slide XML string."""
    # The title shape starts at y~825350, has spAutoFit and two paragraphs with Red Hat Display font
    # We find the third <p:sp> block (title) by matching on "spAutoFit" and "Red Hat Display"
    # Strategy: find the <p:txBody> that contains "Red Hat Display" and "spAutoFit", replace its <a:p> elements
    pattern = r'(<p:txBody>\s*<a:bodyPr[^>]*>\s*<a:spAutoFit/>\s*</a:bodyPr>\s*<a:lstStyle/>\s*)((?:<a:p>.*?</a:p>\s*)+)(</p:txBody>)'
    new_content = make_title_xml(title, subtitle)
    result = re.sub(pattern, r"\1" + new_content + r"\n\3", xml_str, count=1, flags=re.DOTALL)
    return result


def replace_body_in_xml(xml_str, items):
    """Replace the body text box content in a slide XML string.

    The body shape is identified by lIns="91425" + anchor="ctr" + noAutofit,
    distinguishing it from the header bar (lIns="438900") and footer (lIns="0").
    """
    # Use lookaheads to match both anchor="ctr" and lIns="91425" regardless of attribute order
    pattern = r'(<p:txBody>\s*<a:bodyPr(?=[^>]*anchor="ctr")(?=[^>]*lIns="91425")[^>]*>\s*<a:noAutofit/>\s*</a:bodyPr>\s*<a:lstStyle/>\s*)((?:<a:p>.*?</a:p>\s*)+)(</p:txBody>)'

    bullet_xml = "\n".join(
        make_bullet_xml(level, text, is_bold=(level == 0 and text.endswith(":")))
        for level, text in items
    )

    result = re.sub(pattern, r"\1" + bullet_xml + r"\n\3", xml_str, count=1, flags=re.DOTALL)

    # Change body anchor from "ctr" (vertically centered) to "t" (top-aligned)
    # to eliminate the excessive gap between title and body content.
    # Target only the body shape's bodyPr (identified by lIns="91425").
    result = re.sub(
        r'(<a:bodyPr(?=[^>]*lIns="91425")[^>]*)anchor="ctr"',
        r'\1anchor="t"',
        result,
        count=1,
    )

    return result


def main():
    # Clean and prepare work directory
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)

    # Unpack template
    print("Unpacking template...")
    subprocess.run(
        ["python", f"{SCRIPTS_DIR}/office/unpack.py", TEMPLATE_PPTX, WORK_DIR],
        check=True,
    )

    # ─── Step 1: Modify title slide (slide1) ───
    print("Modifying title slide...")
    slide1_path = f"{WORK_DIR}/ppt/slides/slide1.xml"
    xml = read_file(slide1_path)
    xml = xml.replace("SAP HA Health Check", xml_escape(TITLE_SLIDE_TITLE))
    xml = xml.replace("SAP Alliance Technology Team", xml_escape(TITLE_SLIDE_SUBTITLE))
    write_file(slide1_path, xml)

    # ─── Step 2: Modify agenda slide (slide2) ───
    print("Modifying agenda slide...")
    slide2_path = f"{WORK_DIR}/ppt/slides/slide2.xml"
    xml = read_file(slide2_path)
    xml = replace_agenda_body_in_xml(xml, AGENDA_ITEMS)
    write_file(slide2_path, xml)

    # ─── Step 2b: Clean up slide26 (Thank You) leftover text ───
    slide26_path = f"{WORK_DIR}/ppt/slides/slide26.xml"
    if os.path.exists(slide26_path):
        xml = read_file(slide26_path)
        xml = xml.replace("GWS Germany New Hire Call", "")
        write_file(slide26_path, xml)

    # ─── Step 3: Duplicate slide7 for each content slide ───
    print(f"Creating {len(CONTENT_SLIDES)} content slides from template...")
    add_slide_script = f"{SCRIPTS_DIR}/add_slide.py"

    new_slide_ids = []
    for i, (title, subtitle, items) in enumerate(CONTENT_SLIDES):
        result = subprocess.run(
            ["python", add_slide_script, WORK_DIR, "slide7.xml"],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        lines = output.strip().split("\n")
        new_filename = None
        for line in lines:
            m = re.search(r"Created (slide\d+\.xml)", line)
            if m:
                new_filename = m.group(1)

        if not new_filename:
            print(f"  ERROR: Could not parse add_slide output: {output}")
            continue

        new_slide_ids.append(new_filename)

        # Edit the new slide's content using string-based XML manipulation
        new_path = f"{WORK_DIR}/ppt/slides/{new_filename}"
        xml = read_file(new_path)
        xml = replace_title_in_xml(xml, title, subtitle)
        xml = replace_body_in_xml(xml, items)
        write_file(new_path, xml)
        print(f"  [{i+1}/{len(CONTENT_SLIDES)}] {new_filename}: {title} / {subtitle}")

    # ─── Step 4: Update presentation.xml slide order ───
    print("Updating slide order...")
    pres_path = f"{WORK_DIR}/ppt/presentation.xml"
    pres_xml = read_file(pres_path)

    # Read the rels file to map slide filenames to rIds
    rels_path = f"{WORK_DIR}/ppt/_rels/presentation.xml.rels"
    rels_xml = read_file(rels_path)

    filename_to_rid = {}
    for m in re.finditer(r'Target="slides/(slide\d+\.xml)"[^>]*Id="(rId\d+)"', rels_xml):
        filename_to_rid[m.group(1)] = m.group(2)
    for m in re.finditer(r'Id="(rId\d+)"[^>]*Target="slides/(slide\d+\.xml)"', rels_xml):
        filename_to_rid[m.group(2)] = m.group(1)

    # Build new slide order: title, agenda, content slides, questions, thank you
    slide_order = ["slide1.xml", "slide2.xml"]
    slide_order.extend(new_slide_ids)
    slide_order.extend(["slide25.xml", "slide26.xml"])

    # Build new sldIdLst content
    sld_entries = []
    for idx, fname in enumerate(slide_order):
        rid = filename_to_rid.get(fname)
        if not rid:
            print(f"  WARNING: No rId found for {fname}")
            continue
        sld_entries.append(f'    <p:sldId id="{256 + idx}" r:id="{rid}"/>')
        print(f"  {fname} -> id={256+idx}, {rid}")

    new_sldIdLst = "<p:sldIdLst>\n" + "\n".join(sld_entries) + "\n  </p:sldIdLst>"

    # Replace the existing sldIdLst
    pres_xml = re.sub(
        r"<p:sldIdLst>.*?</p:sldIdLst>",
        new_sldIdLst,
        pres_xml,
        flags=re.DOTALL,
    )

    write_file(pres_path, pres_xml)

    # ─── Step 5: Clean orphaned slides and pack ───
    print("Cleaning orphaned files...")
    subprocess.run(
        ["python", f"{SCRIPTS_DIR}/clean.py", WORK_DIR], check=True
    )

    print("Packing final PPTX...")
    subprocess.run(
        [
            "python",
            f"{SCRIPTS_DIR}/office/pack.py",
            WORK_DIR,
            OUTPUT_PPTX,
            "--original",
            TEMPLATE_PPTX,
        ],
        check=True,
    )

    print(f"\nDone! Output: {OUTPUT_PPTX}")
    print(f"Total slides: {len(slide_order)}")


if __name__ == "__main__":
    main()
