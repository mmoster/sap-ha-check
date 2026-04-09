#!/usr/bin/env python3
"""
PDF Report Generator for SAP HANA Cluster Health Check
Following Red Hat Documentation Style Guidelines
"""

from datetime import datetime
from typing import Dict, List

# fpdf2 is optional - PDF generation will be skipped if not available
FPDF_AVAILABLE = False
try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    # Create a dummy base class so the module can be imported
    class FPDF:
        """Dummy FPDF class when fpdf2 is not installed."""
        def __init__(self, *args, **kwargs):
            raise ImportError("PDF generation requires fpdf2. Install with: pip install fpdf2")


def is_pdf_available() -> bool:
    """Check if PDF generation is available (fpdf2 installed)."""
    return FPDF_AVAILABLE


class RedHatColors:
    """Red Hat brand colors"""
    RED = (204, 0, 0)           # Red Hat Red
    DARK_RED = (163, 0, 0)      # Darker red for headers
    BLACK = (21, 21, 21)        # Near black
    GRAY = (102, 102, 102)      # Medium gray
    LIGHT_GRAY = (240, 240, 240)  # Background gray
    WHITE = (255, 255, 255)
    GREEN = (63, 156, 53)       # Success green
    YELLOW = (236, 178, 0)      # Warning yellow
    ORANGE = (255, 140, 0)      # Incomplete/in-progress orange
    BLUE = (0, 102, 204)        # Link blue


class HealthCheckPDF(FPDF):
    """PDF Report Generator following Red Hat style guidelines"""

    def __init__(self, cluster_name: str = "Unknown", report_date: str = None):
        super().__init__()
        self.cluster_name = cluster_name
        self.report_date = report_date or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        """Page header with Red Hat styling"""
        # Red header bar
        self.set_fill_color(*RedHatColors.RED)
        self.rect(0, 0, 210, 12, 'F')

        # Header text
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*RedHatColors.WHITE)
        self.set_xy(10, 3)
        self.cell(0, 6, 'SAP HANA Cluster Health Check Report', align='L')

        self.set_xy(-60, 3)
        self.set_font('Helvetica', '', 8)
        self.cell(50, 6, self.report_date, align='R')

        self.ln(15)

    def footer(self):
        """Page footer"""
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(*RedHatColors.GRAY)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    def chapter_title(self, title: str):
        """Section header with Red Hat styling"""
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(*RedHatColors.DARK_RED)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        # Underline
        self.set_draw_color(*RedHatColors.RED)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def sub_section(self, title: str):
        """Subsection header"""
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(*RedHatColors.BLACK)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")

    def body_text(self, text: str):
        """Regular body text"""
        self.set_font('Helvetica', '', 10)
        self.set_text_color(*RedHatColors.BLACK)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def status_badge(self, status: str, x: float = None, y: float = None):
        """Draw a colored status badge"""
        if x is not None:
            self.set_x(x)
        if y is not None:
            self.set_y(y)

        colors = {
            'PASSED': RedHatColors.GREEN,
            'FAILED': RedHatColors.RED,
            'WARNING': RedHatColors.YELLOW,
            'SKIPPED': RedHatColors.GRAY,
            'ERROR': RedHatColors.RED,
            'OK': RedHatColors.GREEN,
            'CRITICAL': RedHatColors.RED,
            'CRITICAL - INCOMPLETE': RedHatColors.RED,
            'FAILED - INCOMPLETE': RedHatColors.ORANGE,
            'INCOMPLETE': RedHatColors.ORANGE,
            'NEEDS ATTENTION': RedHatColors.YELLOW,
            'HEALTHY': RedHatColors.GREEN,
        }

        color = colors.get(status.upper(), RedHatColors.GRAY)

        self.set_fill_color(*color)
        self.set_text_color(*RedHatColors.WHITE)
        self.set_font('Helvetica', 'B', 8)

        width = self.get_string_width(status) + 6
        self.cell(width, 6, status, fill=True, align='C')
        self.set_text_color(*RedHatColors.BLACK)

    def info_table(self, data: Dict[str, str]):
        """Draw an info table with key-value pairs"""
        self.set_font('Helvetica', '', 10)
        col_width = 50

        for key, value in data.items():
            self.set_font('Helvetica', 'B', 10)
            self.set_text_color(*RedHatColors.GRAY)
            self.cell(col_width, 7, f"{key}:", align='L')

            self.set_font('Helvetica', '', 10)
            self.set_text_color(*RedHatColors.BLACK)
            self.cell(0, 7, str(value), new_x="LMARGIN", new_y="NEXT")

    def check_result_row(self, check_id: str, description: str, status: str,
                         message: str = "", node: str = ""):
        """Draw a check result row"""
        # Background for alternating rows
        y_start = self.get_y()

        # Status badge
        self.status_badge(status)
        self.set_xy(30, y_start)

        # Check ID
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(*RedHatColors.BLACK)
        self.cell(45, 6, check_id, ln=False)

        # Description
        self.set_font('Helvetica', '', 9)
        self.cell(0, 6, description[:50] + ('...' if len(description) > 50 else ''), new_x="LMARGIN", new_y="NEXT")

        # Message and node if present
        if message or node:
            self.set_x(30)
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(*RedHatColors.GRAY)
            info = []
            if node:
                info.append(f"Node: {node}")
            if message:
                info.append(message[:70])
            self.cell(0, 5, " | ".join(info), new_x="LMARGIN", new_y="NEXT")

        self.ln(2)

    def command_block(self, command: str, description: str = ""):
        """Draw a command block (code style)"""
        if description:
            self.set_font('Helvetica', 'I', 9)
            self.set_text_color(*RedHatColors.GRAY)
            self.cell(0, 5, f"# {description}", new_x="LMARGIN", new_y="NEXT")

        # Command background
        self.set_fill_color(*RedHatColors.LIGHT_GRAY)
        self.set_font('Courier', '', 9)
        self.set_text_color(*RedHatColors.BLACK)

        # Handle multi-line commands
        lines = command.split('\n')
        for line in lines:
            self.cell(0, 6, f"  {line}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def recommendation_box(self, priority: str, title: str, description: str,
                           commands: List[str] = None):
        """Draw a recommendation box"""
        y_start = self.get_y()

        # Priority indicator
        priority_colors = {
            '1': RedHatColors.RED,
            '2': RedHatColors.YELLOW,
            '3': RedHatColors.BLUE,
        }
        color = priority_colors.get(priority, RedHatColors.GRAY)

        # Left border
        self.set_draw_color(*color)
        self.set_line_width(2)
        self.line(10, y_start, 10, y_start + 20)

        # Title
        self.set_x(15)
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*RedHatColors.BLACK)
        self.cell(0, 6, f"Priority {priority}: {title}", new_x="LMARGIN", new_y="NEXT")

        # Description
        self.set_x(15)
        self.set_font('Helvetica', '', 9)
        self.set_text_color(*RedHatColors.GRAY)
        self.multi_cell(180, 5, description)

        # Commands
        if commands:
            self.ln(2)
            for cmd in commands:
                self.set_x(15)
                self.command_block(cmd)

        self.ln(5)


def generate_health_check_report(
    results: List[Dict],
    summary: Dict,
    cluster_info: Dict,
    output_path: str = None,
    install_status: Dict = None
) -> str:
    """
    Generate a PDF health check report.

    Args:
        results: List of check results
        summary: Summary statistics
        cluster_info: Cluster information (name, nodes, etc.)
        output_path: Output file path (optional)
        install_status: Installation status dict (optional)

    Returns:
        Path to generated PDF file

    Raises:
        ImportError: If fpdf2 is not installed
    """
    if not FPDF_AVAILABLE:
        raise ImportError("PDF generation requires fpdf2. Install with: pip install fpdf2")

    cluster_name = cluster_info.get('cluster_name', 'Unknown Cluster')
    nodes = cluster_info.get('nodes', [])

    pdf = HealthCheckPDF(cluster_name=cluster_name)
    pdf.alias_nb_pages()
    pdf.add_page()

    # =========================================================================
    # EXECUTIVE SUMMARY
    # =========================================================================
    pdf.chapter_title("Executive Summary")

    # Overall status
    total = summary.get('total', 0)
    passed = summary.get('passed', 0)
    failed = summary.get('failed', 0)
    warnings = summary.get('warning_count', 0)
    critical = summary.get('critical_count', 0)

    # Check installation completeness
    install_complete = True
    steps_done = 0
    steps_total = 7
    missing_steps = []
    if install_status:
        steps_done = sum(1 for v in [
            install_status.get('subscription_registered'),
            install_status.get('repos_enabled'),
            install_status.get('packages_installed'),
            install_status.get('pcsd_running'),
            install_status.get('cluster_configured'),
            install_status.get('stonith_configured'),
            install_status.get('hana_resources')
        ] if v)
        install_complete = (steps_done >= steps_total)

        # Build list of missing steps
        if not install_status.get('stonith_configured'):
            missing_steps.append("stonith")
        if not install_status.get('hana_resources'):
            missing_steps.append("hana_resources")
        if not install_status.get('cluster_configured'):
            missing_steps.append("cluster")

    # Determine overall status considering both checks and installation
    status_descriptions = {
        "CRITICAL - INCOMPLETE": "Critical issues found and installation incomplete",
        "FAILED - INCOMPLETE": "Failed checks and installation incomplete",
        "CRITICAL": "Critical issues found, installation complete",
        "NEEDS ATTENTION": "Failed checks found, installation complete",
        "INCOMPLETE": "No failures, but installation incomplete",
        "WARNING": "Warnings only, no critical issues",
        "HEALTHY": "All checks passed, cluster fully configured",
    }

    if critical > 0 and not install_complete:
        overall_status = "CRITICAL - INCOMPLETE"
    elif critical > 0:
        overall_status = "CRITICAL"
    elif failed > 0 and not install_complete:
        overall_status = "FAILED - INCOMPLETE"
    elif failed > 0:
        overall_status = "NEEDS ATTENTION"
    elif not install_complete:
        overall_status = "INCOMPLETE"
    elif warnings > 0:
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"

    # Status summary table
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(40, 8, "Overall Status: ")
    pdf.status_badge(overall_status)
    pdf.ln(6)
    # Add status description in smaller font
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(*RedHatColors.GRAY)
    pdf.cell(0, 5, status_descriptions.get(overall_status, ""), ln=True)
    pdf.set_text_color(*RedHatColors.BLACK)
    pdf.ln(4)

    pdf.info_table({
        "Cluster Name": cluster_name,
        "Nodes": ", ".join(nodes) if nodes else "N/A",
        "Report Date": datetime.now().strftime("%d %B %Y, %H:%M"),
        "Total Checks": str(total),
        "Passed": str(passed),
        "Failed": str(failed),
        "Critical Issues": str(critical),
        "Warnings": str(warnings),
    })

    pdf.ln(5)

    # =========================================================================
    # CLUSTER CONFIGURATION
    # =========================================================================
    pdf.chapter_title("Cluster Configuration")

    pdf.info_table({
        "Cluster Type": cluster_info.get('cluster_type', 'Scale-Up'),
        "Node Count": str(len(nodes)),
        "RHEL Version": cluster_info.get('rhel_version', 'N/A'),
        "Pacemaker": cluster_info.get('pacemaker_version', 'N/A'),
    })

    pdf.ln(5)

    # Node list
    pdf.sub_section("Cluster Nodes")
    for node in nodes:
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(5, 6, "-")  # Bullet point
        pdf.cell(0, 6, node, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # =========================================================================
    # CHECK RESULTS
    # =========================================================================
    pdf.add_page()
    pdf.chapter_title("Health Check Results")

    # Group results by status
    passed_checks = [r for r in results if r.get('status') == 'PASSED']
    failed_checks = [r for r in results if r.get('status') == 'FAILED']
    warning_checks = [r for r in results if r.get('severity') == 'WARNING' and r.get('status') == 'FAILED']
    error_checks = [r for r in results if r.get('status') == 'ERROR']
    skipped_checks = [r for r in results if r.get('status') == 'SKIPPED']

    # Critical/Failed checks first
    if failed_checks or error_checks:
        pdf.sub_section("Failed Checks")
        for check in failed_checks + error_checks:
            pdf.check_result_row(
                check.get('check_id', 'N/A'),
                check.get('description', ''),
                check.get('status', 'FAILED'),
                check.get('message', ''),
                check.get('node', '')
            )

        # Add note about errors when cluster is stopped
        if error_checks:
            pdf.ln(3)
            pdf.set_font('Helvetica', 'I', 9)
            pdf.set_text_color(*RedHatColors.GRAY)
            pdf.multi_cell(0, 5,
                "Note: Some checks report ERROR status when the cluster services are not running. "
                "Commands like 'crm_mon', 'pcs status', and 'SAPHanaSR-showAttr' require a running "
                "cluster to report accurate status. Configuration checks using 'pcs -f cib.xml' can "
                "still verify the cluster configuration is correct even when stopped."
            )
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    # Warnings
    if warning_checks:
        pdf.sub_section("Warnings")
        for check in warning_checks:
            pdf.check_result_row(
                check.get('check_id', 'N/A'),
                check.get('description', ''),
                'WARNING',
                check.get('message', ''),
                check.get('node', '')
            )

    # Passed checks (collapsed)
    if passed_checks:
        pdf.sub_section(f"Passed Checks ({len(passed_checks)})")
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(*RedHatColors.GREEN)

        # List passed checks in compact format
        for i, check in enumerate(passed_checks):
            if i > 0 and i % 3 == 0:
                pdf.ln(5)
            pdf.cell(60, 5, f"[OK] {check.get('check_id', 'N/A')}", new_x="LMARGIN" if (i % 3 == 2) else "RIGHT", new_y="NEXT" if (i % 3 == 2) else "TOP")
        pdf.ln(8)

    # Skipped checks
    if skipped_checks:
        pdf.sub_section(f"Skipped Checks ({len(skipped_checks)})")
        pdf.set_font('Helvetica', 'I', 9)
        pdf.set_text_color(*RedHatColors.GRAY)
        pdf.body_text(f"Skipped {len(skipped_checks)} checks (SAP HANA not installed or not applicable)")

    # =========================================================================
    # RECOMMENDATIONS
    # =========================================================================
    pdf.add_page()
    pdf.chapter_title("Recommendations")

    priority = 1

    # Generate recommendations based on failed checks
    if any(c.get('check_id') == 'CHK_STONITH_CONFIG' for c in failed_checks):
        pdf.recommendation_box(
            str(priority),
            "Configure STONITH/Fencing",
            "STONITH is required for production SAP HANA clusters to ensure data integrity.",
            [
                "# Option A: Configure real STONITH (production)\npcs stonith create fence_node1 fence_ipmilan \\\n    ipaddr=<IPMI_IP> login=<USER> passwd=<PASS> \\\n    lanplus=1 pcmk_host_list=node1",
                "# Option B: Disable STONITH (test/dev only)\npcs property set stonith-enabled=false"
            ]
        )
        priority += 1

    if any(c.get('check_id') == 'CHK_HANA_INSTALLED' for c in failed_checks):
        pdf.recommendation_box(
            str(priority),
            "Install SAP HANA",
            "SAP HANA database is not installed on one or more cluster nodes.",
            [
                "# Run SAP HANA installation\n./hdblcm --action=install --sid=<SID> --number=<INST>"
            ]
        )
        priority += 1

    if any(c.get('check_id') in ['CHK_CLONE_CONFIG', 'CHK_RESOURCE_STATUS'] for c in failed_checks):
        pdf.recommendation_box(
            str(priority),
            "Configure SAP HANA Cluster Resources",
            "SAP HANA cluster resources are not configured. Configure SAPHana and SAPHanaTopology resources.",
            [
                "# Create SAPHanaTopology resource\npcs resource create SAPHanaTopology_<SID>_<INST> SAPHanaTopology \\\n    SID=<SID> InstanceNumber=<INST> \\\n    clone clone-max=2 clone-node-max=1 interleave=true",
                "# Create SAPHana resource\npcs resource create SAPHana_<SID>_<INST> SAPHana \\\n    SID=<SID> InstanceNumber=<INST> \\\n    PREFER_SITE_TAKEOVER=true DUPLICATE_PRIMARY_TIMEOUT=7200 \\\n    promotable notify=true clone-max=2 clone-node-max=1"
            ]
        )
        priority += 1

    if priority == 1:  # No specific recommendations
        pdf.body_text("No critical issues found. The cluster appears to be properly configured.")
        pdf.ln(5)

    # =========================================================================
    # BEST PRACTICES CHECKLIST
    # =========================================================================
    pdf.chapter_title("Best Practices Checklist")

    best_practices = [
        ("STONITH/Fencing enabled", "Ensures data integrity during split-brain scenarios"),
        ("Two-node quorum configured", "Proper quorum settings for 2-node clusters"),
        ("HANA System Replication active", "Synchronous or memory-sync replication mode"),
        ("HA/DR hooks configured", "SAPHanaSR hooks for cluster awareness"),
        ("Resource timeouts set", "Appropriate timeouts for SAP HANA operations"),
        ("Monitoring enabled", "Integration with monitoring systems"),
        ("Backup strategy defined", "Regular backups and tested recovery"),
        ("Documentation updated", "Runbooks and procedures documented"),
    ]

    for practice, description in best_practices:
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(8, 6, "[ ]")  # Checkbox
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(70, 6, practice)
        pdf.set_font('Helvetica', 'I', 9)
        pdf.set_text_color(*RedHatColors.GRAY)
        pdf.cell(0, 6, description, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*RedHatColors.BLACK)

    # =========================================================================
    # DOCUMENTATION REFERENCES
    # =========================================================================
    pdf.ln(10)
    pdf.chapter_title("Documentation References")

    references = [
        ("SAP HANA Administration Guide", "https://help.sap.com/docs/SAP_HANA_PLATFORM"),
        ("SAP HANA System Replication", "https://help.sap.com/docs/SAP_HANA_PLATFORM/6b94445c94ae495c83a19646e7c3fd56"),
        ("Red Hat HA Clusters", "https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/configuring_and_managing_high_availability_clusters/"),
        ("Pacemaker Documentation", "https://clusterlabs.org/pacemaker/doc/"),
    ]

    for title, url in references:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(60, 6, title)
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(*RedHatColors.BLUE)
        pdf.cell(0, 6, url, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*RedHatColors.BLACK)

    # =========================================================================
    # SAVE PDF
    # =========================================================================
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"health_check_report_{timestamp}.pdf"

    pdf.output(output_path)
    return output_path


def load_yaml_report(yaml_path: str) -> tuple:
    """Load results from YAML report file"""
    import yaml

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    results = data.get('results', [])
    summary = data.get('summary', {})

    return results, summary


if __name__ == "__main__":
    # Test/demo mode
    import argparse

    parser = argparse.ArgumentParser(description="Generate PDF health check report")
    parser.add_argument('yaml_report', nargs='?', help='YAML report file to convert')
    parser.add_argument('-o', '--output', help='Output PDF path')
    parser.add_argument('--cluster', default='Test Cluster', help='Cluster name')
    parser.add_argument('--nodes', nargs='+', default=['node1', 'node2'], help='Node names')

    args = parser.parse_args()

    if args.yaml_report:
        # Load from YAML
        results, summary = load_yaml_report(args.yaml_report)
        cluster_info = {
            'cluster_name': args.cluster,
            'nodes': args.nodes,
        }
    else:
        # Demo data
        results = [
            {'check_id': 'CHK_NODE_STATUS', 'description': 'Verify all cluster nodes are online',
             'status': 'PASSED', 'severity': 'CRITICAL', 'node': 'cluster'},
            {'check_id': 'CHK_STONITH_CONFIG', 'description': 'Verify STONITH/fencing is configured',
             'status': 'FAILED', 'severity': 'WARNING', 'message': 'No STONITH resources configured', 'node': 'cluster'},
            {'check_id': 'CHK_HANA_INSTALLED', 'description': 'Check if SAP HANA is installed',
             'status': 'FAILED', 'severity': 'INFO', 'message': 'SAP HANA not installed', 'node': 'node1'},
        ]
        summary = {'total': 3, 'passed': 1, 'failed': 2, 'critical_count': 0, 'warning_count': 1}
        cluster_info = {
            'cluster_name': args.cluster,
            'nodes': args.nodes,
            'cluster_type': 'Scale-Up',
        }

    output = generate_health_check_report(results, summary, cluster_info, args.output)
    print(f"PDF report generated: {output}")
