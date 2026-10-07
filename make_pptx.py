"""Generate warehouse-agent-deck.pptx — 10-slide SAP Horizon styled deck."""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import pptx.oxml.ns as nsmap
from lxml import etree

# --------------- colour palette ---------------
BLUE   = RGBColor(0x00, 0x70, 0xF2)
NAVY   = RGBColor(0x1D, 0x2D, 0x3E)
DARK   = RGBColor(0x32, 0x36, 0x3A)
MED    = RGBColor(0x6A, 0x6D, 0x70)
LIGHT  = RGBColor(0x89, 0x91, 0x9A)
BG     = RGBColor(0xF5, 0xF6, 0xF7)
GREEN  = RGBColor(0x10, 0x7E, 0x3E)
ORANGE = RGBColor(0xE7, 0x65, 0x00)
TEAL   = RGBColor(0x00, 0x62, 0x7F)
PURPLE = RGBColor(0x6E, 0x33, 0xB0)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LBLUE  = RGBColor(0x00, 0x40, 0xB0)
GOLD   = RGBColor(0xC8, 0x7B, 0x00)

W = Inches(13.33)
H = Inches(7.5)

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H

blank = prs.slide_layouts[6]   # completely blank

# ==================== helpers ====================

def add_slide():
    return prs.slides.add_slide(blank)

def rect(slide, x, y, w, h, fill=None, line=None):
    """Add a filled rectangle shape."""
    shape = slide.shapes.add_shape(1, x, y, w, h)  # MSO_SHAPE_TYPE.RECTANGLE=1
    shape.line.fill.background()
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    else:
        shape.fill.background()
    if line:
        shape.line.color.rgb = line
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    return shape

def txbox(slide, text, x, y, w, h, size=12, bold=False, color=DARK,
          align=PP_ALIGN.LEFT, wrap=True, italic=False):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return tb

def para(tf, text, size=11, bold=False, color=DARK, align=PP_ALIGN.LEFT, italic=False, space_before=0):
    p = tf.add_paragraph()
    p.alignment = align
    if space_before:
        p.space_before = Pt(space_before)
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return p

def header_bar(slide, title, subtitle="", tag=""):
    rect(slide, 0, 0, W, Inches(1.1), fill=NAVY)
    txbox(slide, title, Inches(0.5), Inches(0.1), Inches(9), Inches(0.55),
          size=22, bold=True, color=WHITE)
    if subtitle:
        txbox(slide, subtitle, Inches(0.5), Inches(0.65), Inches(9), Inches(0.35),
              size=10, color=RGBColor(0xBB, 0xCC, 0xDD), italic=True)
    if tag:
        txbox(slide, tag, Inches(10), Inches(0.35), Inches(3), Inches(0.4),
              size=9, bold=True, color=RGBColor(0x89, 0x91, 0x9A), align=PP_ALIGN.RIGHT)

def footer_bar(slide, left="FGF Brands — D4H-200", right="Warehouse AI Agent · SAP S/4HANA EWM"):
    rect(slide, 0, Inches(7.15), W, Inches(0.35), fill=BG)
    txbox(slide, left,  Inches(0.5), Inches(7.17), Inches(6), Inches(0.28), size=9, color=LIGHT)
    txbox(slide, right, Inches(7),   Inches(7.17), Inches(6), Inches(0.28), size=9, color=LIGHT, align=PP_ALIGN.RIGHT)

def card(slide, x, y, w, h, title, body, accent=BLUE, bg=BG, title_sz=11, body_sz=10):
    rect(slide, x, y, w, h, fill=bg, line=RGBColor(0xE0,0xE0,0xE0))
    # accent left bar
    rect(slide, x, y, Inches(0.06), h, fill=accent)
    tb = slide.shapes.add_textbox(x + Inches(0.12), y + Inches(0.1), w - Inches(0.18), Inches(0.3))
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; run = p.add_run()
    run.text = title; run.font.size = Pt(title_sz); run.font.bold = True; run.font.color.rgb = DARK
    tb2 = slide.shapes.add_textbox(x + Inches(0.12), y + Inches(0.38), w - Inches(0.18), h - Inches(0.45))
    tf2 = tb2.text_frame; tf2.word_wrap = True
    p2 = tf2.paragraphs[0]; run2 = p2.add_run()
    run2.text = body; run2.font.size = Pt(body_sz); run2.font.color.rgb = MED

def kpi(slide, x, y, w, h, number, label):
    rect(slide, x, y, w, h, fill=NAVY)
    txbox(slide, number, x, y + Inches(0.25), w, Inches(0.7), size=34, bold=True,
          color=RGBColor(0x7E, 0xC8, 0xE3), align=PP_ALIGN.CENTER)
    txbox(slide, label, x, y + Inches(0.95), w, Inches(0.35), size=9, bold=True,
          color=RGBColor(0xAA, 0xBB, 0xCC), align=PP_ALIGN.CENTER)

# ==================== SLIDE 1 — TITLE ====================
sl = add_slide()
# gradient bg via two rects
rect(sl, 0, 0, W, H, fill=RGBColor(0x0D, 0x1B, 0x2E))
rect(sl, Inches(3), 0, W - Inches(3), H, fill=RGBColor(0x00, 0x40, 0xB0))

# SAP logo text top-right
txbox(sl, "SAP", Inches(11.5), Inches(0.2), Inches(1.5), Inches(0.6),
      size=28, bold=True, color=WHITE, align=PP_ALIGN.RIGHT)

# badge
txbox(sl, "BTP  ·  A2A  ·  LangGraph  ·  AI Core  ·  EWM",
      Inches(0.8), Inches(1.2), Inches(8), Inches(0.4), size=11,
      color=RGBColor(0x7E, 0xC8, 0xE3))

# main title
txbox(sl, "Warehouse AI Agent", Inches(0.8), Inches(1.7), Inches(10), Inches(1.1),
      size=48, bold=True, color=WHITE)

# subtitle
txbox(sl, "Conversational Intelligence for SAP S/4HANA EWM\nFrom Stock Queries to Goods Movements — in Natural Language",
      Inches(0.8), Inches(2.85), Inches(10), Inches(0.85), size=16,
      color=RGBColor(0xCC, 0xDD, 0xEE))

# deployment chips
for i, txt in enumerate(["FGF Brands — D4H-200", "PBAR Warehouse · BAR1 Plant", "GPT-4.1 via SAP AI Core"]):
    cx = Inches(0.8) + i * Inches(3.6)
    rect(sl, cx, Inches(3.85), Inches(3.3), Inches(0.35), fill=RGBColor(0x00, 0x35, 0x80))
    txbox(sl, "● " + txt, cx + Inches(0.1), Inches(3.88), Inches(3.1), Inches(0.3),
          size=10, color=RGBColor(0xCC, 0xEE, 0xFF))

# stats row
stats = [("13", "AI Skills"), ("48", "SAP Tools"), ("4", "Tenants Live"), ("A2A", "Agent Protocol")]
for i, (num, lbl) in enumerate(stats):
    sx = Inches(0.8) + i * Inches(2.9)
    txbox(sl, num, sx, Inches(4.55), Inches(2.6), Inches(0.9),
          size=40, bold=True, color=RGBColor(0x7E, 0xC8, 0xE3))
    txbox(sl, lbl, sx, Inches(5.4), Inches(2.6), Inches(0.4),
          size=11, color=RGBColor(0x88, 0x99, 0xAA))

# presenter / date
txbox(sl, "FGF Brands Primary Deployment  |  2026", Inches(0.8), Inches(6.7), Inches(8), Inches(0.4),
      size=11, color=RGBColor(0x88, 0x99, 0xAA))

# ==================== SLIDE 2 — PROBLEM ====================
sl = add_slide()
header_bar(sl, "The Warehouse Operations Challenge",
           "Data lives in SAP — but insight requires navigation, not conversation",
           "SAP EWM · S/4HANA")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

problems = [
    ("Transaction-Driven Operations",
     "Staff navigate 10+ SAP transactions (LT01, MB51, MIGO, LI01…) to answer basic questions every time."),
    ("No Cross-Domain Visibility",
     "EWM bin stock, MM inventory, production orders, and deliveries have no unified conversational view."),
    ("Manual, Time-Consuming Actions",
     "Goods receipts, task confirmations, and stock transfers require SAPGUI and multiple form steps."),
    ("No Lightweight Interface",
     "Shop floor workers cannot query bin stock or confirm tasks without full SAP GUI on a desktop."),
    ("Joule EWM Coverage Gap",
     "SAP Joule lacks deep EWM — bin stock, task management, HU-level GR, and goods movement are absent."),
    ("AI Projects Take Too Long",
     "Traditional AI for warehouse ops takes 8–12 months and rare SAP + ML specialists. No reuse."),
]
cols, rows = 3, 2
cw = Inches(4.1); ch = Inches(2.4)
gx = Inches(0.3); gy = Inches(1.25)
gap = Inches(0.17)
for i, (t, b) in enumerate(problems):
    col = i % cols; row = i // cols
    x = gx + col * (cw + gap)
    y = gy + row * (ch + gap)
    card(sl, x, y, cw, ch, t, b, accent=ORANGE)

footer_bar(sl)

# ==================== SLIDE 3 — ARCHITECTURE ====================
sl = add_slide()
header_bar(sl, "Solution Architecture",
           "Natural language → SAP actions via A2A + LangGraph + AI Core on SAP BTP",
           "CLOUD FOUNDRY · BTP")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

# top flow row
flow_top = [
    (BLUE,   "Chat UI / Joule",      "Browser · Desktop · MCP"),
    (NAVY,   "warehouse-agent-ui",   "Node/Express · Static HTML"),
    (BLUE,   "warehouse-agent",      "Python A2A · JSON-RPC 2.0"),
    (TEAL,   "LangGraph",            "Agentic Loop · Tool Dispatch"),
    (NAVY,   "SAP AI Core",          "GPT-4.1 · Orchestration"),
]
bw = Inches(2.1); bh = Inches(0.85); by = Inches(1.3)
bx_start = Inches(0.35)
for i, (col, title, sub) in enumerate(flow_top):
    bx = bx_start + i * Inches(2.6)
    rect(sl, bx, by, bw, bh, fill=col)
    txbox(sl, title, bx, by + Inches(0.12), bw, Inches(0.35), size=10, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    txbox(sl, sub,   bx, by + Inches(0.48), bw, Inches(0.3),  size=8, color=RGBColor(0xCC,0xDD,0xEE), align=PP_ALIGN.CENTER)
    if i < 4:
        txbox(sl, "→", bx + bw, by + Inches(0.28), Inches(0.5), Inches(0.3),
              size=16, bold=True, color=BLUE, align=PP_ALIGN.CENTER)

txbox(sl, "↓  48 domain tool calls", Inches(5.5), Inches(2.25), Inches(3), Inches(0.3),
      size=10, italic=True, color=MED, align=PP_ALIGN.CENTER)

# bottom flow row
flow_bot = [
    (GREEN,  "SAP EWM (OData V4)", "WO · Tasks · Stock · GR · PI"),
    (GOLD,   "SAP MM (OData V2)",  "Stock · GR · Deliveries · STO"),
    (PURPLE, "Production (BAPI/V2)", "Orders · BOM · Confirmations"),
    (NAVY,   "BTP Connectivity",   "Cloud Connector → D4H-200"),
]
by2 = Inches(2.65)
for i, (col, title, sub) in enumerate(flow_bot):
    bx = bx_start + i * Inches(3.2)
    rect(sl, bx, by2, Inches(3.0), bh, fill=col)
    txbox(sl, title, bx, by2 + Inches(0.12), Inches(3.0), Inches(0.35), size=10, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    txbox(sl, sub,   bx, by2 + Inches(0.48), Inches(3.0), Inches(0.3),  size=8, color=RGBColor(0xCC,0xDD,0xEE), align=PP_ALIGN.CENTER)
    if i < 3:
        txbox(sl, "↔", bx + Inches(3.0), by2 + Inches(0.28), Inches(0.2), Inches(0.3),
              size=14, bold=True, color=GREEN, align=PP_ALIGN.CENTER)

# 4 design-principle cards
principles = [
    ("BTP Native", "Destination + Connectivity Service", BLUE),
    ("A2A Protocol", "Agent-to-Agent JSON-RPC 2.0", TEAL),
    ("Human-in-Loop", "Write ops require explicit approval", ORANGE),
    ("Multi-Tenant", "One codebase, per-tenant config", GREEN),
]
py = Inches(3.65); pw = Inches(3.1); ph = Inches(0.95)
for i, (t, s, col) in enumerate(principles):
    px = Inches(0.35) + i * Inches(3.25)
    rect(sl, px, py, pw, ph, fill=WHITE, line=RGBColor(0xD0,0xD0,0xD0))
    rect(sl, px, py, pw, Inches(0.06), fill=col)
    txbox(sl, t, px, py + Inches(0.12), pw, Inches(0.35), size=11, bold=True, color=DARK, align=PP_ALIGN.CENTER)
    txbox(sl, s, px, py + Inches(0.48), pw, Inches(0.4), size=9, color=MED, align=PP_ALIGN.CENTER)

footer_bar(sl)

# ==================== SLIDE 4 — 13 SKILLS ====================
sl = add_slide()
header_bar(sl, "13 Conversational Skills",
           "Intent detection + tool orchestration + human-in-loop approval for all write operations",
           "JOULE STUDIO · REGISTERED")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

skills = [
    ("01·Read",  "MM Stock Query",          "Plant/SLoc/batch stock via MM inventory API",                     False),
    ("02·Read",  "EWM Stock Query",          "Bin-level available + physical stock in WH PBAR",                 False),
    ("03·Read",  "Cross-Warehouse Stock",    "Physical stock across all 34 warehouses in one query",            False),
    ("04·Read",  "WO & Tasks",               "EWM WO/WT query, filter by status, material, bin",                False),
    ("05·Write", "Task Confirmation ✋",      "Confirm EWM warehouse tasks with qty and destination bin",        True),
    ("06·Read",  "Inbound Deliveries",       "Delivery headers, items, and document flow",                      False),
    ("07·Read",  "EWM Outbound",             "Outbound delivery orders from warehouse perspective",              False),
    ("08·Read",  "Storage Bins",             "Bin master data, fixed assignments, empty bins",                   False),
    ("09·Write", "Goods Movement & GR ✋",   "Material doc history + post goods receipt movement 101",          True),
    ("10·Read",  "EWM Phys. Inventory",      "PI documents and count items in warehouse PBAR",                   False),
    ("11·Read",  "Production Orders",        "Order status, BOM components, routing operations",                 False),
    ("12·Write", "STO 3PL→FEN1 ✋",          "One-shot STO ZIC3 → GI 351 → GR 101, no inbound delivery",      True),
    ("13·Write", "EWM Inbound GR ✋",        "GR against EWM inbound delivery — full, partial, or HU-level",   True),
]

cols4 = 4
sw = Inches(3.1); sh = Inches(1.05)
sx0 = Inches(0.35); sy0 = Inches(1.25)
gap4 = Inches(0.1)
for i, (num, name, desc, write) in enumerate(skills):
    col = i % cols4; row = i // cols4
    x = sx0 + col * (sw + gap4)
    y = sy0 + row * (sh + gap4)
    accent = ORANGE if write else BLUE
    # wider last card
    w = sw if i < 12 else sw * 2 + gap4
    rect(sl, x, y, w, sh, fill=WHITE, line=RGBColor(0xE0,0xE0,0xE0))
    rect(sl, x, y, w, Inches(0.05), fill=accent)
    txbox(sl, num,  x + Inches(0.08), y + Inches(0.08), w - Inches(0.12), Inches(0.22),
          size=8, bold=True, color=accent)
    txbox(sl, name, x + Inches(0.08), y + Inches(0.28), w - Inches(0.12), Inches(0.3),
          size=10, bold=True, color=DARK)
    txbox(sl, desc, x + Inches(0.08), y + Inches(0.6),  w - Inches(0.12), Inches(0.38),
          size=8, color=MED)
    if i == 12:
        break   # last card spans 2 cols

# legend chips
txbox(sl, "● 8 Read skills    ✋ 5 Write skills (require approval gate)    ✓ All 13 registered in Joule Studio (FGF tenant)",
      Inches(0.4), Inches(7.0), Inches(12), Inches(0.2), size=9, color=MED)

footer_bar(sl)

# ==================== SLIDE 5 — 48 TOOLS ====================
sl = add_slide()
header_bar(sl, "48 SAP Tools — Deep API Coverage",
           "OData V2, OData V4, A2X, BAPI/SOAP — all major EWM and S/4HANA APIs represented",
           "S/4HANA · EWM · MM · PP")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

groups = [
    ("EWM Warehouse [V4]",
     "get_warehouse_orders, get_warehouse_tasks, get_warehouse_task_detail\nconfirm_warehouse_task, confirm_warehouse_task_exact [WRITE]\nget_storage_bins, get_fixed_bin_assignments\nget_warehouses, get_storage_types, get_warehouse_resources"),
    ("EWM Stock [V4]",
     "get_ewm_available_stock\nget_ewm_physical_stock\nget_cross_warehouse_stock\nget_phys_inventory_docs\nget_phys_inventory_count_items"),
    ("EWM Inbound GR [A2X V4]",
     "list_ewm_inbound_deliveries\nget_ewm_inbound_delivery\npost_ewm_inbound_gr [WRITE]\nget_ewm_outbound_deliveries\nget_ewm_outbound_delivery_items"),
    ("MM Inventory [V2]",
     "get_material_stock, get_stock_overview\nget_inbound_deliveries, get_inbound_delivery_detail\nget_delivery_items, get_delivery_doc_flow\nget_material_documents\npost_goods_receipt [WRITE]\nsearch_batches, get_batch_classification"),
    ("STO Transfer [V2]",
     "create_sto [WRITE]\npost_sto_goods_issue [WRITE]\npost_sto_goods_receipt_no_del [WRITE]\nexecute_sto_transfer [WRITE]\nget_purchase_orders, get_po_details"),
    ("Production [BAPI+V2]",
     "get_production_order, get_production_order_components\nget_production_order_operations, get_production_confirmations\nget_production_orders_odata, get_production_order_status_odata\npost_goods_issue_production [WRITE]\npost_production_confirmation [WRITE]\npost_goods_receipt_production [WRITE]"),
]

gw = Inches(4.1); gh = Inches(2.3)
gx0 = Inches(0.35); gy0 = Inches(1.25)
gg = Inches(0.12)
for i, (grp, tools) in enumerate(groups):
    col = i % 3; row = i // 3
    x = gx0 + col * (gw + gg)
    y = gy0 + row * (gh + gg)
    rect(sl, x, y, gw, gh, fill=WHITE, line=RGBColor(0xD8,0xD8,0xD8))
    rect(sl, x, y, gw, Inches(0.04), fill=BLUE)
    txbox(sl, grp, x + Inches(0.1), y + Inches(0.08), gw - Inches(0.15), Inches(0.3),
          size=10, bold=True, color=BLUE)
    txbox(sl, tools, x + Inches(0.1), y + Inches(0.42), gw - Inches(0.15), gh - Inches(0.5),
          size=8, color=DARK)

footer_bar(sl)

# ==================== SLIDE 6 — BEFORE vs AFTER ====================
sl = add_slide()
header_bar(sl, "From SAP Transactions to Conversation",
           "The agent replaces manual navigation with intelligent, action-ready responses",
           "BUSINESS VALUE")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

# Before column
rect(sl, Inches(0.3), Inches(1.2), Inches(6.2), Inches(5.8), fill=WHITE, line=RGBColor(0xD0,0xD0,0xD0))
txbox(sl, "BEFORE — SAP Transactions", Inches(0.5), Inches(1.3), Inches(5.8), Inches(0.35),
      size=11, bold=True, color=MED)

before = [
    ("How much stock for 1010005 in bin H13A2?", "→ Open LX03, navigate warehouse/bin, read screen manually"),
    ("Which inbound deliveries expected today?",   "→ Run VL06I, filter by warehouse, export to Excel"),
    ("Confirm WT 1000045 to GR-DOCK with 50 EA",  "→ Navigate LT12, enter task + qty + bin, confirm"),
    ("Post GR for inbound delivery 180000234",     "→ Open MIGO, GR for inbound delivery, fill items, post"),
    ("Status of PO 1001176 — any shortages?",      "→ CO03, multiple tabs, manual availability check"),
]
for i, (q, a) in enumerate(before):
    y = Inches(1.75) + i * Inches(1.0)
    txbox(sl, q, Inches(0.5), y, Inches(5.8), Inches(0.3), size=10, bold=True, color=DARK)
    txbox(sl, a, Inches(0.5), y + Inches(0.32), Inches(5.8), Inches(0.35),
          size=9, italic=True, color=MED)

# After column
rect(sl, Inches(6.85), Inches(1.2), Inches(6.1), Inches(5.8), fill=LBLUE)
txbox(sl, "AFTER — Warehouse AI Agent", Inches(7.0), Inches(1.3), Inches(5.8), Inches(0.35),
      size=11, bold=True, color=WHITE)

after = [
    ("How much stock for 1010005 in bin H13A2?",
     '"Bin H13A2: 120 EA available, 120 EA physical. Storage type 3000."'),
    ("Which inbound deliveries expected today?",
     '"3 open deliveries for PBAR: 1800234 (10:00), 1800236 (14:30)…"'),
    ("Confirm WT 1000045 to GR-DOCK with 50 EA",
     '[Approval prompt] → User approves → "Task confirmed. 50 EA → GR-DOCK."'),
    ("Post GR for delivery 180000234",
     '[Shows items, asks confirm] → "GR posted. Mat.doc 5000012345 created."'),
    ("Status of PO 1001176 — any shortages?",
     '"Released. Qty 500. Shortages: 1010017 (-20 EA), 1010019 (-10 EA)…"'),
]
for i, (q, a) in enumerate(after):
    y = Inches(1.75) + i * Inches(1.0)
    txbox(sl, q, Inches(7.0), y, Inches(5.8), Inches(0.3), size=10, bold=True, color=WHITE)
    txbox(sl, a, Inches(7.0), y + Inches(0.32), Inches(5.8), Inches(0.35),
          size=9, italic=True, color=RGBColor(0xBB,0xDD,0xFF))

footer_bar(sl)

# ==================== SLIDE 7 — BUSINESS VALUE ====================
sl = add_slide()
header_bar(sl, "Business Value Delivered",
           "Measurable impact across warehouse operations, speed, and platform integration",
           "ROI · IMPACT")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

kpis = [("48", "SAP APIs Unified"), ("<30s", "vs. 5+ min manual"), ("Zero", "SAP GUI Required"), ("4", "Tenants Live Today")]
kw = Inches(3.1); kh = Inches(1.4)
kx0 = Inches(0.35)
for i, (n, l) in enumerate(kpis):
    kpi(sl, kx0 + i * Inches(3.25), Inches(1.25), kw, kh, n, l)

# two detail boxes
rect(sl, Inches(0.35), Inches(2.85), Inches(6.1), Inches(4.1), fill=WHITE, line=RGBColor(0xD0,0xD0,0xD0))
rect(sl, Inches(0.35), Inches(2.85), Inches(6.1), Inches(0.04), fill=BLUE)
txbox(sl, "Operational Efficiency", Inches(0.5), Inches(2.95), Inches(5.8), Inches(0.3),
      size=11, bold=True, color=NAVY)
op_items = [
    "✓  Stock lookups: seconds vs. minutes of transaction navigation",
    "✓  Inbound GR: conversational posting replaces MIGO forms",
    "✓  STO one-shot: create + GI 351 + GR 101 in a single command",
    "✓  Cross-warehouse: 34 warehouses answered in one query",
    "✓  Task confirmation: guided workflow with quantity validation",
]
for i, t in enumerate(op_items):
    txbox(sl, t, Inches(0.5), Inches(3.35) + i * Inches(0.55), Inches(5.8), Inches(0.45),
          size=10, color=DARK)

rect(sl, Inches(6.85), Inches(2.85), Inches(6.1), Inches(4.1), fill=WHITE, line=RGBColor(0xD0,0xD0,0xD0))
rect(sl, Inches(6.85), Inches(2.85), Inches(6.1), Inches(0.04), fill=BLUE)
txbox(sl, "Platform & Integration Benefits", Inches(7.0), Inches(2.95), Inches(5.8), Inches(0.3),
      size=11, bold=True, color=NAVY)
pl_items = [
    "✓  100% native on SAP BTP — no third-party infrastructure",
    "✓  Joule Studio: 13 skills as built-in Joule intents (FGF)",
    "✓  MCP proxy: connects Claude Code, Cursor, Joule Desktop",
    "✓  A2A standard: future-ready for multi-agent orchestration",
    "✓  Responsible AI: human approval gates on all write operations",
]
for i, t in enumerate(pl_items):
    txbox(sl, t, Inches(7.0), Inches(3.35) + i * Inches(0.55), Inches(5.8), Inches(0.45),
          size=10, color=DARK)

footer_bar(sl)

# ==================== SLIDE 8 — CLIENT INTERFACES ====================
sl = add_slide()
header_bar(sl, "Four Ways to Access the Agent",
           "Browser, desktop widget, developer MCP proxy, and embedded Joule intent",
           "UX · ACCESSIBILITY")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

ifaces = [
    (BLUE,   "Web Chat UI",
     "SAP Fiori-styled browser interface with collapsible Skills + Quick Actions sidebar. Markdown rendering, confirmation prompts for write operations, session history, and a full 'All Skills & Prompts' catalog with 13 skill tiles.",
     "warehouse-agent-ui.cfapps.us10-001.hana.ondemand.com"),
    (ORANGE, "Floating Desktop Widget",
     "Transparent tkinter overlay for Windows — stays visible while SAP GUI is open. Ctrl+Alt+W shows/hides from anywhere. Ctrl+Alt+J opens popup and switches destination to D4H-200. Auto-launches at Windows login.",
     "floating_icon.pyw · pythonw.exe · shell:startup"),
    (TEAL,   "MCP Proxy (Claude Code / Joule Desktop)",
     "FastAPI server on localhost:8766 exposing ask_warehouse_agent as a single MCP tool over Streamable HTTP (MCP 2025-03-26). Register in Joule Desktop, Claude Code (.mcp.json), or Cursor without browser auth.",
     "http://localhost:8766/mcp · mcp_proxy/warehouse_mcp.py"),
    (PURPLE, "SAP Joule Studio Integration",
     "All 13 skills registered as triggerable Joule intents on the FGF BTP tenant. Intent matching uses skill descriptions + sample utterances from SKILL.md files loaded at agent startup.",
     "FGF tenant only · load_skill_resources.py · skills/*/SKILL.md"),
]

iw = Inches(6.1); ih = Inches(2.7)
ix0 = Inches(0.35); iy0 = Inches(1.25)
for i, (col, title, body, url) in enumerate(ifaces):
    ic = i % 2; ir = i // 2
    x = ix0 + ic * (iw + Inches(0.3))
    y = iy0 + ir * (ih + Inches(0.15))
    rect(sl, x, y, iw, ih, fill=WHITE, line=RGBColor(0xD0,0xD0,0xD0))
    rect(sl, x, y, iw, Inches(0.06), fill=col)
    txbox(sl, title, x + Inches(0.12), y + Inches(0.12), iw - Inches(0.2), Inches(0.35),
          size=13, bold=True, color=DARK)
    txbox(sl, body,  x + Inches(0.12), y + Inches(0.52), iw - Inches(0.2), ih - Inches(1.1),
          size=9, color=MED)
    txbox(sl, url,   x + Inches(0.12), y + ih - Inches(0.38), iw - Inches(0.2), Inches(0.3),
          size=8, color=col)

footer_bar(sl)

# ==================== SLIDE 9 — MULTI-TENANT ====================
sl = add_slide()
header_bar(sl, "Multi-Tenant — One Codebase, Any S/4HANA",
           "Per-tenant destination and AI Core config — deploy to a new backend in hours, not months",
           "BTP · SCALABLE")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

# table
headers = ["Tenant", "SAP Backend", "WH / Plant", "BTP Subaccount", "Joule Studio", "Status"]
col_w   = [Inches(3.1), Inches(2.7), Inches(1.5), Inches(2.5), Inches(1.4), Inches(1.4)]
rows_data = [
    ["★ FGF Brands — D4H-200", "D4H-200 via SBPA_d4hclnt200", "PBAR/BAR1", "FGFDev (us10-001)", "✓ Subscribed", "● Primary", True],
    ["COE — COENAMFLIVE", "S4X-100 via UXM Cloud Connector", "1710/1710", "max-na-industry-us10", "Standalone A2A", "● Live", False],
    ["SM Trial (sm1801)", "D4H-200 (same as FGF)", "PBAR/BAR1", "sm1801 (us10-001)", "—", "● Live", False],
    ["Hackathon (original)", "S4X-100 via gclp0353", "1710/1710", "gdh-prj-vector", "—", "Historical", False],
]
tx = Inches(0.3); ty = Inches(1.25)
th = Inches(0.38)
rect(sl, tx, ty, W - Inches(0.6), th, fill=NAVY)
xi = tx
for j, (hdr, cw) in enumerate(zip(headers, col_w)):
    txbox(sl, hdr, xi + Inches(0.08), ty + Inches(0.07), cw - Inches(0.1), Inches(0.25),
          size=9, bold=True, color=WHITE)
    xi += cw

for r, row_data in enumerate(rows_data):
    is_primary = row_data[-1]
    row_vals = row_data[:-1]
    ry = ty + th + r * th
    bg = RGBColor(0xE8, 0xF4, 0xFF) if is_primary else (WHITE if r % 2 == 0 else BG)
    rect(sl, tx, ry, W - Inches(0.6), th, fill=bg)
    xi = tx
    for j, (val, cw) in enumerate(zip(row_vals, col_w)):
        fcol = BLUE if is_primary else (GREEN if "Live" in val or "Primary" in val else DARK)
        txbox(sl, val, xi + Inches(0.08), ry + Inches(0.07), cw - Inches(0.1), Inches(0.25),
              size=9, color=fcol, bold=(j == 0))
        xi += cw

# 3 config cards
config_cards = [
    ("What's Shared (One Codebase)", LBLUE,
     "✓ All 48 tools and 13 skills\n✓ A2A server + LangGraph logic\n✓ System prompts + intent matching\n✓ Approval gate framework\n✓ Web UI + MCP proxy"),
    ("What's Per-Tenant (Config Only)", ORANGE,
     "✓ Destination name (env var)\n✓ AI Core deployment ID + model\n✓ BTP services bound in manifest\n✓ CF manifest file (manifest-*.yml)\n✓ Cloud Connector location ID"),
    ("Add a New Tenant (3 Steps)", GREEN,
     "1. Create BTP destination to backend\n2. Set env vars in new manifest\n3. cf push -f manifest-new.yml\n\n✓ First agent live: same day"),
]
ccy = Inches(3.85); cch = Inches(2.9); ccw = Inches(4.1)
for i, (t, col, body) in enumerate(config_cards):
    cx = Inches(0.35) + i * Inches(4.3)
    rect(sl, cx, ccy, ccw, cch, fill=WHITE, line=RGBColor(0xD0,0xD0,0xD0))
    rect(sl, cx, ccy, ccw, Inches(0.04), fill=col)
    txbox(sl, t,    cx + Inches(0.12), ccy + Inches(0.1),  ccw - Inches(0.2), Inches(0.35),
          size=11, bold=True, color=DARK)
    txbox(sl, body, cx + Inches(0.12), ccy + Inches(0.52), ccw - Inches(0.2), cch - Inches(0.65),
          size=10, color=DARK)

footer_bar(sl)

# ==================== SLIDE 10 — ROADMAP ====================
sl = add_slide()
header_bar(sl, "What's Live & What's Next",
           "Extensible framework — new skills and tools without architectural changes",
           "ROADMAP")
rect(sl, 0, Inches(1.1), W, H - Inches(1.1), fill=BG)

delivered = [
    ("13 Skills + 48 Tools",
     "Full EWM stock, orders, tasks, GR, PI, outbound. MM deliveries, GR, STO. Production order read + write execution. All live on FGF."),
    ("Joule Studio Integration",
     "All 13 skills as triggerable intents on FGF tenant. Natural language intent matching via skill descriptions + sample utterances."),
    ("MCP Proxy for Developer Tools",
     "Claude Code, Cursor, and SAP Joule Desktop connect via local MCP server on localhost:8766 — no browser auth required."),
    ("4 Tenant Deployments",
     "FGF primary, COE, Trial, and Hackathon — all serving different S/4HANA backends from one codebase, same-day deploy."),
]

roadmap = [
    ("EWM Putaway & Replenishment",
     "Trigger putaway orders and replenishment tasks conversationally. Extend task confirmation skill with putaway control."),
    ("TM Delivery Scheduling",
     "SAP TM carrier visibility and delivery scheduling queries via A2X TM OData APIs — close the logistics loop."),
    ("Proactive Alerting Agent",
     "Monitor inventory thresholds, overdue tasks, and delivery exceptions. Shift from reactive to proactive operations."),
    ("Multi-Agent Orchestration",
     "Warehouse agent as specialist in a broader supply chain agent network — coordinating with demand, procurement, logistics agents via A2A."),
]

col_w2 = Inches(6.0)
lx = Inches(0.35); rx = Inches(7.0); row_h = Inches(1.3)

txbox(sl, "✓ Delivered", lx, Inches(1.2), col_w2, Inches(0.3), size=12, bold=True, color=DARK)
rect(sl, lx, Inches(1.5), col_w2, Inches(0.04), fill=GREEN)

txbox(sl, "→ Potential Next", rx, Inches(1.2), col_w2, Inches(0.3), size=12, bold=True, color=DARK)
rect(sl, rx, Inches(1.5), col_w2, Inches(0.04), fill=ORANGE)

for i, (t, b) in enumerate(delivered):
    y = Inches(1.65) + i * row_h
    rect(sl, lx, y, Inches(0.9), Inches(0.28), fill=GREEN)
    txbox(sl, "Live", lx + Inches(0.05), y + Inches(0.04), Inches(0.8), Inches(0.22),
          size=9, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    txbox(sl, t, lx + Inches(1.05), y, col_w2 - Inches(1.15), Inches(0.28),
          size=11, bold=True, color=DARK)
    txbox(sl, b, lx + Inches(1.05), y + Inches(0.3), col_w2 - Inches(1.15), Inches(0.9),
          size=9, color=MED)

tags = ["Near-term", "Near-term", "Strategic", "Strategic"]
tag_cols = [ORANGE, ORANGE, MED, MED]
for i, (t, b) in enumerate(roadmap):
    y = Inches(1.65) + i * row_h
    rect(sl, rx, y, Inches(1.1), Inches(0.28), fill=tag_cols[i])
    txbox(sl, tags[i], rx + Inches(0.05), y + Inches(0.04), Inches(1.0), Inches(0.22),
          size=8, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    txbox(sl, t, rx + Inches(1.2), y, col_w2 - Inches(1.3), Inches(0.28),
          size=11, bold=True, color=DARK)
    txbox(sl, b, rx + Inches(1.2), y + Inches(0.3), col_w2 - Inches(1.3), Inches(0.9),
          size=9, color=MED)

footer_bar(sl)

# ==================== SAVE ====================
out = r"C:\mydata\JD\Joulewarehouse\warehouse-agent-deck.pptx"
prs.save(out)
print(f"Saved: {out}")
