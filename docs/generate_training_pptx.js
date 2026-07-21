const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// Icon imports
const {
  FaCheckCircle, FaTimesCircle, FaExclamationTriangle, FaInfoCircle,
  FaServer, FaNetworkWired, FaDatabase, FaTerminal, FaFileAlt,
  FaClipboardCheck, FaCogs, FaShieldAlt, FaSyncAlt, FaSearch,
  FaDownload, FaUserShield, FaLayerGroup, FaProjectDiagram,
  FaLaptopCode, FaChartBar, FaQuestionCircle, FaArrowRight,
  FaBook, FaGithub, FaWrench, FaList, FaPlay
} = require("react-icons/fa");

// ─── Color Palette: Ocean/Midnight (SAP infrastructure feel) ───
const C = {
  midnight:   "21295C",  // dark navy - title slides
  deepBlue:   "065A82",  // primary - headers, accents
  teal:       "1C7293",  // secondary
  lightTeal:  "9DD1E1",  // soft accent
  iceBlue:    "E8F4F8",  // light bg
  white:      "FFFFFF",
  offWhite:   "F7FAFC",
  darkText:   "1A202C",
  bodyText:   "2D3748",
  mutedText:  "718096",
  green:      "38A169",
  red:        "E53E3E",
  orange:     "DD6B20",
  amber:      "D69E2E",
  codeBg:     "EDF2F7",
  cardBorder: "CBD5E0",
};

// ─── Fonts ───
const FONT_TITLE = "Georgia";
const FONT_BODY  = "Calibri";
const FONT_CODE  = "Consolas";

// ─── Helper: fresh shadow factory ───
const cardShadow = () => ({
  type: "outer", color: "000000", blur: 4, offset: 2, angle: 135, opacity: 0.10
});

// ─── Icon rendering ───
function renderIconSvg(IconComponent, color, size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

// ─── Slide builder helpers ───

// Dark section title slide (midnight bg)
function addSectionSlide(pres, title, subtitle, slideNum) {
  const slide = pres.addSlide();
  slide.background = { color: C.midnight };

  // Left accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.08, h: 5.625, fill: { color: C.teal }
  });

  // Section number circle
  if (slideNum) {
    slide.addShape(pres.shapes.OVAL, {
      x: 0.6, y: 1.8, w: 0.9, h: 0.9,
      fill: { color: C.teal }, line: { color: C.lightTeal, width: 2 }
    });
    slide.addText(String(slideNum), {
      x: 0.6, y: 1.8, w: 0.9, h: 0.9,
      fontSize: 28, fontFace: FONT_TITLE, color: C.white,
      align: "center", valign: "middle", bold: true
    });
  }

  slide.addText(title, {
    x: 1.8, y: 1.5, w: 7.5, h: 1.2,
    fontSize: 36, fontFace: FONT_TITLE, color: C.white, bold: true,
    valign: "middle", margin: 0
  });

  if (subtitle) {
    slide.addText(subtitle, {
      x: 1.8, y: 2.7, w: 7.5, h: 0.8,
      fontSize: 16, fontFace: FONT_BODY, color: C.lightTeal,
      valign: "top", margin: 0
    });
  }

  // Bottom bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.325, w: 10, h: 0.3, fill: { color: C.deepBlue }
  });

  return slide;
}

// Content slide with title (light bg)
function addContentSlide(pres, title) {
  const slide = pres.addSlide();
  slide.background = { color: C.offWhite };

  // Top header bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.85, fill: { color: C.deepBlue }
  });
  slide.addText(title, {
    x: 0.6, y: 0, w: 8.8, h: 0.85,
    fontSize: 22, fontFace: FONT_TITLE, color: C.white, bold: true,
    valign: "middle", margin: 0
  });

  // Bottom footer line
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.425, w: 10, h: 0.2, fill: { color: C.deepBlue }
  });
  slide.addText("SAP HANA Cluster Health Check - Training", {
    x: 0.5, y: 5.35, w: 6, h: 0.28,
    fontSize: 8, fontFace: FONT_BODY, color: C.mutedText, margin: 0
  });

  return slide;
}

// Code block
function addCodeBlock(slide, x, y, w, h, codeText) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h, fill: { color: C.codeBg },
    line: { color: C.cardBorder, width: 0.5 }
  });
  slide.addText(codeText, {
    x: x + 0.15, y: y + 0.08, w: w - 0.3, h: h - 0.16,
    fontSize: 11, fontFace: FONT_CODE, color: C.darkText,
    valign: "top", margin: 0, paraSpaceAfter: 2
  });
}

// Card with left accent
function addCard(slide, x, y, w, h, accentColor, contentArr) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h, fill: { color: C.white },
    shadow: cardShadow(),
    line: { color: C.cardBorder, width: 0.5 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h, fill: { color: accentColor }
  });
  if (contentArr) {
    slide.addText(contentArr, {
      x: x + 0.2, y: y + 0.08, w: w - 0.35, h: h - 0.16,
      fontSize: 13, fontFace: FONT_BODY, color: C.bodyText,
      valign: "top", margin: 0, paraSpaceAfter: 4
    });
  }
}

// ─── MAIN ───
let pres;

async function main() {
  pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "SAP HANA Cluster Health Check";
  pres.title = "SAP HANA Cluster Health Check - Introduction & Training";

  // Pre-render icons
  const icons = {};
  const iconDefs = [
    ["server", FaServer, C.deepBlue],
    ["network", FaNetworkWired, C.teal],
    ["database", FaDatabase, C.deepBlue],
    ["terminal", FaTerminal, C.deepBlue],
    ["file", FaFileAlt, C.teal],
    ["clipboard", FaClipboardCheck, C.green],
    ["cogs", FaCogs, C.teal],
    ["shield", FaShieldAlt, C.deepBlue],
    ["sync", FaSyncAlt, C.teal],
    ["search", FaSearch, C.deepBlue],
    ["download", FaDownload, C.teal],
    ["userShield", FaUserShield, C.deepBlue],
    ["layers", FaLayerGroup, C.teal],
    ["project", FaProjectDiagram, C.deepBlue],
    ["laptop", FaLaptopCode, C.teal],
    ["chart", FaChartBar, C.deepBlue],
    ["check", FaCheckCircle, C.green],
    ["cross", FaTimesCircle, C.red],
    ["warn", FaExclamationTriangle, C.orange],
    ["info", FaInfoCircle, C.teal],
    ["question", FaQuestionCircle, C.teal],
    ["arrow", FaArrowRight, C.deepBlue],
    ["book", FaBook, C.deepBlue],
    ["github", FaGithub, C.darkText],
    ["wrench", FaWrench, C.teal],
    ["list", FaList, C.deepBlue],
    ["play", FaPlay, C.green],
    ["checkWhite", FaCheckCircle, "#FFFFFF"],
    ["serverWhite", FaServer, "#FFFFFF"],
    ["searchWhite", FaSearch, "#FFFFFF"],
    ["chartWhite", FaChartBar, "#FFFFFF"],
    ["wrenchWhite", FaWrench, "#FFFFFF"],
    ["bookWhite", FaBook, "#FFFFFF"],
  ];
  for (const [name, comp, color] of iconDefs) {
    icons[name] = await iconToBase64Png(comp, color.startsWith("#") ? color : `#${color}`);
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 1: Title
  // ═══════════════════════════════════════════════════════════
  {
    const slide = pres.addSlide();
    slide.background = { color: C.midnight };

    // Left accent
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 0, w: 0.08, h: 5.625, fill: { color: C.teal }
    });

    // Title
    slide.addText("SAP HANA Cluster\nHealth Check", {
      x: 0.8, y: 0.8, w: 8.5, h: 2.2,
      fontSize: 44, fontFace: FONT_TITLE, color: C.white, bold: true,
      valign: "bottom", margin: 0
    });

    // Subtitle
    slide.addText("Introduction & Training", {
      x: 0.8, y: 3.1, w: 8.5, h: 0.7,
      fontSize: 24, fontFace: FONT_BODY, color: C.lightTeal,
      valign: "top", margin: 0
    });

    // Tagline
    slide.addText("Automated health checks for SAP HANA Pacemaker clusters on RHEL", {
      x: 0.8, y: 3.8, w: 8.5, h: 0.5,
      fontSize: 14, fontFace: FONT_BODY, color: C.mutedText,
      valign: "top", margin: 0
    });

    // Bottom bar with stats
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 4.8, w: 10, h: 0.825, fill: { color: C.deepBlue }
    });

    const stats = [
      { n: "22", label: "Health Checks" },
      { n: "3", label: "Access Methods" },
      { n: "5", label: "Check Steps" },
      { n: "PDF", label: "Auto Reports" },
    ];
    stats.forEach((s, i) => {
      const sx = 0.6 + i * 2.35;
      slide.addText(s.n, {
        x: sx, y: 4.85, w: 1.2, h: 0.4,
        fontSize: 24, fontFace: FONT_TITLE, color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      slide.addText(s.label, {
        x: sx + 1.15, y: 4.85, w: 1.2, h: 0.4,
        fontSize: 11, fontFace: FONT_BODY, color: C.lightTeal,
        align: "left", valign: "middle", margin: 0
      });
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 2: What Is It?
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "What Is It?");

    slide.addText("A comprehensive, automated health check tool for SAP HANA\nPacemaker clusters on Red Hat Enterprise Linux (RHEL 8/9/10).", {
      x: 0.6, y: 1.1, w: 8.8, h: 0.7,
      fontSize: 16, fontFace: FONT_BODY, color: C.darkText, italic: true,
      margin: 0
    });

    // 4 value prop cards in 2x2 grid
    const props = [
      { icon: "clipboard", title: "22 Automated Checks", desc: "Cluster config, Pacemaker, and SAP-specific validations" },
      { icon: "server", title: "Live & Offline", desc: "SSH to live clusters or analyze SOSreports offline" },
      { icon: "search", title: "Auto-Discovery", desc: "Discovers all cluster nodes from a single seed node" },
      { icon: "file", title: "PDF Reports", desc: "Auto-generated reports with standard or verbose detail" },
    ];

    for (let i = 0; i < 4; i++) {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const cx = 0.6 + col * 4.5;
      const cy = 2.1 + row * 1.55;

      addCard(slide, cx, cy, 4.2, 1.35, C.teal, null);

      slide.addImage({ data: icons[props[i].icon], x: cx + 0.2, y: cy + 0.3, w: 0.45, h: 0.45 });
      slide.addText(props[i].title, {
        x: cx + 0.8, y: cy + 0.15, w: 3.2, h: 0.4,
        fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true,
        margin: 0, valign: "middle"
      });
      slide.addText(props[i].desc, {
        x: cx + 0.8, y: cy + 0.55, w: 3.2, h: 0.6,
        fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "top"
      });
    }
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 3: Architecture Overview (5 Steps)
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Architecture Overview");

    slide.addText("The tool follows a 5-step pipeline from discovery to reporting:", {
      x: 0.6, y: 1.05, w: 8.8, h: 0.45,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    const steps = [
      { n: "1", title: "Access\nDiscovery", desc: "SSH, SOSreport,\nor local", color: C.deepBlue },
      { n: "2", title: "Cluster\nConfig", desc: "Nodes, quorum,\nclones, packages", color: C.teal },
      { n: "3", title: "Pacemaker\nChecks", desc: "STONITH, resources,\nfencing, roles", color: C.deepBlue },
      { n: "4", title: "SAP\nChecks", desc: "HANA SR, hooks,\nautostart, systemd", color: C.teal },
      { n: "5", title: "Report\nGeneration", desc: "YAML + PDF\nsummary", color: C.deepBlue },
    ];

    steps.forEach((s, i) => {
      const sx = 0.35 + i * 1.92;
      // Card bg
      slide.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: 1.7, w: 1.72, h: 3.2,
        fill: { color: C.white }, shadow: cardShadow(),
        line: { color: C.cardBorder, width: 0.5 }
      });
      // Top color strip
      slide.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: 1.7, w: 1.72, h: 0.06, fill: { color: s.color }
      });
      // Step number
      slide.addShape(pres.shapes.OVAL, {
        x: sx + 0.56, y: 1.95, w: 0.6, h: 0.6,
        fill: { color: s.color }
      });
      slide.addText(s.n, {
        x: sx + 0.56, y: 1.95, w: 0.6, h: 0.6,
        fontSize: 22, fontFace: FONT_TITLE, color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      // Title
      slide.addText(s.title, {
        x: sx + 0.1, y: 2.7, w: 1.52, h: 0.8,
        fontSize: 13, fontFace: FONT_BODY, color: C.deepBlue, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      // Description
      slide.addText(s.desc, {
        x: sx + 0.1, y: 3.55, w: 1.52, h: 0.8,
        fontSize: 11, fontFace: FONT_BODY, color: C.bodyText,
        align: "center", valign: "top", margin: 0
      });
      // Arrow between steps
      if (i < 4) {
        slide.addImage({
          data: icons.arrow, x: sx + 1.72, y: 2.95, w: 0.2, h: 0.2
        });
      }
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 4: Installation (Section divider first)
  // ═══════════════════════════════════════════════════════════
  addSectionSlide(pres, "Getting Started", "Installation, prerequisites, and first run", 1);

  // ═══════════════════════════════════════════════════════════
  // SLIDE 5: Installation
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Installation");

    // Option 1
    slide.addImage({ data: icons.terminal, x: 0.6, y: 1.15, w: 0.35, h: 0.35 });
    slide.addText("Option 1: Using git (recommended)", {
      x: 1.05, y: 1.15, w: 4, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0, valign: "middle"
    });
    addCodeBlock(slide, 0.6, 1.65, 4.2, 1.15,
      "git clone https://github.com/mmoster/\n  tool.sap_cluster_checks.git\ncd tool.sap_cluster_checks\n./cluster_health_check.py --local"
    );

    // Option 2
    slide.addImage({ data: icons.download, x: 0.6, y: 3.05, w: 0.35, h: 0.35 });
    slide.addText("Option 2: Download without git", {
      x: 1.05, y: 3.05, w: 4, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0, valign: "middle"
    });
    addCodeBlock(slide, 0.6, 3.55, 4.2, 1.0,
      "curl -L https://github.com/mmoster/\n  tool.sap_cluster_checks/archive/.../main.tar.gz \\\n  | tar xz\ncd tool.sap_cluster_checks-main"
    );

    // Right side: Prerequisites card
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 5.2, y: 1.15, w: 4.4, h: 3.8,
      fill: { color: C.white }, shadow: cardShadow(),
      line: { color: C.cardBorder, width: 0.5 }
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 5.2, y: 1.15, w: 4.4, h: 0.06, fill: { color: C.teal }
    });
    slide.addText("Prerequisites", {
      x: 5.4, y: 1.3, w: 4, h: 0.4,
      fontSize: 16, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    const prereqs = [
      { text: "Python 3.6+", sub: "Included in RHEL 8/9/10" },
      { text: "PyYAML", sub: "pip install pyyaml" },
      { text: "fpdf2 (optional)", sub: "pip install fpdf2 (for PDF reports)" },
      { text: "SSH access", sub: "For remote checks (key-based)" },
    ];
    prereqs.forEach((p, i) => {
      const py = 1.85 + i * 0.75;
      slide.addImage({ data: icons.check, x: 5.45, y: py + 0.05, w: 0.25, h: 0.25 });
      slide.addText(p.text, {
        x: 5.8, y: py, w: 3.5, h: 0.3,
        fontSize: 13, fontFace: FONT_BODY, color: C.darkText, bold: true, margin: 0
      });
      slide.addText(p.sub, {
        x: 5.8, y: py + 0.3, w: 3.5, h: 0.25,
        fontSize: 11, fontFace: FONT_BODY, color: C.mutedText, margin: 0
      });
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 6: First Run
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "First Run");

    slide.addText("Run locally on a cluster node to see immediate results:", {
      x: 0.6, y: 1.05, w: 8.8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    addCodeBlock(slide, 0.6, 1.55, 4.2, 0.55, "./cluster_health_check.py --local");

    slide.addText("Example output:", {
      x: 0.6, y: 2.3, w: 4.2, h: 0.3,
      fontSize: 13, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    // Output simulation card
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 2.7, w: 4.2, h: 2.3,
      fill: { color: "1A202C" }, line: { color: "4A5568", width: 1 }
    });
    slide.addText([
      { text: "Health Check Results:", options: { color: C.white, bold: true, breakLine: true } },
      { text: "  PASSED:  22  FAILED:  0  SKIPPED:  0", options: { color: C.green, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 6 } },
      { text: "  +=============================================+", options: { color: C.lightTeal, breakLine: true } },
      { text: "  |     CLUSTER IS HEALTHY                      |", options: { color: C.green, bold: true, breakLine: true } },
      { text: "  +=============================================+", options: { color: C.lightTeal, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 6 } },
      { text: "  PDF report saved: health_check_report.pdf", options: { color: C.mutedText } },
    ], {
      x: 0.8, y: 2.8, w: 3.8, h: 2.1,
      fontSize: 10, fontFace: FONT_CODE, valign: "top", margin: 0, paraSpaceAfter: 1
    });

    // Right side: what happens
    slide.addText("What happens on first run:", {
      x: 5.2, y: 1.05, w: 4.4, h: 0.4,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    const firstRunSteps = [
      "Discovers cluster nodes from Pacemaker",
      "Checks connectivity to all nodes",
      "Collects configuration data",
      "Runs all 22 health checks",
      "Generates summary + PDF report",
      "Caches config for future runs",
    ];
    slide.addText(firstRunSteps.map((s, i) => ({
      text: `${i + 1}. ${s}`,
      options: { breakLine: true, paraSpaceAfter: 6 }
    })), {
      x: 5.2, y: 1.55, w: 4.4, h: 3.5,
      fontSize: 13, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "top"
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 7: Section - Core Use Cases
  // ═══════════════════════════════════════════════════════════
  addSectionSlide(pres, "Core Use Cases", "Real-world scenarios and workflows", 2);

  // ═══════════════════════════════════════════════════════════
  // SLIDE 8: Use Case 1 - Routine Health Check
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 1: Routine Health Check");

    slide.addImage({ data: icons.clipboard, x: 0.6, y: 1.15, w: 0.4, h: 0.4 });
    slide.addText("Run on a live cluster node for a quick validation", {
      x: 1.1, y: 1.15, w: 8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, italic: true, margin: 0, valign: "middle"
    });

    // When to use
    addCard(slide, 0.6, 1.75, 4.2, 1.6, C.green, [
      { text: "When to use", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "Daily / weekly operational checks", options: { bullet: true, breakLine: true } },
      { text: "After routine maintenance", options: { bullet: true, breakLine: true } },
      { text: "Quick sanity check before changes", options: { bullet: true } },
    ]);

    // Command
    addCodeBlock(slide, 0.6, 3.6, 4.2, 0.5, "./cluster_health_check.py --local");

    // Right: what you get
    addCard(slide, 5.2, 1.75, 4.4, 2.35, C.teal, [
      { text: "What you get", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "Pass/fail summary for all 22 checks", options: { bullet: true, breakLine: true } },
      { text: "CRITICAL / WARNING / INFO severities", options: { bullet: true, breakLine: true } },
      { text: "Health status banner (HEALTHY / ISSUES)", options: { bullet: true, breakLine: true } },
      { text: "Auto-saved PDF report", options: { bullet: true, breakLine: true } },
      { text: "Cached config for faster re-runs", options: { bullet: true } },
    ]);

    slide.addText("Tip: First run caches cluster topology. Subsequent runs are faster.", {
      x: 5.2, y: 4.3, w: 4.4, h: 0.4,
      fontSize: 11, fontFace: FONT_BODY, color: C.mutedText, italic: true, margin: 0
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 9: Use Case 2 - Remote Cluster Check
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 2: Remote Cluster Check");

    slide.addImage({ data: icons.network, x: 0.6, y: 1.15, w: 0.4, h: 0.4 });
    slide.addText("Check clusters remotely via SSH - auto-discovers all members", {
      x: 1.1, y: 1.15, w: 8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, italic: true, margin: 0, valign: "middle"
    });

    // Two command options
    slide.addText("Option A: Specify nodes directly", {
      x: 0.6, y: 1.8, w: 4.2, h: 0.3,
      fontSize: 13, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });
    addCodeBlock(slide, 0.6, 2.15, 4.2, 0.45,
      "./cluster_health_check.py hana01 hana02"
    );

    slide.addText("Option B: Use a hosts file", {
      x: 0.6, y: 2.8, w: 4.2, h: 0.3,
      fontSize: 13, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });
    addCodeBlock(slide, 0.6, 3.15, 4.2, 0.45,
      "./cluster_health_check.py -H hosts.txt"
    );

    // Right: key points
    addCard(slide, 5.2, 1.8, 4.4, 2.8, C.deepBlue, [
      { text: "Key behaviors", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "Auto-discovers all cluster nodes from any seed node", options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: "Only one node needed - others found via Pacemaker config", options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: "Uses SSH key-based authentication", options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: "Parallel connectivity checks for speed", options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } },
      { text: "Multi-cluster: prompts if multiple clusters found", options: { bullet: true } },
    ]);

    slide.addText("Tip: Use --cluster NAME to select a specific cluster non-interactively.", {
      x: 0.6, y: 4.85, w: 9, h: 0.35,
      fontSize: 11, fontFace: FONT_BODY, color: C.mutedText, italic: true, margin: 0
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 10: Use Case 3 - Offline SOSreport Analysis
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 3: Offline SOSreport Analysis");

    slide.addImage({ data: icons.file, x: 0.6, y: 1.15, w: 0.4, h: 0.4 });
    slide.addText("Analyze SOSreports without SSH access - ideal for support & post-mortem", {
      x: 1.1, y: 1.15, w: 8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, italic: true, margin: 0, valign: "middle"
    });

    addCodeBlock(slide, 0.6, 1.8, 5.5, 0.45,
      "./cluster_health_check.py -s /path/to/sosreports/"
    );

    // Two cards: when and what
    addCard(slide, 0.6, 2.5, 4.2, 2.3, C.teal, [
      { text: "When to use", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "Support case analysis", options: { bullet: true, breakLine: true } },
      { text: "Post-mortem investigations", options: { bullet: true, breakLine: true } },
      { text: "No SSH access to the cluster", options: { bullet: true, breakLine: true } },
      { text: "Historical analysis of saved reports", options: { bullet: true, breakLine: true } },
      { text: "Training on real cluster data", options: { bullet: true } },
    ]);

    addCard(slide, 5.2, 2.5, 4.4, 2.3, C.deepBlue, [
      { text: "Supported formats", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: ".tar.xz archives (standard SOSreport)", options: { bullet: true, breakLine: true } },
      { text: ".tar.gz archives", options: { bullet: true, breakLine: true } },
      { text: "Pre-extracted directories", options: { bullet: true, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "Tool auto-extracts archives and maps data\nto the same checks as live analysis.", options: { italic: true, fontSize: 12, color: C.mutedText } },
    ]);
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 11: Use Case 4 - SOSreport Collection Workflow
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 4: SOSreport Collection Workflow");

    slide.addImage({ data: icons.download, x: 0.6, y: 1.15, w: 0.4, h: 0.4 });
    slide.addText("End-to-end: discover cluster, configure extensions, create & fetch SOSreports", {
      x: 1.1, y: 1.15, w: 8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, italic: true, margin: 0, valign: "middle"
    });

    addCodeBlock(slide, 0.6, 1.75, 8.8, 0.45,
      "./cluster_health_check.py -R hana01                    # full workflow"
    );
    addCodeBlock(slide, 0.6, 2.3, 8.8, 0.45,
      "./cluster_health_check.py -R hana01 --configure-extensions  # auto-configure"
    );

    // Workflow steps
    const wfSteps = [
      "Discovers cluster name and all nodes from the seed node",
      "Checks SSH access to all nodes (skips unreachable)",
      "Checks and optionally configures SAP SOSreport extensions",
      "Creates SOSreports in parallel with cluster label",
      "Fetches SOSreports via SCP to local ./sosreports/ directory",
    ];

    wfSteps.forEach((s, i) => {
      const sy = 3.0 + i * 0.45;
      slide.addShape(pres.shapes.OVAL, {
        x: 0.7, y: sy + 0.05, w: 0.3, h: 0.3,
        fill: { color: C.teal }
      });
      slide.addText(String(i + 1), {
        x: 0.7, y: sy + 0.05, w: 0.3, h: 0.3,
        fontSize: 12, fontFace: FONT_BODY, color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      slide.addText(s, {
        x: 1.15, y: sy, w: 8.2, h: 0.4,
        fontSize: 13, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "middle"
      });
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 12: Use Case 5 - Pre-Maintenance Validation
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 5: Pre-Maintenance Validation");

    slide.addImage({ data: icons.shield, x: 0.6, y: 1.15, w: 0.4, h: 0.4 });
    slide.addText("Run before and after maintenance windows to verify cluster state", {
      x: 1.1, y: 1.15, w: 8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, italic: true, margin: 0, valign: "middle"
    });

    // Before card
    addCard(slide, 0.6, 1.8, 4.2, 3.0, C.green, null);
    slide.addText("Before Maintenance", {
      x: 0.8, y: 1.9, w: 3.8, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });
    addCodeBlock(slide, 0.8, 2.35, 3.8, 0.5,
      "./cluster_health_check.py --local -v"
    );
    slide.addText([
      { text: "Establishes baseline state", options: { bullet: true, breakLine: true } },
      { text: "Verbose PDF captures all details", options: { bullet: true, breakLine: true } },
      { text: "Save as \"pre-maintenance\" reference", options: { bullet: true, breakLine: true } },
      { text: "Identify pre-existing issues", options: { bullet: true } },
    ], {
      x: 0.8, y: 3.0, w: 3.8, h: 1.6,
      fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "top"
    });

    // After card
    addCard(slide, 5.2, 1.8, 4.4, 3.0, C.teal, null);
    slide.addText("After Maintenance", {
      x: 5.4, y: 1.9, w: 4, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });
    addCodeBlock(slide, 5.4, 2.35, 4, 0.5,
      "./cluster_health_check.py --local -v"
    );
    slide.addText([
      { text: "Verify cluster recovered correctly", options: { bullet: true, breakLine: true } },
      { text: "Compare with pre-maintenance report", options: { bullet: true, breakLine: true } },
      { text: "Detect any regressions", options: { bullet: true, breakLine: true } },
      { text: "Document maintenance outcome", options: { bullet: true } },
    ], {
      x: 5.4, y: 3.0, w: 4, h: 1.6,
      fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "top"
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 13: Use Case 6 - Audit & Compliance
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 6: Audit & Compliance");

    slide.addImage({ data: icons.userShield, x: 0.6, y: 1.15, w: 0.4, h: 0.4 });
    slide.addText("Generate detailed PDF reports for compliance documentation", {
      x: 1.1, y: 1.15, w: 8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, italic: true, margin: 0, valign: "middle"
    });

    addCodeBlock(slide, 0.6, 1.8, 8.8, 0.45,
      "./cluster_health_check.py --local -v         # verbose PDF with all check details"
    );

    // What verbose includes
    addCard(slide, 0.6, 2.5, 4.2, 2.5, C.deepBlue, [
      { text: "Verbose PDF includes", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "All 22 checks with full details", options: { bullet: true, breakLine: true } },
      { text: "Cluster topology & configuration", options: { bullet: true, breakLine: true } },
      { text: "Node status and IP addresses", options: { bullet: true, breakLine: true } },
      { text: "System replication details", options: { bullet: true, breakLine: true } },
      { text: "STONITH/fencing configuration", options: { bullet: true, breakLine: true } },
      { text: "Package versions across nodes", options: { bullet: true } },
    ]);

    addCard(slide, 5.2, 2.5, 4.4, 2.5, C.green, [
      { text: "Use for", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "Internal compliance audits", options: { bullet: true, breakLine: true } },
      { text: "External auditor documentation", options: { bullet: true, breakLine: true } },
      { text: "Management reporting", options: { bullet: true, breakLine: true } },
      { text: "Change management evidence", options: { bullet: true, breakLine: true } },
      { text: "Support case attachments", options: { bullet: true, breakLine: true } },
      { text: "Historical comparison", options: { bullet: true } },
    ]);
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 14: Use Case 7 - Multi-Cluster + Use Case 8 - Interactive
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Use Case 7 & 8: Multi-Cluster & Interactive Mode");

    // Left: Multi-Cluster
    addCard(slide, 0.6, 1.15, 4.2, 3.8, C.deepBlue, null);
    slide.addImage({ data: icons.layers, x: 0.8, y: 1.3, w: 0.35, h: 0.35 });
    slide.addText("Multi-Cluster Management", {
      x: 1.25, y: 1.3, w: 3.3, h: 0.35,
      fontSize: 14, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0, valign: "middle"
    });
    addCodeBlock(slide, 0.8, 1.8, 3.8, 0.4,
      "./cluster_health_check.py -S"
    );
    addCodeBlock(slide, 0.8, 2.3, 3.8, 0.4,
      "./cluster_health_check.py -S hana01"
    );
    slide.addText([
      { text: "View all discovered cluster configs", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Filter by cluster name or node", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Prompts for selection when\nmultiple clusters are found", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Use -D to reset and re-discover", options: { bullet: true } },
    ], {
      x: 0.8, y: 2.85, w: 3.8, h: 1.9,
      fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "top"
    });

    // Right: Interactive
    addCard(slide, 5.2, 1.15, 4.4, 3.8, C.teal, null);
    slide.addImage({ data: icons.search, x: 5.4, y: 1.3, w: 0.35, h: 0.35 });
    slide.addText("Interactive / Exploratory Mode", {
      x: 5.85, y: 1.3, w: 3.5, h: 0.35,
      fontSize: 14, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0, valign: "middle"
    });
    addCodeBlock(slide, 5.4, 1.8, 4, 0.4,
      "./cluster_health_check.py -u"
    );
    slide.addText([
      { text: "Scans current directory for:", options: { breakLine: true, bold: true, paraSpaceAfter: 4 } },
      { text: "SOSreport archives (.tar.xz/.tar.gz)", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Hosts files (hosts.txt, inventory)", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Previous health check results (.yaml)", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "Presents interactive menu to choose\nwhat to analyze. Great for guided setup.", options: { italic: true, fontSize: 12, color: C.mutedText } },
    ], {
      x: 5.4, y: 2.35, w: 4, h: 2.4,
      fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "top"
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 15: Section - Understanding Results
  // ═══════════════════════════════════════════════════════════
  addSectionSlide(pres, "Understanding Results", "Reading output, severities, and reports", 3);

  // ═══════════════════════════════════════════════════════════
  // SLIDE 16: Reading the Output
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Reading the Output");

    // Healthy output
    slide.addText("Healthy Cluster", {
      x: 0.6, y: 1.1, w: 4.2, h: 0.3,
      fontSize: 14, fontFace: FONT_BODY, color: C.green, bold: true, margin: 0
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 1.5, w: 4.2, h: 1.8,
      fill: { color: "1A202C" }, line: { color: "4A5568", width: 1 }
    });
    slide.addText([
      { text: "Health Check Results:", options: { color: C.white, bold: true, breakLine: true } },
      { text: "  PASSED:  22  FAILED:  0", options: { color: C.green, breakLine: true } },
      { text: "  SKIPPED:  0  ERROR:   0", options: { color: C.green, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  CLUSTER IS HEALTHY", options: { color: C.green, bold: true } },
    ], {
      x: 0.75, y: 1.55, w: 3.9, h: 1.65,
      fontSize: 11, fontFace: FONT_CODE, valign: "top", margin: 0
    });

    // Failed output
    slide.addText("Issues Detected", {
      x: 5.2, y: 1.1, w: 4.4, h: 0.3,
      fontSize: 14, fontFace: FONT_BODY, color: C.red, bold: true, margin: 0
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 5.2, y: 1.5, w: 4.4, h: 1.8,
      fill: { color: "1A202C" }, line: { color: "4A5568", width: 1 }
    });
    slide.addText([
      { text: "Health Check Results:", options: { color: C.white, bold: true, breakLine: true } },
      { text: "  PASSED:  20  FAILED:  2", options: { color: C.red, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  X FAILED: CHK_STONITH_CONFIG", options: { color: C.red, bold: true, breakLine: true } },
      { text: "    STONITH is disabled", options: { color: C.orange } },
    ], {
      x: 5.35, y: 1.55, w: 4.1, h: 1.65,
      fontSize: 11, fontFace: FONT_CODE, valign: "top", margin: 0
    });

    // Result statuses
    slide.addText("Result Statuses", {
      x: 0.6, y: 3.65, w: 9, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    const statuses = [
      { label: "PASSED", color: C.green, desc: "Check completed successfully" },
      { label: "FAILED", color: C.red, desc: "Issue detected, action needed" },
      { label: "SKIPPED", color: "B7791F", desc: "Not applicable to this config" },
      { label: "ERROR", color: C.orange, desc: "Check could not complete" },
    ];
    statuses.forEach((s, i) => {
      const sx = 0.6 + i * 2.35;
      slide.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: 4.15, w: 2.15, h: 0.85,
        fill: { color: C.white }, shadow: cardShadow(),
        line: { color: C.cardBorder, width: 0.5 }
      });
      slide.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: 4.15, w: 2.15, h: 0.05, fill: { color: s.color }
      });
      slide.addText(s.label, {
        x: sx, y: 4.25, w: 2.15, h: 0.3,
        fontSize: 14, fontFace: FONT_CODE, color: s.color, bold: true,
        align: "center", margin: 0
      });
      slide.addText(s.desc, {
        x: sx + 0.1, y: 4.55, w: 1.95, h: 0.35,
        fontSize: 10, fontFace: FONT_BODY, color: C.mutedText,
        align: "center", margin: 0
      });
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 17: Check Severities
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Check Severities");

    slide.addText("Each health check has a severity level that determines its impact:", {
      x: 0.6, y: 1.1, w: 8.8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    const sevs = [
      {
        label: "CRITICAL", color: C.red, icon: "cross",
        desc: "Immediate action required. These checks identify issues that affect cluster availability or data integrity.",
        examples: "STONITH disabled, node offline, quorum lost, SR status incorrect"
      },
      {
        label: "WARNING", color: C.orange, icon: "warn",
        desc: "Should be addressed. These checks identify best practice violations or potential issues.",
        examples: "Package mismatch, cluster not fully started, resource failures detected"
      },
      {
        label: "INFO", color: C.teal, icon: "info",
        desc: "Informational. These checks provide context about cluster topology and configuration.",
        examples: "Cluster type detection, HANA installation status"
      },
    ];

    sevs.forEach((s, i) => {
      const sy = 1.7 + i * 1.2;
      addCard(slide, 0.6, sy, 8.8, 1.0, s.color, null);
      slide.addImage({ data: icons[s.icon], x: 0.85, y: sy + 0.15, w: 0.4, h: 0.4 });
      slide.addText(s.label, {
        x: 1.4, y: sy + 0.1, w: 1.8, h: 0.35,
        fontSize: 18, fontFace: FONT_BODY, color: s.color, bold: true, margin: 0, valign: "middle"
      });
      slide.addText(s.desc, {
        x: 3.2, y: sy + 0.05, w: 6, h: 0.4,
        fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "middle"
      });
      slide.addText("Examples: " + s.examples, {
        x: 3.2, y: sy + 0.5, w: 6, h: 0.35,
        fontSize: 11, fontFace: FONT_BODY, color: C.mutedText, italic: true, margin: 0, valign: "top"
      });
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 18: What the 22 Checks Cover (split: Cluster Config)
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Health Checks: Cluster Configuration (9)");

    // Helper for fresh opts (PptxGenJS mutates them)
    const hdr = () => ({ fill: { color: C.deepBlue }, color: C.white, bold: true, fontSize: 10, fontFace: FONT_BODY, align: "left", valign: "middle" });
    const cell = () => ({ fontSize: 10, fontFace: FONT_BODY, color: C.bodyText, valign: "middle" });
    const alt = () => ({ fontSize: 10, fontFace: FONT_BODY, color: C.bodyText, valign: "middle", fill: { color: C.iceBlue } });

    const configChecks = [
      [{ text: "Check ID", options: hdr() }, { text: "Severity", options: hdr() }, { text: "Description", options: hdr() }],
      [{ text: "CHK_CLUSTER_READY", options: cell() }, { text: "WARNING", options: cell() }, { text: "Check if cluster is fully started (not in transition)", options: cell() }],
      [{ text: "CHK_CLUSTER_TYPE", options: alt() }, { text: "INFO", options: alt() }, { text: "Detect Scale-Up vs Scale-Out configuration", options: alt() }],
      [{ text: "CHK_NODE_STATUS", options: cell() }, { text: "CRITICAL", options: cell() }, { text: "Verify all cluster nodes are online", options: cell() }],
      [{ text: "CHK_CLUSTER_QUORUM", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Verify cluster has quorum", options: alt() }],
      [{ text: "CHK_QUORUM_CONFIG", options: cell() }, { text: "CRITICAL", options: cell() }, { text: "Validate quorum configuration (Scale-Up)", options: cell() }],
      [{ text: "CHK_CLONE_CONFIG", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Validate clone resource configuration", options: alt() }],
      [{ text: "CHK_SETUP_VALIDATION", options: cell() }, { text: "CRITICAL", options: cell() }, { text: "Validate against SAP HANA HA best practices", options: cell() }],
      [{ text: "CHK_CIB_TIME_SYNC", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Verify CIB updates are synchronized", options: alt() }],
      [{ text: "CHK_PACKAGE_CONSISTENCY", options: cell() }, { text: "WARNING", options: cell() }, { text: "Verify package versions match across nodes", options: cell() }],
    ];
    slide.addTable(configChecks, {
      x: 0.5, y: 1.1, w: 9.0, colW: [2.3, 1.0, 5.7],
      border: { pt: 0.5, color: C.cardBorder },
      rowH: [0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32]
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 18b: Health Checks: Pacemaker + SAP
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Health Checks: Pacemaker (6) & SAP (7)");

    const hdr = () => ({ fill: { color: C.deepBlue }, color: C.white, bold: true, fontSize: 9, fontFace: FONT_BODY, align: "left", valign: "middle" });
    const cell = () => ({ fontSize: 9, fontFace: FONT_BODY, color: C.bodyText, valign: "middle" });
    const alt = () => ({ fontSize: 9, fontFace: FONT_BODY, color: C.bodyText, valign: "middle", fill: { color: C.iceBlue } });

    // Pacemaker section header
    slide.addText("Pacemaker/Corosync", {
      x: 0.5, y: 1.0, w: 4, h: 0.25,
      fontSize: 12, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    const pcmkChecks = [
      [{ text: "Check ID", options: hdr() }, { text: "Severity", options: hdr() }, { text: "Description", options: hdr() }],
      [{ text: "CHK_STONITH_CONFIG", options: cell() }, { text: "CRITICAL", options: cell() }, { text: "Verify STONITH/fencing is enabled", options: cell() }],
      [{ text: "CHK_RESOURCE_STATUS", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Verify SAP HANA resources are running", options: alt() }],
      [{ text: "CHK_RESOURCE_FAILURES", options: cell() }, { text: "WARNING", options: cell() }, { text: "Detect failed resource operations", options: cell() }],
      [{ text: "CHK_ALERT_FENCING", options: alt() }, { text: "WARNING", options: alt() }, { text: "Validate SAPHanaSR-alert-fencing", options: alt() }],
      [{ text: "CHK_MASTER_SLAVE_ROLES", options: cell() }, { text: "CRITICAL", options: cell() }, { text: "Verify master/slave role consistency", options: cell() }],
      [{ text: "CHK_MAJORITY_MAKER", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Validate majority maker constraints (Scale-Out)", options: alt() }],
    ];
    slide.addTable(pcmkChecks, {
      x: 0.5, y: 1.27, w: 9.0, colW: [2.3, 1.0, 5.7],
      border: { pt: 0.5, color: C.cardBorder },
      rowH: [0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25]
    });

    // SAP section header — Pacemaker table ends at 1.27 + 7*0.25 = 3.02
    slide.addText("SAP-Specific", {
      x: 0.5, y: 3.12, w: 4, h: 0.25,
      fontSize: 12, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    const sapChecks = [
      [{ text: "Check ID", options: hdr() }, { text: "Severity", options: hdr() }, { text: "Description", options: hdr() }],
      [{ text: "CHK_HANA_INSTALLED", options: cell() }, { text: "INFO", options: cell() }, { text: "Detect HANA installation, SID, instance, sidadm", options: cell() }],
      [{ text: "CHK_HANA_SR_STATUS", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Verify HANA System Replication status", options: alt() }],
      [{ text: "CHK_REPLICATION_MODE", options: cell() }, { text: "WARNING", options: cell() }, { text: "Verify replication mode is sync or syncmem", options: cell() }],
      [{ text: "CHK_HADR_HOOKS", options: alt() }, { text: "CRITICAL", options: alt() }, { text: "Validate HA/DR provider hooks", options: alt() }],
      [{ text: "CHK_HANA_AUTOSTART", options: cell() }, { text: "WARNING", options: cell() }, { text: "Validate HANA autostart is disabled", options: cell() }],
      [{ text: "CHK_SYSTEMD_SAP", options: alt() }, { text: "WARNING", options: alt() }, { text: "Validate SAP Host Agent and systemd config", options: alt() }],
      [{ text: "CHK_SITE_ROLES", options: cell() }, { text: "CRITICAL", options: cell() }, { text: "Verify site roles consistency", options: cell() }],
    ];
    // SAP table starts at 3.39, has 8 rows × 0.25 = 2.0, ends at 5.39 (footer at 5.425)
    slide.addTable(sapChecks, {
      x: 0.5, y: 3.39, w: 9.0, colW: [2.3, 1.0, 5.7],
      border: { pt: 0.5, color: C.cardBorder },
      rowH: [0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25]
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 19: PDF Reports
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "PDF Reports");

    // Standard vs Verbose
    addCard(slide, 0.6, 1.15, 4.2, 2.0, C.teal, null);
    slide.addText("Standard Report", {
      x: 0.8, y: 1.25, w: 3.8, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });
    addCodeBlock(slide, 0.8, 1.65, 3.8, 0.35,
      "./cluster_health_check.py --local"
    );
    slide.addText([
      { text: "Shows failed checks with details", options: { bullet: true, breakLine: true } },
      { text: "Summary pass/fail counts", options: { bullet: true, breakLine: true } },
      { text: "Compact and focused", options: { bullet: true } },
    ], {
      x: 0.8, y: 2.1, w: 3.8, h: 0.9,
      fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    addCard(slide, 5.2, 1.15, 4.4, 2.0, C.deepBlue, null);
    slide.addText("Verbose Report (-v)", {
      x: 5.4, y: 1.25, w: 4, h: 0.35,
      fontSize: 15, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });
    addCodeBlock(slide, 5.4, 1.65, 4, 0.35,
      "./cluster_health_check.py --local -v"
    );
    slide.addText([
      { text: "Shows ALL checks with full details", options: { bullet: true, breakLine: true } },
      { text: "Cluster configuration included", options: { bullet: true, breakLine: true } },
      { text: "Ideal for audits & documentation", options: { bullet: true } },
    ], {
      x: 5.4, y: 2.1, w: 4, h: 0.9,
      fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    // What's in the PDF
    slide.addText("What's included in every PDF:", {
      x: 0.6, y: 3.4, w: 9, h: 0.35,
      fontSize: 14, fontFace: FONT_BODY, color: C.deepBlue, bold: true, margin: 0
    });

    const pdfItems = [
      "Cluster name & timestamp",
      "Node list with status",
      "Check results table",
      "Health status banner",
      "RHEL & Pacemaker versions",
      "Report filename with cluster + time",
    ];
    pdfItems.forEach((item, i) => {
      const col = i % 3;
      const row = Math.floor(i / 3);
      const ix = 0.6 + col * 3.1;
      const iy = 3.9 + row * 0.5;
      slide.addImage({ data: icons.check, x: ix, y: iy + 0.02, w: 0.22, h: 0.22 });
      slide.addText(item, {
        x: ix + 0.3, y: iy, w: 2.7, h: 0.3,
        fontSize: 12, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "middle"
      });
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 20: Section - Practical Examples
  // ═══════════════════════════════════════════════════════════
  addSectionSlide(pres, "Practical Examples", "Real output walkthroughs and troubleshooting", 4);

  // ═══════════════════════════════════════════════════════════
  // SLIDE 21: Example - Healthy Cluster
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Example: Healthy Cluster Output");

    addCodeBlock(slide, 0.6, 1.1, 4.0, 0.4,
      "./cluster_health_check.py --local"
    );

    // Terminal output
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 1.7, w: 8.8, h: 3.2,
      fill: { color: "1A202C" }, line: { color: "4A5568", width: 1 }
    });
    slide.addText([
      { text: "$ ./cluster_health_check.py --local", options: { color: C.mutedText, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  Discovering cluster from local node...", options: { color: C.lightTeal, breakLine: true } },
      { text: "  Found cluster: production_hana (hana01, hana02)", options: { color: C.white, breakLine: true } },
      { text: "  RHEL 9.4 | Pacemaker 2.1.7 | ANGI (sap-hana-ha)", options: { color: C.mutedText, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  Running health checks...", options: { color: C.lightTeal, breakLine: true } },
      { text: "  Step 2: Cluster Configuration Check    [9/9 passed]", options: { color: C.green, breakLine: true } },
      { text: "  Step 3: Pacemaker/Corosync Check       [6/6 passed]", options: { color: C.green, breakLine: true } },
      { text: "  Step 4: SAP-Specific Checks            [7/7 passed]", options: { color: C.green, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  Health Check Results:", options: { color: C.white, bold: true, breakLine: true } },
      { text: "    PASSED:  22  FAILED:  0  SKIPPED:  0  ERROR:  0", options: { color: C.green, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "    +===============================================+", options: { color: C.lightTeal, breakLine: true } },
      { text: "    |        CLUSTER IS HEALTHY                     |", options: { color: C.green, bold: true, breakLine: true } },
      { text: "    +===============================================+", options: { color: C.lightTeal, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "    PDF report saved: health_check_report_production_hana_1507.pdf", options: { color: C.mutedText } },
    ], {
      x: 0.8, y: 1.75, w: 8.4, h: 3.1,
      fontSize: 9, fontFace: FONT_CODE, valign: "top", margin: 0, paraSpaceAfter: 0
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 22: Example - Failed Check
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Example: Failed Check (STONITH Disabled)");

    // Terminal output
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 1.1, w: 8.8, h: 2.2,
      fill: { color: "1A202C" }, line: { color: "4A5568", width: 1 }
    });
    slide.addText([
      { text: "  Health Check Results:", options: { color: C.white, bold: true, breakLine: true } },
      { text: "    PASSED:  20  FAILED:  2  SKIPPED:  0  ERROR:  0", options: { color: C.red, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  X FAILED: CHK_STONITH_CONFIG [CRITICAL]", options: { color: C.red, bold: true, breakLine: true } },
      { text: "    STONITH is disabled - fencing is required for production clusters", options: { color: C.orange, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  X FAILED: CHK_RESOURCE_FAILURES [WARNING]", options: { color: C.red, bold: true, breakLine: true } },
      { text: "    2 failed resource actions detected on hana01", options: { color: C.orange, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "    CLUSTER HAS ISSUES - REVIEW FAILED CHECKS", options: { color: C.red, bold: true } },
    ], {
      x: 0.8, y: 1.15, w: 8.4, h: 2.1,
      fontSize: 10, fontFace: FONT_CODE, valign: "top", margin: 0
    });

    // What to do cards
    addCard(slide, 0.6, 3.55, 4.2, 1.6, C.red, [
      { text: "Fix STONITH", options: { bold: true, fontSize: 14, color: C.red, breakLine: true } },
      { text: "1. Enable STONITH in cluster properties", options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: "2. Configure fencing device", options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: "3. Test with pcs stonith fence <node>", options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: "4. Re-run health check to verify", options: {} },
    ]);

    addCard(slide, 5.2, 3.55, 4.4, 1.6, C.orange, [
      { text: "Fix Resource Failures", options: { bold: true, fontSize: 14, color: C.orange, breakLine: true } },
      { text: "1. Check pcs status for details", options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: "2. Review /var/log/pacemaker.log", options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: "3. Clear failures: pcs resource cleanup", options: { breakLine: true, paraSpaceAfter: 4 } },
      { text: "4. Re-run health check to verify", options: {} },
    ]);
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 23: Example - Scale-Out Cluster
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Example: Scale-Out Cluster");

    slide.addText("Scale-Out clusters have additional topology-specific checks:", {
      x: 0.6, y: 1.1, w: 8.8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    // Scale-Up vs Scale-Out comparison
    addCard(slide, 0.6, 1.7, 4.2, 1.6, C.teal, [
      { text: "Scale-Up (typical)", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "2 HANA nodes", options: { bullet: true, breakLine: true } },
      { text: "SAPHana resource agent", options: { bullet: true, breakLine: true } },
      { text: "All 22 base checks apply", options: { bullet: true, breakLine: true } },
      { text: "CHK_QUORUM_CONFIG (Scale-Up only)", options: { bullet: true } },
    ]);

    addCard(slide, 5.2, 1.7, 4.4, 1.6, C.deepBlue, [
      { text: "Scale-Out", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "4+ HANA nodes + majority maker", options: { bullet: true, breakLine: true } },
      { text: "SAPHanaController resource agent", options: { bullet: true, breakLine: true } },
      { text: "CHK_MAJORITY_MAKER (Scale-Out only)", options: { bullet: true, breakLine: true } },
      { text: "Validates majority maker constraints", options: { bullet: true } },
    ]);

    // Topology-aware dispatch
    addCard(slide, 0.6, 3.55, 8.8, 1.5, C.teal, [
      { text: "Automatic Topology Detection", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "The tool detects cluster type via resource agent (SAPHana vs SAPHanaController)", options: { breakLine: true, paraSpaceAfter: 6 } },
      { text: "Checks are dispatched via check_dispatch.yaml - topology-specific checks auto-skip on wrong topology", options: { breakLine: true, paraSpaceAfter: 6 } },
      { text: "Additional cluster nodes (ASCS, ERS) are correctly identified and don't cause false failures", options: {} },
    ]);
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 24: Example - Cluster Not Running
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Example: Cluster Not Running");

    slide.addText("The tool gracefully handles clusters that aren't fully running:", {
      x: 0.6, y: 1.1, w: 8.8, h: 0.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.bodyText, margin: 0
    });

    // What happens
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 1.7, w: 8.8, h: 1.6,
      fill: { color: "1A202C" }, line: { color: "4A5568", width: 1 }
    });
    slide.addText([
      { text: "  Warning: Pacemaker/Corosync is not running on hana01", options: { color: C.orange, bold: true, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  Falling back to static configuration from corosync.conf", options: { color: C.lightTeal, breakLine: true } },
      { text: "  Discovered nodes: hana01, hana02 (from corosync.conf)", options: { color: C.white, breakLine: true } },
      { text: "", options: { breakLine: true, fontSize: 4 } },
      { text: "  Note: Some checks will be SKIPPED because they require", options: { color: C.mutedText, breakLine: true } },
      { text: "        a running cluster (e.g., resource status, SR status)", options: { color: C.mutedText } },
    ], {
      x: 0.8, y: 1.75, w: 8.4, h: 1.5,
      fontSize: 10, fontFace: FONT_CODE, valign: "top", margin: 0
    });

    addCard(slide, 0.6, 3.55, 8.8, 1.5, C.orange, [
      { text: "Graceful Degradation", options: { bold: true, fontSize: 14, color: C.deepBlue, breakLine: true } },
      { text: "Falls back to corosync.conf for node discovery when Pacemaker is down", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Checks that need a running cluster are automatically SKIPPED (not FAILED)", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Still runs all checks that can work with static configuration files", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
      { text: "Useful during planned downtime or when troubleshooting startup issues", options: { bullet: true } },
    ]);
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 25: Section - Tips & Advanced
  // ═══════════════════════════════════════════════════════════
  addSectionSlide(pres, "Tips & Advanced", "Options reference, troubleshooting, and next steps", 5);

  // ═══════════════════════════════════════════════════════════
  // SLIDE 26: Useful Options Quick Reference
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Useful Options Quick Reference");

    const hdrOpts = { fill: { color: C.deepBlue }, color: C.white, bold: true, fontSize: 11, fontFace: FONT_BODY, valign: "middle" };
    const cOpts = { fontSize: 10, fontFace: FONT_BODY, color: C.bodyText, valign: "middle" };
    const cAlt = { fontSize: 10, fontFace: FONT_BODY, color: C.bodyText, valign: "middle", fill: { color: C.iceBlue } };
    const cCode = { fontSize: 10, fontFace: FONT_CODE, color: C.deepBlue, valign: "middle", bold: true };
    const cCodeA = { fontSize: 10, fontFace: FONT_CODE, color: C.deepBlue, valign: "middle", bold: true, fill: { color: C.iceBlue } };

    const rows = [
      [{ text: "Option", options: hdrOpts }, { text: "Description", options: hdrOpts }, { text: "Example", options: hdrOpts }],
      [{ text: "--local", options: cCode }, { text: "Run on current cluster node", options: cOpts }, { text: "--local", options: cOpts }],
      [{ text: "-s DIR", options: cCodeA }, { text: "Analyze SOSreports in directory", options: cAlt }, { text: "-s ./sosreports/", options: cAlt }],
      [{ text: "-H FILE", options: cCode }, { text: "Read hosts from file", options: cOpts }, { text: "-H hosts.txt", options: cOpts }],
      [{ text: "-u", options: cCodeA }, { text: "Interactive mode - scan for resources", options: cAlt }, { text: "-u", options: cAlt }],
      [{ text: "-v", options: cCode }, { text: "Verbose PDF (all checks, full detail)", options: cOpts }, { text: "--local -v", options: cOpts }],
      [{ text: "-d", options: cCodeA }, { text: "Debug mode (verbose console output)", options: cAlt }, { text: "-d --local", options: cAlt }],
      [{ text: "-L", options: cCode }, { text: "List all available health checks", options: cOpts }, { text: "-L", options: cOpts }],
      [{ text: "-S", options: cCodeA }, { text: "Show discovered cluster config", options: cAlt }, { text: "-S my_cluster", options: cAlt }],
      [{ text: "-D", options: cCode }, { text: "Delete cached config, start fresh", options: cOpts }, { text: "-D", options: cOpts }],
      [{ text: "-f", options: cCodeA }, { text: "Force rediscovery (ignore cache)", options: cAlt }, { text: "-f --local", options: cAlt }],
      [{ text: "-R NODE", options: cCode }, { text: "Full SOSreport collection workflow", options: cOpts }, { text: "-R hana01", options: cOpts }],
      [{ text: "-F", options: cCodeA }, { text: "Fetch existing SOSreports from nodes", options: cAlt }, { text: "-F my_cluster", options: cAlt }],
      [{ text: "--no-pdf", options: cCode }, { text: "Skip PDF report generation", options: cOpts }, { text: "--no-pdf --local", options: cOpts }],
    ];

    slide.addTable(rows, {
      x: 0.5, y: 1.05, w: 9.0,
      colW: [1.3, 3.6, 2.0],
      border: { pt: 0.5, color: C.cardBorder },
      rowH: [0.3, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28]
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 27: Troubleshooting
  // ═══════════════════════════════════════════════════════════
  {
    const slide = addContentSlide(pres, "Troubleshooting");

    const issues = [
      {
        problem: "SSH connection fails",
        solution: "Verify key-based SSH access. Run: ssh -o BatchMode=yes <node> hostname",
        color: C.red
      },
      {
        problem: "PyYAML not found",
        solution: "Install: pip install pyyaml  or  dnf install python3-pyyaml",
        color: C.orange
      },
      {
        problem: "No PDF generated",
        solution: "Install fpdf2: pip install fpdf2  (optional dependency)",
        color: C.orange
      },
      {
        problem: "Cluster not detected",
        solution: "Pacemaker may not be running. Tool falls back to corosync.conf automatically",
        color: C.amber
      },
      {
        problem: "Stale cached config",
        solution: "Use -D to delete cache and -f to force rediscovery",
        color: C.amber
      },
      {
        problem: "Wrong cluster selected",
        solution: "Use --cluster NAME or -D to reset, then re-run to select correct cluster",
        color: C.teal
      },
    ];

    issues.forEach((issue, i) => {
      const iy = 1.05 + i * 0.62;
      addCard(slide, 0.6, iy, 8.8, 0.5, issue.color, null);
      slide.addText(issue.problem, {
        x: 0.85, y: iy + 0.03, w: 2.8, h: 0.44,
        fontSize: 12, fontFace: FONT_BODY, color: C.darkText, bold: true, margin: 0, valign: "middle"
      });
      slide.addText(issue.solution, {
        x: 3.7, y: iy + 0.03, w: 5.5, h: 0.44,
        fontSize: 11, fontFace: FONT_BODY, color: C.bodyText, margin: 0, valign: "middle"
      });
    });

    slide.addText("Tip: Use -d (debug mode) for verbose console output to diagnose any issues.", {
      x: 0.6, y: 4.85, w: 9, h: 0.3,
      fontSize: 11, fontFace: FONT_BODY, color: C.mutedText, italic: true, margin: 0
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SLIDE 28: Next Steps & Resources (closing slide)
  // ═══════════════════════════════════════════════════════════
  {
    const slide = pres.addSlide();
    slide.background = { color: C.midnight };

    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 0, w: 0.08, h: 5.625, fill: { color: C.teal }
    });

    slide.addText("Next Steps & Resources", {
      x: 0.8, y: 0.5, w: 8.5, h: 0.8,
      fontSize: 36, fontFace: FONT_TITLE, color: C.white, bold: true, margin: 0
    });

    // Resource cards
    const resources = [
      { icon: "bookWhite", title: "Full Documentation", desc: "README.md - Complete reference guide", link: "github.com/mmoster/tool.sap_cluster_checks" },
      { icon: "wrenchWhite", title: "Extend the Tool", desc: "EXTENDING_HEALTH_CHECKS.md - Create custom rules", link: "docs/EXTENDING_HEALTH_CHECKS.md" },
      { icon: "chartWhite", title: "Quick Start Guide", desc: "BLOG_HOWTO.md - Step-by-step examples", link: "docs/BLOG_HOWTO.md" },
    ];

    resources.forEach((r, i) => {
      const ry = 1.6 + i * 1.1;
      slide.addShape(pres.shapes.RECTANGLE, {
        x: 0.8, y: ry, w: 8.4, h: 0.9,
        fill: { color: C.deepBlue },
        line: { color: C.teal, width: 1 }
      });
      slide.addImage({ data: icons[r.icon], x: 1.0, y: ry + 0.2, w: 0.45, h: 0.45 });
      slide.addText(r.title, {
        x: 1.65, y: ry + 0.08, w: 4, h: 0.35,
        fontSize: 16, fontFace: FONT_BODY, color: C.white, bold: true, margin: 0
      });
      slide.addText(r.desc, {
        x: 1.65, y: ry + 0.45, w: 4, h: 0.3,
        fontSize: 12, fontFace: FONT_BODY, color: C.lightTeal, margin: 0
      });
      slide.addText(r.link, {
        x: 6.0, y: ry + 0.08, w: 3, h: 0.7,
        fontSize: 10, fontFace: FONT_CODE, color: C.mutedText, margin: 0, valign: "middle"
      });
    });

    // Quick start reminder
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.8, y: 4.55, w: 8.4, h: 0.7,
      fill: { color: C.teal }
    });
    slide.addText("Get started now:", {
      x: 1.0, y: 4.55, w: 2.0, h: 0.7,
      fontSize: 16, fontFace: FONT_BODY, color: C.white, bold: true, margin: 0, valign: "middle"
    });
    slide.addText("git clone https://github.com/mmoster/tool.sap_cluster_checks.git && cd tool.sap_cluster_checks && ./cluster_health_check.py --local", {
      x: 3.0, y: 4.55, w: 6.0, h: 0.7,
      fontSize: 11, fontFace: FONT_CODE, color: C.white, margin: 0, valign: "middle"
    });
  }

  // ─── Write file ───
  const outPath = "/home/mmoster/projects/SAP_cluster_health_check/docs/SAP_Cluster_Health_Check_Training.pptx";
  await pres.writeFile({ fileName: outPath });
  console.log(`Presentation saved to: ${outPath}`);
  console.log(`Total slides: ${pres.slides.length}`);
}

main().catch(err => { console.error(err); process.exit(1); });
