"""Generate 4-slide deck: About, Problem, Solution, Key Features."""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

prs = Presentation()
prs.slide_width  = Inches(13.33)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]

# ── Palette ──────────────────────────────────────────────────────────────────
BLUE    = RGBColor(0x00, 0x6D, 0xD7)
TEAL    = RGBColor(0x07, 0x89, 0x87)
GOLD    = RGBColor(0xF0, 0xAB, 0x00)
GREEN   = RGBColor(0x18, 0x8F, 0x30)
DARK    = RGBColor(0x1A, 0x1A, 0x2E)
MID     = RGBColor(0x55, 0x60, 0x6E)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
LGREY   = RGBColor(0xF4, 0xF5, 0xF7)
DKBLUE  = RGBColor(0x00, 0x2B, 0x5C)

def solid(shape, rgb):
    shape.fill.solid(); shape.fill.fore_color.rgb = rgb

def noborder(shape):
    shape.line.fill.background()

def rect(slide, l, t, w, h, fill=None, line=None, lw=Pt(0)):
    s = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
    if fill: solid(s, fill)
    else: s.fill.background()
    if line: s.line.color.rgb = line; s.line.width = lw
    else: noborder(s)
    return s

def txt(slide, text, l, t, w, h, bold=False, size=Pt(13),
        color=DARK, align=PP_ALIGN.LEFT, wrap=True, italic=False):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = wrap
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text
    r.font.bold = bold; r.font.size = size
    r.font.color.rgb = color; r.font.italic = italic
    return tb

def header(slide, title, subtitle=None, bg=BLUE):
    rect(slide, 0, 0, 13.33, 7.5, LGREY)
    rect(slide, 0, 0, 13.33, 1.4, bg)
    rect(slide, 0, 1.4, 13.33, 0.07, TEAL)
    txt(slide, title, 0.45, 0.18, 12.4, 0.75,
        bold=True, size=Pt(30), color=WHITE)
    if subtitle:
        txt(slide, subtitle, 0.45, 0.88, 12.0, 0.42,
            size=Pt(13), color=RGBColor(0xCC, 0xE4, 0xFF))

def footer(slide, note="FGF Brands · D4H-200 · SAP EWM Warehouse AI Agent"):
    rect(slide, 0, 7.1, 13.33, 0.4, RGBColor(0xE4, 0xEC, 0xF8))
    txt(slide, note, 0.35, 7.14, 12.6, 0.3,
        size=Pt(9), color=MID)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — ABOUT
# ══════════════════════════════════════════════════════════════════════════════
s = prs.slides.add_slide(BLANK)
solid(s.background, DKBLUE)
rect(s, 0, 0, 0.22, 7.5, TEAL)
rect(s, 0, 5.6, 13.33, 1.9, RGBColor(0x00, 0x1F, 0x4A))
rect(s, 0, 5.52, 13.33, 0.12, GOLD)

txt(s, "SAP EWM", 0.55, 0.9, 12.0, 0.85,
    bold=True, size=Pt(44), color=GOLD)
txt(s, "Warehouse AI Agent", 0.55, 1.7, 12.0, 0.85,
    bold=True, size=Pt(44), color=WHITE)
txt(s, "Conversational AI for SAP S/4HANA Extended Warehouse Management",
    0.55, 2.65, 11.5, 0.55, size=Pt(18), color=RGBColor(0xAA, 0xCC, 0xFF))
txt(s, "13 Skills  ·  47 Tools  ·  18 SAP API Surfaces  ·  LangGraph + GPT-4.1  ·  A2A JSON-RPC 2.0",
    0.55, 3.25, 11.5, 0.45, size=Pt(13.5), color=RGBColor(0x88, 0xAA, 0xDD))

# Stat chips
chips = [
    ("13",  "Skills",      BLUE),
    ("47",  "Tools",       TEAL),
    ("18",  "API Surfaces",GOLD),
    ("3",   "Interfaces",  GREEN),
]
for i, (n, l, c) in enumerate(chips):
    cx = 0.55 + i * 3.0
    rect(s, cx, 4.1, 2.6, 1.05, c)
    txt(s, n, cx+0.08, 4.18, 2.44, 0.58,
        bold=True, size=Pt(34), color=WHITE, align=PP_ALIGN.CENTER)
    txt(s, l, cx+0.08, 4.75, 2.44, 0.32,
        size=Pt(11.5), color=WHITE, align=PP_ALIGN.CENTER)

txt(s, "FGF Brands — D4H-200  ·  Warehouse PBAR  ·  Plant BAR1  ·  Cloud Foundry (BTP us10-001)",
    0.55, 5.72, 12.2, 0.35, size=Pt(10.5), color=RGBColor(0x88, 0xAA, 0xDD))
txt(s, "Interfaces: Browser Chat UI  ·  Desktop Floating Widget  ·  SAP Joule Desktop (MCP)",
    0.55, 6.1, 12.2, 0.35, size=Pt(10.5), color=RGBColor(0x88, 0xAA, 0xDD))

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — PROBLEM
# ══════════════════════════════════════════════════════════════════════════════
s = prs.slides.add_slide(BLANK)
header(s, "The Problem",
       "Warehouse operators spend too much time navigating SAP — and still can't do everything",
       RGBColor(0xBB, 0x22, 0x00))
rect(s, 0, 1.47, 13.33, 0.07, GOLD)
footer(s)

problems = [
    ("⏱", "Too Many Screens",
     "A single stock check, inbound delivery review, or task confirmation requires navigating 3–5 "
     "SAP transactions. Warehouse supervisors lose hours per day switching between EWM, MM, and PP views."),
    ("🔒", "Write Operations Locked Away",
     "Standard SAP interfaces require deep transaction knowledge to post a GR, confirm a task, or "
     "execute an STO. One wrong entry can cause stock discrepancies — so operators escalate to supervisors."),
    ("📦", "No HU-Level GR in Standard APIs",
     "SAP's released OData APIs can only post GR for a full delivery or per-item quantities — there is "
     "no standard way to receive just 2 of 10 handling units on a delivery line. This forces manual workarounds."),
    ("🔌", "Disconnected Touchpoints",
     "Warehouse staff use SAP GUI, Fiori, mobile scanners, and Joule — but none share context. There is "
     "no single conversational interface that spans stock, tasks, deliveries, production, and write operations."),
]

for i, (icon, title, body) in enumerate(problems):
    col, row = i % 2, i // 2
    px = 0.35 + col * 6.45
    py = 1.72 + row * 2.5
    rect(s, px, py, 6.2, 2.32, WHITE, line=RGBColor(0xBB,0x22,0x00), lw=Pt(1.2))
    rect(s, px, py, 6.2, 0.44, RGBColor(0xBB, 0x22, 0x00))
    txt(s, f"{icon}  {title}", px+0.14, py+0.08, 5.9, 0.32,
        bold=True, size=Pt(11), color=WHITE)
    txt(s, body, px+0.14, py+0.52, 5.92, 1.68,
        size=Pt(9.5), color=MID)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — SOLUTION
# ══════════════════════════════════════════════════════════════════════════════
s = prs.slides.add_slide(BLANK)
header(s, "The Solution",
       "One conversational AI agent — plain English in, SAP actions out", GREEN)
rect(s, 0, 1.47, 13.33, 0.07, TEAL)
footer(s)

# Architecture flow
flow = [
    ("👤\nUser", RGBColor(0x33,0x55,0x99)),
    ("💬\nChat / Widget\n/ Joule", BLUE),
    ("🧠\nLangGraph\nAgent", TEAL),
    ("🔧\n47 SAP\nTools", GREEN),
    ("🏭\nSAP EWM\nD4H-200", RGBColor(0x55,0x00,0x88)),
]
bw, bh, gap = 1.85, 1.55, 0.28
total = len(flow) * bw + (len(flow)-1) * gap
sx = (13.33 - total) / 2
for i, (lbl, clr) in enumerate(flow):
    bx = sx + i * (bw + gap)
    rect(s, bx, 1.68, bw, bh, clr)
    txt(s, lbl, bx+0.06, 1.75, bw-0.1, bh-0.1,
        bold=True, size=Pt(10), color=WHITE, align=PP_ALIGN.CENTER)
    if i < len(flow)-1:
        ax = bx + bw + 0.03
        txt(s, "→", ax, 2.1, gap+0.05, 0.6,
            bold=True, size=Pt(18), color=BLUE, align=PP_ALIGN.CENTER)

# Solution points
solutions = [
    ("🗣 Plain English Interface",
     "Ask in natural language — \"Post GR for HU P21234\" or \"Show stock for 1111044 in PBAR\". "
     "The LangGraph reasoning loop selects the right tool, calls SAP, and returns the answer."),
    ("✅ Safe Write Operations",
     "Every write — task confirmation, GR posting, STO execution — is gated by a single "
     "confirmation block. SAP errors are relayed verbatim. A test-run mode validates without posting."),
    ("📦 HU-Level GR (Custom FM)",
     "Custom ABAP FM Z_EWM_GR_HU_POST3 fills the gap the standard OData API leaves: "
     "post GR for specific handling units only, leaving others open on the same delivery line."),
    ("🔌 Three Access Points",
     "Browser chat UI, Windows floating desktop widget (Ctrl+Shift+J over SAP GUI), "
     "and SAP Joule Desktop via MCP HTTP proxy — same backend, same 47 tools everywhere."),
]

for i, (title, body) in enumerate(solutions):
    col, row = i % 2, i // 2
    sx2 = 0.35 + col * 6.45
    sy2 = 3.45 + row * 1.68
    rect(s, sx2, sy2, 6.2, 1.55, WHITE, line=GREEN, lw=Pt(1.2))
    rect(s, sx2, sy2, 0.1, 1.55, GREEN)
    txt(s, title, sx2+0.22, sy2+0.1, 5.85, 0.35,
        bold=True, size=Pt(10.5), color=GREEN)
    txt(s, body, sx2+0.22, sy2+0.46, 5.85, 0.98,
        size=Pt(9.5), color=MID)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — KEY FEATURES
# ══════════════════════════════════════════════════════════════════════════════
s = prs.slides.add_slide(BLANK)
header(s, "Key Features", "13 skills · 47 tools · 18 SAP API surfaces")
footer(s)

features = [
    (BLUE,  "📦 Stock — 3 Skills",
     ["MM plant/SLoc/batch stock (OData V2)",
      "EWM bin-level available + physical stock",
      "Cross-warehouse stock — all 34 warehouses"]),
    (TEAL,  "🚚 Inbound & Outbound — 2 Skills",
     ["Inbound delivery headers, items, doc flow",
      "EWM outbound delivery orders",
      "GR: full / partial / HU-level (custom FM)"]),
    (GREEN, "✅ Write Operations — 4 Skills",
     ["EWM task confirmation with qty + bin",
      "HU-level GR via Z_EWM_GR_HU_POST3",
      "STO one-shot: create + GI 351 + GR 101",
      "GR mvt 101 for inbound delivery"]),
    (RGBColor(0x6E,0x00,0x9E), "🏗 Production — 2 Skills",
     ["Order status, BOM components, routing",
      "GI for production + confirmation + GR",
      "BAPI + OData V2 (dual path)"]),
    (GOLD,  "🏭 EWM Master — 3 Skills",
     ["Storage bins + fixed assignments",
      "Physical inventory docs + count items",
      "Warehouses, storage types, resources"]),
    (RGBColor(0xC0,0x53,0x00), "🔌 3 Access Interfaces",
     ["Browser chat UI (Cloud Foundry)",
      "Desktop widget — Ctrl+Shift+J (tkinter)",
      "SAP Joule Desktop — MCP HTTP proxy"]),
]

cw, ch, cgap = 3.95, 2.55, 0.2
for i, (clr, title, bullets) in enumerate(features):
    col, row = i % 3, i // 3
    fx = 0.28 + col * (cw + cgap)
    fy = 1.58 + row * (ch + 0.18)
    rect(s, fx, fy, cw, ch, WHITE, line=clr, lw=Pt(1.2))
    rect(s, fx, fy, cw, 0.42, clr)
    txt(s, title, fx+0.14, fy+0.08, cw-0.2, 0.3,
        bold=True, size=Pt(10.5), color=WHITE)
    for bi, b in enumerate(bullets):
        by = fy + 0.54 + bi * 0.52
        rect(s, fx+0.14, by+0.12, 0.08, 0.08, clr)
        txt(s, b, fx+0.3, by, cw-0.42, 0.48,
            size=Pt(9.5), color=DARK)

# ── Save ─────────────────────────────────────────────────────────────────────
out = r"c:\mydata\JD\Joulewarehouse\EWM_Agent_4Slides.pptx"
prs.save(out)
print(f"Saved: {out}")
