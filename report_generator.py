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

    # Build info table with data source information
    data_source = cluster_info.get('data_source', 'Unknown')
    used_cib_xml = cluster_info.get('used_cib_xml', False)

    info_data = {
        "Cluster Name": cluster_name,
        "Nodes": ", ".join(nodes) if nodes else "N/A",
        "Data Source": data_source,
        "Report Date": datetime.now().strftime("%d %B %Y, %H:%M"),
        "Total Checks": str(total),
        "Passed": str(passed),
        "Failed": str(failed),
        "Critical Issues": str(critical),
        "Warnings": str(warnings),
    }

    pdf.info_table(info_data)

    pdf.ln(5)

    # =========================================================================
    # DATA SOURCE INFO BOX (SOSreport / cib.xml usage)
    # =========================================================================
    access_method = cluster_info.get('access_method', 'unknown')

    if access_method == 'sosreport':
        # Info box for sosreport analysis
        if used_cib_xml:
            # Yellow warning - cluster was stopped when sosreport was taken
            pdf.set_fill_color(255, 243, 205)  # Light yellow background
            pdf.set_draw_color(255, 193, 7)    # Yellow border
            pdf.set_text_color(133, 100, 4)    # Dark yellow/brown text
            box_title = "INFO: Analyzing SOSreport (cluster was stopped)"
            box_text = (
                "This analysis is based on SOSreport data. The cluster was not running when "
                "the SOSreport was collected, so cluster configuration was read from cib.xml. "
                "Some checks (node status, quorum, resource status) reflect the offline state."
            )
        else:
            # Blue info - sosreport analysis
            pdf.set_fill_color(217, 237, 247)  # Light blue background
            pdf.set_draw_color(49, 112, 143)   # Blue border
            pdf.set_text_color(31, 78, 121)    # Dark blue text
            box_title = "INFO: Analyzing SOSreport (offline data)"
            box_text = (
                "This analysis is based on SOSreport data collected from cluster nodes. "
                "No live SSH access was used. Results reflect the cluster state at the time "
                "the SOSreport was collected."
            )

        pdf.set_line_width(0.5)
        pdf.set_font('Helvetica', 'B', 11)

        y_start = pdf.get_y()
        pdf.rect(10, y_start, 190, 24, 'DF')
        pdf.set_xy(15, y_start + 3)
        pdf.cell(0, 6, box_title, ln=True)

        pdf.set_xy(15, y_start + 10)
        pdf.set_font('Helvetica', '', 9)
        pdf.multi_cell(180, 4, box_text)

        pdf.set_text_color(*RedHatColors.BLACK)
        pdf.set_line_width(0.2)
        pdf.ln(8)

    # =========================================================================
    # CLUSTER NOT RUNNING WARNING (for live access AND SOSreports)
    # =========================================================================
    cluster_running = cluster_info.get('cluster_running', True)

    # Also check install_status for live systems
    if install_status and access_method != 'sosreport':
        # Check if cluster is configured but not running
        has_config = install_status.get('corosync_conf_exists') or install_status.get('cib_exists')
        pacemaker_running = install_status.get('pacemaker_running')
        if has_config and not pacemaker_running:
            cluster_running = False

    if not cluster_running:
        # Determine warning message based on access method
        if access_method == 'sosreport':
            warning_title = "WARNING: Cluster Was Not Running When SOSreport Was Captured"
            warning_text = (
                "The SOSreport was collected while Pacemaker was not running. Health check results "
                "may be incomplete or inaccurate. Checks that require live cluster data (quorum, "
                "node status, resource status, replication status) will report ERROR status. "
                "Consider creating new SOSreports with the cluster running."
            )
        else:
            warning_title = "WARNING: Cluster Services Not Running"
            warning_text = (
                "The cluster is configured but Pacemaker is not running. Health check results "
                "may be incomplete or inaccurate. Checks that require live cluster data (quorum, "
                "node status, resource status, replication status) will report ERROR status."
            )

        # Add prominent warning box
        pdf.set_fill_color(255, 243, 205)  # Light yellow background
        pdf.set_draw_color(255, 193, 7)    # Yellow border
        pdf.set_line_width(0.5)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(133, 100, 4)    # Dark yellow/brown text

        # Warning box
        y_start = pdf.get_y()
        pdf.rect(10, y_start, 190, 38, 'DF')
        pdf.set_xy(15, y_start + 3)
        pdf.cell(0, 6, warning_title, ln=True)

        pdf.set_xy(15, y_start + 10)
        pdf.set_font('Helvetica', '', 9)
        pdf.multi_cell(180, 4, warning_text)
        pdf.set_xy(15, y_start + 22)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(0, 4, "To start the cluster and rerun the health check:")
        pdf.set_xy(15, y_start + 28)
        pdf.set_font('Courier', '', 9)
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(180, 5, "  pcs cluster start --all", fill=True)

        pdf.set_text_color(*RedHatColors.BLACK)
        pdf.set_line_width(0.2)
        pdf.ln(20)

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
    majority_makers = cluster_info.get('majority_makers', [])
    for node in nodes:
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(5, 6, "-")  # Bullet point
        if node in majority_makers:
            pdf.set_font('Helvetica', 'I', 10)
            pdf.cell(0, 6, f"{node} (MajorityMaker)", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.cell(0, 6, node, new_x="LMARGIN", new_y="NEXT")

    # Note about MajorityMaker constraints for Scale-Out
    if majority_makers and cluster_info.get('cluster_type') == 'Scale-Out':
        pdf.ln(2)
        pdf.set_font('Helvetica', 'I', 8)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 4,
            f"Note: MajorityMaker node(s) have location constraints with resource-discovery=never "
            f"to prevent SAPHanaTopology and SAPHanaController from running on these nodes."
        )
        pdf.set_text_color(*RedHatColors.BLACK)

    pdf.ln(5)

    # SAP HANA HA Parameters (Ansible-compatible)
    sid = cluster_info.get('sid')
    if sid:
        pdf.sub_section("SAP HANA Configuration")
        hana_config = {}
        if sid:
            hana_config["SID"] = sid
        if cluster_info.get('instance_number'):
            hana_config["Instance Number"] = cluster_info.get('instance_number')
        if cluster_info.get('virtual_ip'):
            hana_config["Virtual IP (Primary)"] = cluster_info.get('virtual_ip')
        if cluster_info.get('secondary_vip'):
            hana_config["Virtual IP (Secondary)"] = cluster_info.get('secondary_vip')
        if cluster_info.get('replication_mode'):
            hana_config["Replication Mode"] = cluster_info.get('replication_mode')
        if cluster_info.get('operation_mode'):
            hana_config["Operation Mode"] = cluster_info.get('operation_mode')
        if cluster_info.get('secondary_read') is not None:
            hana_config["Secondary Read Enabled"] = str(cluster_info.get('secondary_read'))
        if hana_config:
            pdf.info_table(hana_config)
        pdf.ln(3)

        # HA Parameters
        ha_config = {}
        if cluster_info.get('prefer_site_takeover') is not None:
            ha_config["Prefer Site Takeover"] = str(cluster_info.get('prefer_site_takeover'))
        if cluster_info.get('automated_register') is not None:
            ha_config["Automated Register"] = str(cluster_info.get('automated_register'))
        if cluster_info.get('duplicate_primary_timeout') is not None:
            ha_config["Duplicate Primary Timeout"] = str(cluster_info.get('duplicate_primary_timeout'))
        if cluster_info.get('migration_threshold') is not None:
            ha_config["Migration Threshold"] = str(cluster_info.get('migration_threshold'))
        if ha_config:
            pdf.sub_section("HA Parameters")
            pdf.info_table(ha_config)
        pdf.ln(3)

        # SAPHanaTopology Resource (Scale-Out)
        topology_resource = cluster_info.get('topology_resource')
        if topology_resource:
            pdf.sub_section("SAPHanaTopology Resource")
            topo_config = {
                "Resource Name": topology_resource,
                "Resource Agent": "ocf:suse:SAPHanaTopology",
                "Clone Type": "clone (runs on all HANA nodes)",
                "interleave": "true",
            }
            # Add majority maker exclusion info
            if majority_makers:
                topo_config["Excluded Nodes"] = ", ".join(majority_makers) + " (resource-discovery=never)"
            pdf.info_table(topo_config)
            pdf.ln(3)

        # SAPHanaController Resource (Scale-Out) / SAPHana Resource (Scale-Up)
        res_config = {}
        resource_type = cluster_info.get('resource_type')
        resource_name = cluster_info.get('resource_name')
        if resource_type and resource_name:
            if resource_type == 'SAPHanaController':
                pdf.sub_section("SAPHanaController Resource")
                res_config["Resource Name"] = resource_name
                res_config["Resource Agent"] = "ocf:suse:SAPHanaController"
                res_config["Clone Type"] = "promotable (master/slave)"
                res_config["interleave"] = "true"
                # Add majority maker exclusion info
                if majority_makers:
                    res_config["Excluded Nodes"] = ", ".join(majority_makers) + " (resource-discovery=never)"
            else:
                pdf.sub_section("SAPHana Resource")
                res_config["Resource Name"] = resource_name
                res_config["Resource Agent"] = "ocf:suse:SAPHana"
                res_config["Clone Type"] = "promotable (master/slave)"
            pdf.info_table(res_config)
            pdf.ln(3)

        # VIP Resources
        vip_config = {}
        if cluster_info.get('vip_resource'):
            vip_config["Primary VIP Resource"] = cluster_info.get('vip_resource')
        if cluster_info.get('secondary_vip_resource'):
            vip_config["Secondary VIP Resource"] = cluster_info.get('secondary_vip_resource')
        if vip_config:
            pdf.sub_section("Virtual IP Resources")
            pdf.info_table(vip_config)
        pdf.ln(3)

        # STONITH Configuration
        stonith_config = {}
        if cluster_info.get('stonith_device'):
            stonith_config["STONITH Device"] = cluster_info.get('stonith_device')
        stonith_params = cluster_info.get('stonith_params')
        if stonith_params:
            if stonith_params.get('ssl'):
                stonith_config["SSL Enabled"] = "Yes" if stonith_params.get('ssl') == '1' else "No"
            if stonith_params.get('ssl_insecure'):
                stonith_config["SSL Insecure"] = "Yes" if stonith_params.get('ssl_insecure') == '1' else "No"
        if stonith_config:
            pdf.sub_section("STONITH/Fencing Configuration")
            pdf.info_table(stonith_config)
            # Show pcmk_host_map in a formatted table
            if stonith_params and stonith_params.get('pcmk_host_map'):
                pdf.ln(3)
                pdf.set_font('Helvetica', 'B', 9)
                pdf.cell(0, 5, "STONITH Host Mapping (pcmk_host_map):", ln=True)
                pdf.ln(1)
                # Table header
                pdf.set_fill_color(240, 240, 240)
                pdf.set_font('Helvetica', 'B', 8)
                pdf.cell(60, 5, "Cluster Node", border=1, fill=True)
                pdf.cell(80, 5, "STONITH Target", border=1, fill=True, ln=True)
                # Table rows
                pdf.set_font('Helvetica', '', 8)
                host_map = stonith_params.get('pcmk_host_map', '')
                hosts = host_map.split(';')
                for host in hosts:
                    if host.strip() and ':' in host:
                        node, target = host.strip().split(':', 1)
                        pdf.cell(60, 5, node, border=1)
                        pdf.cell(80, 5, target, border=1, ln=True)

        pdf.ln(5)

    # =========================================================================
    # CONFIGURED RESOURCES (from cib.xml)
    # =========================================================================
    resource_config = cluster_info.get('resource_config')
    if resource_config and resource_config.get('available'):
        pdf.add_page()
        pdf.chapter_title("Configured Resources (from cib.xml)")

        # Resources summary
        resources = resource_config.get('resources', {})
        if resources.get('list'):
            pdf.sub_section("Cluster Resources")
            pdf.set_font('Courier', '', 8)
            for resource in resources.get('list', [])[:20]:  # Limit to 20 resources
                pdf.set_x(10)  # Reset to left margin
                pdf.multi_cell(0, 4, f"- {resource[:90]}")  # Truncate long lines
            if len(resources.get('list', [])) > 20:
                pdf.set_font('Helvetica', 'I', 8)
                pdf.set_x(10)
                pdf.cell(0, 4, f"  ... and {len(resources['list']) - 20} more resources", ln=True)
            pdf.ln(3)

        # SAP HANA specific configuration
        sap_hana = resource_config.get('sap_hana', {})
        if sap_hana:
            pdf.sub_section("SAP HANA Resource Configuration")
            for resource_name, attrs in sap_hana.items():
                pdf.set_font('Helvetica', 'B', 9)
                pdf.cell(0, 5, resource_name[:60], ln=True)
                pdf.set_font('Courier', '', 8)
                for key, value in attrs.items():
                    # Truncate long values to prevent layout issues
                    val_str = str(value)[:80]
                    pdf.cell(0, 4, f"  {key}={val_str}", ln=True)
                pdf.ln(2)

        # Constraints summary
        constraints = resource_config.get('constraints', {})

        # Location constraints with resource-discovery
        resource_discovery = constraints.get('resource_discovery', [])
        if resource_discovery:
            pdf.sub_section("Resource Discovery Settings")
            pdf.set_font('Courier', '', 8)
            for rd in resource_discovery[:15]:
                pdf.set_x(10)
                pdf.multi_cell(0, 4, rd[:100])
            if len(resource_discovery) > 15:
                pdf.set_font('Helvetica', 'I', 8)
                pdf.set_x(10)
                pdf.cell(0, 4, f"  ... and {len(resource_discovery) - 15} more", ln=True)
            pdf.ln(3)

        # Location constraints
        location = constraints.get('location', [])
        if location:
            pdf.sub_section("Location Constraints")
            pdf.set_font('Courier', '', 7)
            shown = 0
            for loc in location:
                if shown >= 20:
                    break
                if loc.startswith('resource') or loc.startswith('Resource'):
                    pdf.set_x(10)
                    pdf.multi_cell(0, 3.5, loc[:100])
                    shown += 1
            if len([ln for ln in location if ln.startswith('resource') or ln.startswith('Resource')]) > 20:
                pdf.set_font('Helvetica', 'I', 8)
                pdf.set_x(10)
                pdf.cell(0, 4, "  ... more constraints in full output", ln=True)
            pdf.ln(3)

        # Colocation constraints
        colocation = constraints.get('colocation', [])
        if colocation:
            pdf.sub_section("Colocation Constraints")
            pdf.set_font('Courier', '', 8)
            for col in colocation[:10]:
                pdf.set_x(10)
                pdf.multi_cell(0, 4, col[:100])
            pdf.ln(3)

        # Order constraints
        order = constraints.get('order', [])
        if order:
            pdf.sub_section("Order Constraints")
            pdf.set_font('Courier', '', 8)
            for ord_c in order[:10]:
                pdf.set_x(10)
                pdf.multi_cell(0, 4, ord_c[:100])
            pdf.ln(3)

        # STONITH info from cib
        stonith = resource_config.get('stonith', {})
        if stonith.get('devices'):
            pdf.sub_section("STONITH Devices (from cib.xml)")
            pdf.set_font('Courier', '', 8)
            for device in stonith.get('devices', [])[:10]:
                pdf.set_x(10)
                pdf.multi_cell(0, 4, device[:100])
            pdf.ln(3)

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

        # Add prominent note when cluster is stopped and there are errors
        if error_checks and not cluster_running:
            pdf.set_fill_color(255, 243, 205)  # Light yellow background
            pdf.set_draw_color(255, 193, 7)    # Yellow border
            pdf.set_line_width(0.3)
            y_note = pdf.get_y()
            pdf.rect(10, y_note, 190, 16, 'DF')
            pdf.set_xy(15, y_note + 2)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(133, 100, 4)
            pdf.cell(0, 5, "Cluster Not Running - Some checks cannot retrieve live data", ln=True)
            pdf.set_xy(15, y_note + 8)
            pdf.set_font('Helvetica', '', 8)
            pdf.multi_cell(180, 4,
                "ERROR status below may be caused by the stopped cluster. Start the cluster "
                "with 'pcs cluster start --all' and rerun the health check for accurate results."
            )
            pdf.set_text_color(*RedHatColors.BLACK)
            pdf.set_line_width(0.2)
            pdf.ln(5)

        for check in failed_checks + error_checks:
            pdf.check_result_row(
                check.get('check_id', 'N/A'),
                check.get('description', ''),
                check.get('status', 'FAILED'),
                check.get('message', ''),
                check.get('node', '')
            )

        # Add note about errors when cluster is stopped (for running cluster case)
        if error_checks and cluster_running:
            pdf.ln(3)
            pdf.set_font('Helvetica', 'I', 9)
            pdf.set_text_color(*RedHatColors.GRAY)
            pdf.multi_cell(0, 5,
                "Note: Some checks report ERROR status when data could not be retrieved. "
                "This may indicate a problem with the cluster configuration or services."
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
    """Load results from YAML report file (legacy format)"""
    import yaml

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    results = data.get('results', [])
    summary = data.get('summary', {})

    return results, summary


def load_unified_yaml_report(yaml_path: str) -> tuple:
    """
    Load report data from unified YAML format.

    This function supports both the new unified format (with version field)
    and the legacy format (only results and summary).

    Args:
        yaml_path: Path to YAML report file

    Returns:
        Tuple of (results, summary, cluster_info, install_status)
        - results: List of check result dicts
        - summary: Summary statistics dict
        - cluster_info: Cluster information dict for PDF generation
        - install_status: Installation status dict (or None)
    """
    import yaml

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    # Check if this is the unified format (has version field)
    if 'version' in data:
        # Unified format - extract all components
        results = data.get('results', [])
        summary = data.get('summary', {})

        # Build cluster_info from unified data
        cluster_info = {
            'cluster_name': data.get('cluster_name', 'Unknown'),
            'nodes': data.get('nodes', []),
            'cluster_type': data.get('cluster_type', 'Scale-Up'),
            'majority_makers': data.get('majority_makers', []),

            # Data source
            'data_source': data.get('data_source', 'Unknown'),
            'access_method': data.get('access_method', 'unknown'),
            'used_cib_xml': data.get('used_cib_xml', False),

            # OS/Software versions
            'rhel_version': data.get('rhel_version'),
            'pacemaker_version': data.get('pacemaker_version'),

            # SAP HANA config
            'sid': data.get('sid'),
            'instance_number': data.get('instance_number'),
            'virtual_ip': data.get('virtual_ip'),
            'secondary_vip': data.get('secondary_vip'),
            'replication_mode': data.get('replication_mode'),
            'operation_mode': data.get('operation_mode'),
            'secondary_read': data.get('secondary_read'),

            # Node config
            'node1_hostname': data.get('node1_hostname'),
            'node1_ip': data.get('node1_ip'),
            'node2_hostname': data.get('node2_hostname'),
            'node2_ip': data.get('node2_ip'),
            'sites': data.get('sites'),

            # HA parameters
            'prefer_site_takeover': data.get('prefer_site_takeover'),
            'automated_register': data.get('automated_register'),
            'duplicate_primary_timeout': data.get('duplicate_primary_timeout'),
            'migration_threshold': data.get('migration_threshold'),

            # Resource config
            'resource_type': data.get('resource_type'),
            'resource_name': data.get('resource_name'),
            'topology_resource': data.get('topology_resource'),
            'vip_resource': data.get('vip_resource'),
            'secondary_vip_resource': data.get('secondary_vip_resource'),

            # STONITH
            'stonith_device': data.get('stonith_device'),
            'stonith_params': data.get('stonith_params'),

            # CIB resource config
            'resource_config': data.get('resource_config'),
        }

        install_status = data.get('install_status')

        return results, summary, cluster_info, install_status

    else:
        # Legacy format - only has results and summary
        results = data.get('results', [])
        summary = data.get('summary', {})

        # Build minimal cluster_info
        cluster_info = {
            'cluster_name': 'Unknown',
            'nodes': [],
            'cluster_type': 'Scale-Up',
            'data_source': 'Legacy YAML report',
        }

        return results, summary, cluster_info, None


if __name__ == "__main__":
    # Standalone mode - convert YAML to PDF
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate PDF health check report from YAML",
        epilog="""
Examples:
  # Generate PDF from unified YAML report
  python report_generator.py 20260410_120000_mycluster.yaml

  # Generate PDF with custom output path
  python report_generator.py report.yaml -o custom_report.pdf

  # Generate demo PDF (no YAML input)
  python report_generator.py --demo
        """
    )
    parser.add_argument('yaml_report', nargs='?', help='YAML report file to convert to PDF')
    parser.add_argument('-o', '--output', help='Output PDF path')
    parser.add_argument('--cluster', default='Test Cluster', help='Cluster name (for legacy YAML or demo)')
    parser.add_argument('--nodes', nargs='+', default=['node1', 'node2'], help='Node names (for legacy YAML or demo)')
    parser.add_argument('--demo', action='store_true', help='Generate a demo PDF with sample data')

    args = parser.parse_args()

    install_status = None

    if args.yaml_report:
        # Load from YAML using unified loader
        results, summary, cluster_info, install_status = load_unified_yaml_report(args.yaml_report)

        # Override cluster name and nodes if provided via CLI
        if args.cluster != 'Test Cluster':
            cluster_info['cluster_name'] = args.cluster
        if args.nodes != ['node1', 'node2']:
            cluster_info['nodes'] = args.nodes

        print(f"Loaded report from: {args.yaml_report}")
        print(f"  Cluster: {cluster_info.get('cluster_name', 'Unknown')}")
        print(f"  Data source: {cluster_info.get('data_source', 'Unknown')}")
        print(f"  Checks: {summary.get('total', 0)} total, {summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed")

    elif args.demo:
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
            'data_source': 'Demo data',
        }
        print("Generating demo PDF report...")

    else:
        parser.print_help()
        print("\nError: Please provide a YAML report file or use --demo")
        exit(1)

    output = generate_health_check_report(results, summary, cluster_info, args.output, install_status)
    print(f"PDF report generated: {output}")
