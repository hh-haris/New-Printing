"""
Modern Printers - Banner Printing Tracker
Run: python banner_tracker.py
Requires: pip install reportlab pillow
Data stored in: ~/banner_tracker.db (SQLite)
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
import csv
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from functools import partial
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                 Spacer, HRFlowable, KeepTogether)
from reportlab.platypus import LongTable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

DB_PATH = Path.home() / "banner_tracker.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS banners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                width_ft REAL NOT NULL,
                height_ft REAL NOT NULL,
                pieces INTEGER DEFAULT 1,
                sqft REAL NOT NULL,
                price_per_sqft REAL NOT NULL,
                amount REAL NOT NULL,
                custom_amount INTEGER DEFAULT 0,
                date_sent TEXT NOT NULL,
                date_added TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                notes TEXT DEFAULT '',
                client_name TEXT DEFAULT '',
                client_rate REAL DEFAULT 0,
                client_amount REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                date_paid TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("INSERT OR IGNORE INTO settings VALUES ('price_per_sqft', '50')")
        conn.execute("INSERT OR IGNORE INTO settings VALUES ('reminder_days', '10')")
        conn.commit()
        # Migrate old schema
        for col, definition in [
            ("pieces", "INTEGER DEFAULT 1"),
            ("price_per_sqft", "REAL NOT NULL DEFAULT 50"),
            ("amount", "REAL NOT NULL DEFAULT 0"),
            ("custom_amount", "INTEGER DEFAULT 0"),
            ("client_name", "TEXT DEFAULT ''"),
            ("client_rate", "REAL DEFAULT 0"),
            ("client_amount", "REAL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE banners ADD COLUMN {col} {definition}")
                conn.commit()
            except:
                pass
        # Backfill amount/price for old rows
        price = float(get_setting("price_per_sqft") or 50)
        conn.execute("UPDATE banners SET price_per_sqft=? WHERE price_per_sqft=0", (price,))
        conn.execute("UPDATE banners SET amount=sqft*price_per_sqft WHERE amount=0")
        conn.execute("UPDATE banners SET pieces=1 WHERE pieces IS NULL OR pieces=0")
        conn.commit()

def get_setting(key):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

def set_setting(key, value):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))
        conn.commit()

# ─── Colors & Fonts ──────────────────────────────────────────────────────────

C = {
    "bg":        "#FAFAFA",
    "white":     "#FFFFFF",
    "border":    "#E8E8EC",
    "border2":   "#D0D0D8",
    "text":      "#1A1A2E",
    "muted":     "#8A8A9A",
    "muted2":    "#BCBCCC",
    "accent":    "#2563EB",
    "accent_lt": "#EFF6FF",
    "accent_hv": "#DBEAFE",
    "green":     "#16A34A",
    "green_lt":  "#F0FDF4",
    "green_hv":  "#BBF7D0",
    "red":       "#DC2626",
    "red_lt":    "#FEF2F2",
    "red_hv":    "#FECACA",
    "orange":    "#D97706",
    "orange_lt": "#FFFBEB",
    "orange_hv": "#FDE68A",
    "purple":    "#7C3AED",
    "purple_lt": "#F5F3FF",
    "row_alt":   "#F8F8FB",
    "hover":     "#F0F4FF",
}

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "SF Pro Display" if sys.platform == "darwin" else "Ubuntu"

def font(size=10, weight="normal"):
    return (FONT_FAMILY, size, weight)

def fmt_rs(amount):
    return f"Rs {amount:,.0f}"

def fmt_date(d):
    if not d:
        return ""
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except:
        return d

def parse_date(s):
    """Accept dd/mm/yyyy or yyyy-mm-dd. Returns None if no format matches."""
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None

def today_str():
    return date.today().strftime("%d/%m/%Y")

def today_iso():
    return date.today().strftime("%Y-%m-%d")

def hover_btn(btn, hover_bg, normal_bg):
    """Bind hover effects to a button for better visual feedback."""
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
    btn.bind("<Leave>", lambda e: btn.config(bg=normal_bg))

# ─── Auto-mark banners paid by amount ─────────────────────────────────────────

def auto_mark_paid(total_paid):
    """Mark banners as paid oldest-first up to total_paid amount.
    Resets remaining banners to pending so deleted payments revert status."""
    with get_db() as conn:
        banners = conn.execute(
            "SELECT id, amount, status FROM banners ORDER BY date_sent ASC, id ASC"
        ).fetchall()
        remaining = total_paid
        for b in banners:
            amt = b["amount"] if b["amount"] else 0
            if remaining >= amt and amt > 0:
                conn.execute("UPDATE banners SET status='paid' WHERE id=?", (b["id"],))
                remaining -= amt
            elif remaining > 0 and amt > 0:
                conn.execute("UPDATE banners SET status='partial' WHERE id=?", (b["id"],))
                remaining = 0
            else:
                conn.execute("UPDATE banners SET status='pending' WHERE id=?", (b["id"],))
        conn.commit()

def get_client_names():
    """Get unique client names from past banner jobs."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT client_name FROM banners WHERE client_name != '' ORDER BY client_name"
        ).fetchall()
    return [r["client_name"] for r in rows]

def get_last_client_rate(client_name):
    """Get the last used client rate for a given client."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT client_rate FROM banners WHERE client_name=? AND client_rate > 0 ORDER BY id DESC LIMIT 1",
            (client_name,)
        ).fetchone()
    return row["client_rate"] if row else None

# ─── PDF Export Helpers ───────────────────────────────────────────────────────

def _pdf_styles():
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PDFTitle",
        parent=styles["Normal"],
        fontSize=20,
        textColor=colors.HexColor("#1A1A2E"),
        spaceAfter=4,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "PDFSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#8A8A9A"),
        spaceAfter=2,
        alignment=TA_CENTER,
    )
    section_style = ParagraphStyle(
        "PDFSection",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#2563EB"),
        spaceBefore=12,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "PDFBody",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#1A1A2E"),
        leading=13,
    )
    return title_style, subtitle_style, section_style, body_style


def export_banners_pdf(rows, filepath):
    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    title_s, subtitle_s, section_s, body_s = _pdf_styles()
    story = []

    # Header
    story.append(Paragraph("Modern Printers", title_s))
    story.append(Paragraph("Banner Jobs Report", subtitle_s))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            subtitle_s))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#2563EB")))
    story.append(Spacer(1, 0.4*cm))

    # Summary
    total_cost = sum(r["amount"] for r in rows)
    total_rev = sum((r["client_amount"] or 0) for r in rows)
    paid_count = sum(1 for r in rows if r["status"] == "paid")
    summary_data = [
        ["Total Jobs", str(len(rows)), "Print Cost", f"Rs {total_cost:,.0f}"],
        ["Paid Jobs", str(paid_count), "Client Revenue", f"Rs {total_rev:,.0f}"],
        ["Pending", str(len(rows) - paid_count), "Net Profit",
         f"Rs {(total_rev - total_cost):,.0f}"],
    ]
    sum_table = Table(summary_data, colWidths=[3.5*cm, 2.5*cm, 3.5*cm, 3*cm])
    sum_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#8A8A9A")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#8A8A9A")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#1A1A2E")),
        ("TEXTCOLOR", (3, 0), (3, -1), colors.HexColor("#2563EB")),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1),
         [colors.HexColor("#EFF6FF"), colors.HexColor("#DBEAFE")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DBEAFE")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 0.5*cm))

    # Table headers
    story.append(Paragraph("Banner Jobs", section_s))
    header = ["#", "Description", "Mail Send", "Size", "Sq Ft",
              "Print Cost", "Client Rev", "Status"]
    col_w = [0.8*cm, 5.5*cm, 2.3*cm, 2.5*cm, 1.5*cm, 2.5*cm, 2.5*cm, 1.8*cm]
    data = [header]
    for i, r in enumerate(rows, 1):
        size_str = f"{r['width_ft']}×{r['height_ft']}"
        if (r["pieces"] or 1) > 1:
            size_str += f"×{r['pieces']}"
        data.append([
            str(i),
            (r["description"] or "")[:40],
            fmt_date(r["date_sent"]),
            size_str,
            f"{r['sqft']:.1f}",
            f"Rs {r['amount']:,.0f}",
            f"Rs {r['client_amount']:,.0f}" if r["client_amount"] else "—",
            (r["status"] or "").upper(),
        ])

    t = LongTable(data, colWidths=col_w, repeatRows=1)
    row_colors = []
    for i in range(1, len(data)):
        status = data[i][7]
        if status == "PAID":
            row_colors.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F0FDF4")))
        elif status == "PENDING":
            row_colors.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FEF2F2")))
        else:
            row_colors.append(("BACKGROUND", (0, i), (-1, i),
                               colors.white if i % 2 == 0 else colors.HexColor("#F8F8FB")))

    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E8E8EC")),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),
    ] + row_colors))
    story.append(t)

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E8E8EC")))
    story.append(Paragraph(
        f"Modern Printers · {datetime.now().strftime('%d/%m/%Y')} · Total: {len(rows)} records",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#BCBCCC"),
                       alignment=TA_CENTER)
    ))
    doc.build(story)


def export_payments_pdf(rows, total_billed, filepath):
    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    title_s, subtitle_s, section_s, body_s = _pdf_styles()
    story = []

    # Receipt Header
    story.append(Paragraph("Modern Printers", title_s))
    story.append(Paragraph("Payment Records", subtitle_s))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            subtitle_s))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#16A34A")))
    story.append(Spacer(1, 0.4*cm))

    total_paid = sum(r["amount"] for r in rows)
    balance = total_billed - total_paid

    # Summary box
    sum_data = [
        ["Total Billed", f"Rs {total_billed:,.0f}"],
        ["Total Received", f"Rs {total_paid:,.0f}"],
        ["Balance Due" if balance > 0 else "Credit Balance", f"Rs {abs(balance):,.0f}"],
    ]
    sum_table = Table(sum_data, colWidths=[8*cm, 6*cm])
    sum_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0FDF4")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#DCFCE7")),
        ("BACKGROUND", (0, 2), (-1, 2),
         colors.HexColor("#FEF2F2") if balance > 0 else colors.HexColor("#F0FDF4")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#8A8A9A")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#16A34A")),
        ("TEXTCOLOR", (1, 2), (1, 2),
         colors.HexColor("#DC2626") if balance > 0 else colors.HexColor("#16A34A")),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBF7D0")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 0.6*cm))

    story.append(Paragraph("Payment History", section_s))
    header = ["#", "Date Paid", "Amount (Rs)", "Notes"]
    col_w = [1*cm, 4*cm, 4*cm, 8*cm]
    data = [header]
    running = 0
    for i, r in enumerate(rows, 1):
        running += r["amount"]
        data.append([
            str(i),
            fmt_date(r["date_paid"]),
            f"Rs {r['amount']:,.0f}" if r["amount"] >= 0 else f"−Rs {abs(r['amount']):,.0f}",
            r["notes"] or "",
        ])

    t = LongTable(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16A34A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F8F8FB")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E8E8EC")),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ]))
    story.append(t)

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E8E8EC")))
    story.append(Paragraph(
        f"Modern Printers · {datetime.now().strftime('%d/%m/%Y')} · {len(rows)} payment(s)",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#BCBCCC"),
                       alignment=TA_CENTER)
    ))
    doc.build(story)


def export_full_db_pdf(banners, payments, filepath):
    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    title_s, subtitle_s, section_s, body_s = _pdf_styles()
    story = []

    story.append(Paragraph("Modern Printers", title_s))
    story.append(Paragraph("Full Database Export", subtitle_s))
    story.append(Paragraph(f"Exported: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            subtitle_s))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#7C3AED")))
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph(f"Banner Jobs ({len(banners)} records)", section_s))
    if banners:
        header = ["#", "Description", "Mail Send", "Size", "Sq Ft", "Print Cost",
                  "Client Rev", "Status"]
        col_w = [0.8*cm, 5.2*cm, 2.3*cm, 2.3*cm, 1.5*cm, 2.5*cm, 2.5*cm, 1.7*cm]
        data = [header]
        for i, r in enumerate(banners, 1):
            size_str = f"{r['width_ft']}×{r['height_ft']}"
            if (r["pieces"] or 1) > 1:
                size_str += f"×{r['pieces']}"
            data.append([
                str(i),
                (r["description"] or "")[:38],
                fmt_date(r["date_sent"]),
                size_str,
                f"{r['sqft']:.1f}",
                f"Rs {r['amount']:,.0f}",
                f"Rs {r['client_amount']:,.0f}" if r["client_amount"] else "—",
                (r["status"] or "").upper(),
            ])
        t = LongTable(data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7C3AED")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F5F3FF")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E8E8EC")),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

    story.append(Spacer(1, 0.6*cm))
    story.append(Paragraph(f"Payment Records ({len(payments)} records)", section_s))
    if payments:
        total_paid = sum(p["amount"] for p in payments)
        ph = ["#", "Date Paid", "Amount (Rs)", "Notes"]
        pcol_w = [1*cm, 4*cm, 4*cm, 9.8*cm]
        pdata = [ph]
        for i, r in enumerate(payments, 1):
            pdata.append([
                str(i),
                fmt_date(r["date_paid"]),
                f"Rs {r['amount']:,.0f}" if r["amount"] >= 0 else f"−Rs {abs(r['amount']):,.0f}",
                r["notes"] or "",
            ])
        pt = LongTable(pdata, colWidths=pcol_w, repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7C3AED")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F5F3FF")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E8E8EC")),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ]))
        story.append(pt)
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(
            f"Total Payments: Rs {total_paid:,.0f}",
            ParagraphStyle("tot", fontSize=10, textColor=colors.HexColor("#16A34A"),
                           fontName="Helvetica-Bold", alignment=TA_RIGHT)
        ))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E8E8EC")))
    story.append(Paragraph(
        f"Modern Printers · Full Export · {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#BCBCCC"),
                       alignment=TA_CENTER)
    ))
    doc.build(story)



class BannerTrackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        init_db()
        self.title("Modern Printers – Banner Printing Tracker")
        self.geometry("1280x860")
        self.minsize(960, 680)
        self.configure(bg=C["bg"])
        style = ttk.Style(self)
        style.configure('TCombobox', fieldbackground=C["bg"])
        self.price_var = tk.DoubleVar(value=float(get_setting("price_per_sqft") or 50))
        self._build_ui()
        self.refresh()
        self._check_reminders()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # ── Top Header ──
        header = tk.Frame(self, bg=C["white"], height=70)
        header.pack(fill="x")
        header.pack_propagate(False)

        left_hdr = tk.Frame(header, bg=C["white"])
        left_hdr.place(x=28, y=12)
        tk.Label(left_hdr, text="Modern Printers", font=font(17, "bold"),
                 bg=C["white"], fg=C["text"]).pack(anchor="w")
        tk.Label(left_hdr, text="Banner Printing Tracker",
                 font=font(9), bg=C["white"], fg=C["muted"]).pack(anchor="w")

        # Help / keyboard shortcuts button
        help_btn = tk.Button(header, text="❓", font=font(12), bg=C["white"], fg=C["muted"],
                             relief="flat", cursor="hand2", command=self._show_shortcuts_help)
        help_btn.place(relx=1.0, x=-200, y=20, anchor="ne")
        hover_btn(help_btn, C["accent_lt"], C["white"])

        # Right: price setting
        tf = tk.Frame(header, bg=C["white"])
        tf.place(relx=1.0, x=-24, y=18, anchor="ne")
        tk.Label(tf, text="Price / sq ft (Rs)", font=font(9), bg=C["white"], fg=C["muted"]).pack(side="left", padx=(0,6))
        self.price_entry = tk.Entry(tf, textvariable=self.price_var, width=8,
                                    font=font(11, "bold"), relief="flat",
                                    bg=C["accent_lt"], fg=C["accent"],
                                    insertbackground=C["accent"], justify="center",
                                    state="disabled", disabledbackground=C["border"],
                                    disabledforeground=C["muted"])
        self.price_entry.pack(side="left")
        self.price_entry.bind("<Return>", lambda e: self._save_price())
        self.price_entry.bind("<FocusOut>", lambda e: self._save_price())
        self._price_locked = True
        self.lock_btn = tk.Button(tf, text="🔒", font=font(9), bg=C["white"], fg=C["muted"],
                                  relief="flat", cursor="hand2", padx=2,
                                  command=self._toggle_price_lock)
        self.lock_btn.pack(side="left", padx=(4,0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── Summary Bar ──
        self.summary_bar = SummaryBar(self)
        self.summary_bar.pack(fill="x", padx=24, pady=(16,0))

        # ── Two Columns ──
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=14)

        # Left sidebar with scroll
        left_outer = tk.Frame(body, bg=C["bg"], width=355)
        left_outer.pack(side="left", fill="y", padx=(0, 16))
        left_outer.pack_propagate(False)

        # Scrollable sidebar
        self._sidebar_canvas = tk.Canvas(left_outer, bg=C["bg"], highlightthickness=0)
        sidebar_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=self._sidebar_canvas.yview)
        self._sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar_scroll.pack(side="right", fill="y")
        self._sidebar_canvas.pack(side="left", fill="both", expand=True)

        self._sidebar_frame = tk.Frame(self._sidebar_canvas, bg=C["bg"])
        self._sidebar_win = self._sidebar_canvas.create_window((0, 0), window=self._sidebar_frame, anchor="nw")
        self._sidebar_frame.bind("<Configure>", lambda e: self._sidebar_canvas.configure(
            scrollregion=self._sidebar_canvas.bbox("all")))
        self._sidebar_canvas.bind("<Configure>", lambda e: self._sidebar_canvas.itemconfig(
            self._sidebar_win, width=e.width))

        # Bind mousewheel to sidebar
        self._sidebar_canvas.bind("<Enter>", lambda e: self._bind_sidebar_scroll())
        self._sidebar_canvas.bind("<Leave>", lambda e: self._unbind_sidebar_scroll())

        self.add_form = AddBannerForm(self._sidebar_frame, self)
        self.add_form.pack(fill="x", pady=(0, 12))

        self.payment_panel = PaymentPanel(self._sidebar_frame, self)
        self.payment_panel.pack(fill="x", pady=(0, 12))

        self.compare_panel = ComparePanel(self._sidebar_frame, self)
        self.compare_panel.pack(fill="x", pady=(0, 12))

        self.shop_tracker = ShopProfitPanel(self._sidebar_frame, self)
        self.shop_tracker.pack(fill="x", pady=(0, 12))

        self.settings_panel = SettingsPanel(self._sidebar_frame, self)
        self.settings_panel.pack(fill="x", pady=(0, 12))

        # Right: Banner table
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        self.banner_table = BannerTable(right, self)
        self.banner_table.pack(fill="both", expand=True)

        # ── Keyboard shortcuts ──
        self.bind_all("<Control-n>", lambda e: self._shortcut_add_form())
        self.bind_all("<Control-p>", lambda e: self._shortcut_payment())
        self.bind_all("<Control-f>", lambda e: self._shortcut_search())
        self.bind_all("<F1>", lambda e: self._show_shortcuts_help())

    def _bind_sidebar_scroll(self):
        self._sidebar_canvas.bind_all("<MouseWheel>", self._on_sidebar_scroll)

    def _unbind_sidebar_scroll(self):
        self._sidebar_canvas.unbind_all("<MouseWheel>")

    def _on_sidebar_scroll(self, event):
        self._sidebar_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _shortcut_add_form(self):
        self._sidebar_canvas.yview_moveto(0)
        self.add_form.desc.focus_set()

    def _shortcut_payment(self):
        self.payment_panel.amt_entry.focus_set()

    def _shortcut_search(self):
        self.banner_table.search_entry.focus_set()
        if self.banner_table.search_entry.get() == "\U0001f50d Search...":
            self.banner_table.search_entry.delete(0, "end")

    def _show_shortcuts_help(self):
        help_win = tk.Toplevel(self)
        help_win.title("Keyboard Shortcuts")
        help_win.geometry("320x280")
        help_win.resizable(False, False)
        help_win.configure(bg=C["white"])
        help_win.grab_set()
        tk.Label(help_win, text="Keyboard Shortcuts", font=font(13, "bold"),
                 bg=C["white"], fg=C["text"]).pack(pady=(16, 8), padx=20, anchor="w")
        tk.Frame(help_win, bg=C["border"], height=1).pack(fill="x")
        shortcuts = [
            ("Ctrl + N", "Focus Add Banner form"),
            ("Ctrl + P", "Focus Payment form"),
            ("Ctrl + F", "Focus Search box"),
            ("F1", "Show this help"),
            ("Enter", "Submit current form"),
            ("Tab", "Move to next field"),
            ("Shift+Tab", "Move to previous field"),
        ]
        body = tk.Frame(help_win, bg=C["white"])
        body.pack(fill="both", expand=True, padx=20, pady=10)
        for key, desc in shortcuts:
            row = tk.Frame(body, bg=C["white"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=key, font=font(9, "bold"), bg=C["accent_lt"],
                     fg=C["accent"], padx=6, pady=2, width=12, anchor="center").pack(side="left")
            tk.Label(row, text=desc, font=font(9), bg=C["white"],
                     fg=C["text"], padx=8).pack(side="left")

    def _toggle_price_lock(self):
        """Toggle the price entry lock state."""
        self._price_locked = not self._price_locked
        if self._price_locked:
            self.price_entry.config(state="disabled", disabledbackground=C["border"],
                                    disabledforeground=C["muted"])
            self.lock_btn.config(text="\U0001f512")
        else:
            self.price_entry.config(state="normal", bg=C["accent_lt"], fg=C["accent"])
            self.lock_btn.config(text="\U0001f513")
            self.price_entry.focus_set()

    def _save_price(self):
        try:
            val = float(self.price_var.get())
            if val <= 0:
                return
            old_val = float(get_setting("price_per_sqft") or 50)
            if abs(val - old_val) < 0.001:
                return
            answer = messagebox.askyesnocancel(
                "Update Price",
                f"New rate: Rs {val:.0f}/sq ft\n\n"
                "Apply new rate to ALL existing banners?\n"
                "• YES = Update all previous banner prices\n"
                "• NO  = Only new banners use this rate\n"
                "• CANCEL = Keep old rate"
            )
            if answer is None:
                self.price_var.set(old_val)
                return
            set_setting("price_per_sqft", val)
            if answer:
                with get_db() as conn:
                    conn.execute("UPDATE banners SET price_per_sqft=?, amount=sqft*pieces*? WHERE custom_amount=0", (val, val))
                    conn.commit()
            self.refresh()
        except:
            pass

    def _check_reminders(self):
        reminder_days = int(get_setting("reminder_days") or 10)
        cutoff = (date.today() - timedelta(days=reminder_days)).strftime("%Y-%m-%d")
        with get_db() as conn:
            overdue = conn.execute(
                "SELECT COUNT(*) as cnt FROM banners WHERE status='pending' AND date_sent <= ?",
                (cutoff,)
            ).fetchone()["cnt"]
        if overdue > 0:
            messagebox.showwarning(
                "Payment Reminder",
                f"⚠️  {overdue} banner job(s) have been unpaid for more than {reminder_days} days!\n\n"
                "Please settle outstanding payments."
            )

    def refresh(self):
        self.summary_bar.refresh()
        self.banner_table.refresh()
        self.payment_panel.refresh()
        self.compare_panel.refresh()
        self.shop_tracker.refresh()

    def _on_close(self):
        """Confirm before closing if form fields have unsaved data."""
        has_data = False
        try:
            desc = self.add_form.desc.get("1.0", "end").strip()
            w = self.add_form.w_var.get().strip()
            h = self.add_form.h_var.get().strip()
            pay_amt = self.payment_panel.amt_var.get().strip()
            if desc or w or h or pay_amt:
                has_data = True
        except:
            pass
        if has_data:
            if not messagebox.askyesno("Unsaved Data",
                                        "You have unsaved form data.\nClose anyway?"):
                return
        self.destroy()

    def show_toast(self, message, bg=None, fg=None, duration=3000):
        """Show a non-blocking toast notification at the bottom of the window."""
        if bg is None:
            bg = C["green_lt"]
        if fg is None:
            fg = C["green"]
        toast = tk.Label(self, text=message, font=font(10, "bold"),
                         bg=bg, fg=fg, padx=16, pady=8, anchor="center")
        toast.place(relx=0.5, rely=1.0, anchor="s", y=-20)
        self.after(duration, toast.destroy)

# ─── Summary Bar ─────────────────────────────────────────────────────────────

class SummaryBar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg"])
        self.cards = {}
        defs = [
            ("total_billed",   "Total Print Cost",   C["accent"],  C["accent_lt"]),
            ("total_paid",     "Total Paid",          C["green"],   C["green_lt"]),
            ("balance_due",    "Balance Due",         C["red"],     C["red_lt"]),
            ("total_revenue",  "Client Revenue",      C["orange"],  C["orange_lt"]),
            ("net_profit",     "Net Profit",          C["green"],   C["white"]),
        ]
        for key, label, color, bg in defs:
            card = SummaryCard(self, label, color, bg)
            card.pack(side="left", expand=True, fill="x", padx=(0, 8))
            self.cards[key] = card

    def refresh(self):
        with get_db() as conn:
            banners = conn.execute("SELECT amount, client_amount, status FROM banners").fetchall()
            payments = conn.execute("SELECT SUM(amount) as total FROM payments").fetchone()

        total_billed = sum(b["amount"] for b in banners)
        total_paid = float(payments["total"] or 0)
        balance_due = total_billed - total_paid
        total_revenue = sum((b["client_amount"] or 0) for b in banners)
        net_profit = total_revenue - total_billed
        paid_count = sum(1 for b in banners if b["status"] == "paid")

        self.cards["total_billed"].set(fmt_rs(total_billed))
        self.cards["total_paid"].set(fmt_rs(total_paid), f"{paid_count} banners paid")
        if balance_due > 0:
            self.cards["balance_due"].set(fmt_rs(balance_due), "amount owed")
            self.cards["balance_due"].val_label.config(fg=C["red"])
        else:
            self.cards["balance_due"].set(fmt_rs(abs(balance_due)), "credit balance")
            self.cards["balance_due"].val_label.config(fg=C["green"])
        self.cards["total_revenue"].set(fmt_rs(total_revenue))
        self.cards["net_profit"].set(fmt_rs(net_profit),
                                     "profit" if net_profit >= 0 else "loss")


class SummaryCard(tk.Frame):
    def __init__(self, parent, label, color, bg):
        super().__init__(parent, bg=bg, padx=12, pady=10,
                         highlightbackground=C["border"], highlightthickness=1)
        tk.Label(self, text=label, font=font(8), bg=bg, fg=C["muted"]).pack(anchor="w")
        self.val_label = tk.Label(self, text="—", font=font(13, "bold"), bg=bg, fg=color)
        self.val_label.pack(anchor="w")
        self.sub_label = tk.Label(self, text="", font=font(8), bg=bg, fg=C["muted"])
        self.sub_label.pack(anchor="w")

    def set(self, value, sub=""):
        self.val_label.config(text=value)
        self.sub_label.config(text=sub)

# ─── Add Banner Form ──────────────────────────────────────────────────────────

class AddBannerForm(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="➕  Add New Banner Job", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["white"])
        body.pack(fill="x", padx=14, pady=8)

        # Description (expandable Text widget, center-aligned, no placeholder)
        tk.Label(body, text="Description", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(2,1))
        self.desc = tk.Text(body, font=font(11), relief="flat",
                             bg=C["bg"], fg=C["text"], insertbackground=C["accent"],
                             height=2, wrap="word")
        self.desc.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 4), ipady=4)
        self.desc.tag_configure("center", justify="center")
        self.desc.bind("<KeyPress>", self._on_desc_key)
        self.desc.bind("<KeyRelease>", self._on_desc_key)

        # Width, Height, Pieces
        tk.Label(body, text="W (ft)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=0, sticky="w", pady=(6,1))
        tk.Label(body, text="H (ft)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=1, sticky="w", pady=(6,1), padx=(6,0))
        tk.Label(body, text="Pcs", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=2, sticky="w", pady=(6,1), padx=(6,0))

        self.w_var = tk.StringVar()
        self.h_var = tk.StringVar()
        self.pcs_var = tk.StringVar(value="1")

        self.w_entry = tk.Entry(body, textvariable=self.w_var, font=font(10), relief="flat",
                                bg=C["bg"], fg=C["text"], width=6, justify="center")
        self.h_entry = tk.Entry(body, textvariable=self.h_var, font=font(10), relief="flat",
                                bg=C["bg"], fg=C["text"], width=6, justify="center")
        self.pcs_entry = tk.Entry(body, textvariable=self.pcs_var, font=font(10), relief="flat",
                                  bg=C["bg"], fg=C["text"], width=4, justify="center")
        self.w_entry.grid(row=3, column=0, sticky="ew", ipady=5)
        self.h_entry.grid(row=3, column=1, sticky="ew", ipady=5, padx=(6,0))
        self.pcs_entry.grid(row=3, column=2, sticky="ew", ipady=5, padx=(6,0))

        self.w_var.trace_add("write", lambda *a: self._update_preview())
        self.h_var.trace_add("write", lambda *a: self._update_preview())
        self.pcs_var.trace_add("write", lambda *a: self._update_preview())

        # Client Rate / Client Total
        tk.Label(body, text="Client Rate/sqft", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6,1))
        tk.Label(body, text="Client Total (auto)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=4, column=2, sticky="w", pady=(6,1), padx=(6,0))

        self.client_rate_var = tk.StringVar()
        self.client_total_var = tk.StringVar()
        self.client_rate_entry = tk.Entry(body, textvariable=self.client_rate_var, font=font(10),
                                          relief="flat", bg=C["bg"], fg=C["orange"],
                                          width=8, justify="center")
        self.client_total_entry = tk.Entry(body, textvariable=self.client_total_var, font=font(10),
                                           relief="flat", bg=C["bg"], fg=C["green"],
                                           width=8, justify="center")
        self.client_rate_entry.grid(row=5, column=0, columnspan=2, sticky="ew", ipady=5)
        self.client_total_entry.grid(row=5, column=2, sticky="ew", ipady=5, padx=(6,0))
        self.client_rate_var.trace_add("write", lambda *a: self._update_client_total())
        self.client_total_var.trace_add("write", lambda *a: self._update_client_rate())
        self._updating_client = False

        # Client Name (with autocomplete)
        tk.Label(body, text="Client Name (optional)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(6,1))
        self.client_name_var = tk.StringVar()
        self.client_name_entry = tk.Entry(body, textvariable=self.client_name_var, font=font(10),
                                          relief="flat", bg=C["bg"], fg=C["text"],
                                          justify="center")
        self.client_name_entry.grid(row=7, column=0, columnspan=3, sticky="ew", ipady=5)
        self.client_name_entry.bind("<KeyRelease>", self._on_client_name_key)
        self.client_name_entry.bind("<FocusOut>", self._on_client_name_select)
        self._client_listbox = None

        # Mail Send date
        tk.Label(body, text="Mail Send (dd/mm/yyyy)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(6,1))
        self.date_entry = tk.Entry(body, font=font(10), relief="flat",
                                   bg=C["bg"], fg=C["text"], justify="center")
        self.date_entry.insert(0, today_str())
        self.date_entry.grid(row=9, column=0, columnspan=3, sticky="ew", ipady=5)

        # Notes
        tk.Label(body, text="Notes (optional)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(6,1))
        self.notes_entry = tk.Entry(body, font=font(9), relief="flat", bg=C["bg"], fg=C["text"],
                                    justify="center")
        self.notes_entry.grid(row=11, column=0, columnspan=3, sticky="ew", ipady=4)

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)

        # Preview
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        self.preview = tk.Label(self, text="Enter size to preview amount",
                                font=font(9), bg=C["bg"], fg=C["muted"],
                                anchor="center", pady=6)
        self.preview.pack(fill="x")

        btn = tk.Button(self, text="ADD BANNER JOB", font=font(10, "bold"),
                        bg=C["accent"], fg="white", relief="flat",
                        activebackground="#1d4ed8", activeforeground="white",
                        cursor="hand2", pady=8, command=self._add)
        btn.pack(fill="x", padx=14, pady=10)
        hover_btn(btn, "#1d4ed8", C["accent"])

        self.success_label = tk.Label(self, text="", font=font(9, "bold"),
                                      bg=C["white"], fg=C["green"], pady=0)
        self.success_label.pack(fill="x", padx=14)

        # Keyboard: Enter key to submit
        for entry in [self.w_entry, self.h_entry, self.pcs_entry,
                       self.date_entry, self.notes_entry]:
            entry.bind("<Return>", lambda e: self._add())

    def _on_desc_key(self, event=None):
        self.desc.tag_add("center", "1.0", "end")

    def _on_client_name_key(self, event=None):
        """Show autocomplete suggestions for client name."""
        text = self.client_name_var.get().strip()
        self._close_client_listbox()
        if len(text) < 1:
            return
        names = get_client_names()
        matches = [n for n in names if text.lower() in n.lower()]
        if not matches:
            return
        self._client_listbox = tk.Listbox(self.client_name_entry.master, font=font(9),
                                           bg=C["white"], fg=C["text"], relief="solid",
                                           bd=1, height=min(len(matches), 5))
        for name in matches:
            self._client_listbox.insert("end", name)
        self._client_listbox.grid(row=7, column=0, columnspan=3, sticky="ew")
        self._client_listbox.lift()
        self._client_listbox.bind("<<ListboxSelect>>", self._pick_client_name)

    def _pick_client_name(self, event=None):
        if self._client_listbox:
            sel = self._client_listbox.curselection()
            if sel:
                name = self._client_listbox.get(sel[0])
                self.client_name_var.set(name)
                rate = get_last_client_rate(name)
                if rate:
                    self.client_rate_var.set(str(rate))
        self._close_client_listbox()

    def _on_client_name_select(self, event=None):
        self.after(200, self._close_client_listbox)

    def _close_client_listbox(self):
        if self._client_listbox:
            self._client_listbox.destroy()
            self._client_listbox = None

    def _get_sqft(self):
        try:
            w = float(self.w_var.get())
            h = float(self.h_var.get())
            pcs = max(1, int(self.pcs_var.get() or 1))
            return w * h * pcs, w, h, pcs
        except:
            return None, None, None, None

    def _update_preview(self):
        sqft, w, h, pcs = self._get_sqft()
        if sqft:
            price = float(get_setting("price_per_sqft") or 50)
            amount = sqft * price
            self.preview.config(
                text=f"{w}×{h} ft × {pcs}pcs = {sqft:.2f} sqft  →  {fmt_rs(amount)}",
                bg=C["accent_lt"], fg=C["accent"]
            )
        else:
            self.preview.config(text="Enter size to preview amount", bg=C["bg"], fg=C["muted"])
        self._update_client_total()

    def _update_client_total(self):
        if self._updating_client:
            return
        self._updating_client = True
        try:
            sqft, _, _, _ = self._get_sqft()
            rate_str = self.client_rate_var.get().strip()
            if sqft and rate_str:
                rate = float(rate_str)
                total = round(sqft * rate, 0)
                self.client_total_var.set(str(int(total)))
        except:
            pass
        self._updating_client = False

    def _update_client_rate(self):
        if self._updating_client:
            return
        self._updating_client = True
        try:
            sqft, _, _, _ = self._get_sqft()
            total_str = self.client_total_var.get().strip()
            if sqft and total_str and sqft > 0:
                total = float(total_str)
                rate = round(total / sqft, 2)
                self.client_rate_var.set(str(rate))
        except:
            pass
        self._updating_client = False

    def _add(self):
        desc = self.desc.get("1.0", "end").strip()
        if not desc:
            messagebox.showwarning("Missing Info", "Please enter a description.")
            return
        sqft, w, h, pcs = self._get_sqft()
        if not sqft:
            messagebox.showwarning("Invalid Size", "Enter valid width & height.")
            return
        date_sent = parse_date(self.date_entry.get())
        if not date_sent:
            messagebox.showwarning("Missing Date", "Enter a valid date.")
            return
        price = float(get_setting("price_per_sqft") or 50)
        amount = round(sqft * price, 2)
        notes = self.notes_entry.get().strip()
        client_name = self.client_name_var.get().strip()
        try:
            client_rate = float(self.client_rate_var.get() or 0)
        except:
            client_rate = 0
        try:
            client_amount = float(self.client_total_var.get() or 0)
        except:
            client_amount = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute(
                """INSERT INTO banners
                   (description, width_ft, height_ft, pieces, sqft, price_per_sqft,
                    amount, custom_amount, date_sent, date_added, status, notes,
                    client_name, client_rate, client_amount)
                   VALUES (?,?,?,?,?,?,?,0,?,?,?,?,?,?,?)""",
                (desc, w, h, pcs, sqft, price, amount, date_sent, now, "pending",
                 notes, client_name, client_rate, client_amount)
            )
            conn.commit()
        self.desc.delete("1.0", "end")
        self.w_var.set("")
        self.h_var.set("")
        self.pcs_var.set("1")
        self.client_rate_var.set("")
        self.client_total_var.set("")
        self.client_name_var.set("")
        self.notes_entry.delete(0, "end")
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, today_str())
        self.preview.config(text="Enter size to preview amount", bg=C["bg"], fg=C["muted"])
        self.app.refresh()
        self._show_success(f"✓ Added: {desc[:30]}")

    def _show_success(self, msg):
        self.success_label.config(text=msg, bg=C["green_lt"], pady=4)
        self.after(3000, lambda: self.success_label.config(text="", bg=C["white"], pady=0))

# ─── Payment Panel ────────────────────────────────────────────────────────────

class PaymentPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._month_expanded = {}
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="💵  Record a Payment", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["white"])
        body.pack(fill="x", padx=14, pady=8)

        tk.Label(body, text="Amount (Rs) — negative amount adds to Balance Due",
                 font=font(8), bg=C["white"], fg=C["muted"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(2,1))

        self.amt_var = tk.StringVar()
        self.amt_entry = tk.Entry(body, textvariable=self.amt_var, font=font(11, "bold"),
                                  relief="flat", bg=C["bg"], fg=C["green"],
                                  insertbackground=C["green"], justify="center")
        self.amt_entry.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=6)

        tk.Label(body, text="Date Paid (dd/mm/yyyy)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=2, column=0, sticky="w", pady=(6,1))
        tk.Label(body, text="Notes", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=2, column=1, sticky="w", pady=(6,1), padx=(6,0))

        self.date_entry = tk.Entry(body, font=font(9), relief="flat",
                                   bg=C["bg"], fg=C["text"], justify="center")
        self.date_entry.insert(0, today_str())
        self.date_entry.grid(row=3, column=0, sticky="ew", ipady=5)

        self.notes = tk.Entry(body, font=font(9), relief="flat", bg=C["bg"], fg=C["text"])
        self.notes.grid(row=3, column=1, sticky="ew", ipady=5, padx=(6,0))

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        btn = tk.Button(self, text="RECORD PAYMENT", font=font(10, "bold"),
                        bg=C["green"], fg="white", relief="flat",
                        activebackground="#15803d", activeforeground="white",
                        cursor="hand2", pady=7, command=self._add_payment)
        btn.pack(fill="x", padx=14, pady=(2, 8))
        hover_btn(btn, "#15803d", C["green"])

        self.success_label = tk.Label(self, text="", font=font(9, "bold"),
                                      bg=C["white"], fg=C["green"], pady=0)
        self.success_label.pack(fill="x", padx=14)

        # Keyboard: Enter key to submit
        self.amt_entry.bind("<Return>", lambda e: self._add_payment())
        self.date_entry.bind("<Return>", lambda e: self._add_payment())
        self.notes.bind("<Return>", lambda e: self._add_payment())

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        hist_hdr = tk.Frame(self, bg=C["white"], pady=6, padx=14)
        hist_hdr.pack(fill="x")
        tk.Label(hist_hdr, text="Payment History", font=font(9, "bold"),
                 bg=C["white"], fg=C["muted"]).pack(side="left")

        self.hist_frame = tk.Frame(self, bg=C["white"])
        self.hist_frame.pack(fill="x", padx=14, pady=(0, 8))

    def _add_payment(self):
        try:
            amt = float(self.amt_var.get())
        except:
            messagebox.showwarning("Invalid Amount", "Enter a valid payment amount.")
            return
        date_paid = parse_date(self.date_entry.get())
        if not date_paid:
            messagebox.showwarning("Invalid Date", "Enter a valid date (dd/mm/yyyy).")
            return
        notes = self.notes.get().strip()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute("INSERT INTO payments (amount, date_paid, notes, created_at) VALUES (?,?,?,?)",
                         (amt, date_paid, notes, now))
            conn.commit()
        self.amt_var.set("")
        self.notes.delete(0, "end")
        # Auto-mark banners
        with get_db() as conn:
            total_paid = conn.execute("SELECT SUM(amount) as s FROM payments").fetchone()["s"] or 0
        auto_mark_paid(total_paid)
        self.app.refresh()
        self._show_success(f"✓ Payment of {fmt_rs(amt)} recorded")

    def _show_success(self, msg):
        self.success_label.config(text=msg, bg=C["green_lt"], pady=4)
        self.after(3000, lambda: self.success_label.config(text="", bg=C["white"], pady=0))

    def refresh(self):
        for w in self.hist_frame.winfo_children():
            w.destroy()
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM payments ORDER BY date_paid DESC").fetchall()
        if not rows:
            tk.Label(self.hist_frame, text="No payments recorded yet.", font=font(8),
                     bg=C["white"], fg=C["muted2"]).pack(anchor="w", pady=4)
            return

        # Group by month
        months = {}
        for row in rows:
            try:
                dt = datetime.strptime(row["date_paid"][:10], "%Y-%m-%d")
                key = dt.strftime("%B %Y")
            except:
                key = "Unknown"
            months.setdefault(key, []).append(row)

        for month_key, month_rows in months.items():
            month_total = sum(r["amount"] for r in month_rows)
            expanded = self._month_expanded.get(month_key, False)

            # Month header (expandable)
            mhdr = tk.Frame(self.hist_frame, bg=C["bg"], cursor="hand2")
            mhdr.pack(fill="x", pady=(2,0))
            arrow = "▼" if expanded else "▶"
            tk.Label(mhdr, text=f"{arrow} {month_key}", font=font(9, "bold"),
                     bg=C["bg"], fg=C["text"]).pack(side="left", padx=4, pady=3)
            tk.Label(mhdr, text=fmt_rs(month_total), font=font(9, "bold"),
                     bg=C["bg"], fg=C["green"]).pack(side="right", padx=4)

            def toggle(mk=month_key):
                self._month_expanded[mk] = not self._month_expanded.get(mk, False)
                self.refresh()

            mhdr.bind("<Button-1>", lambda e, t=toggle: t())
            for child in mhdr.winfo_children():
                child.bind("<Button-1>", lambda e, t=toggle: t())

            if expanded:
                # Group by week inside month
                weeks = {}
                for row in month_rows:
                    try:
                        dt = datetime.strptime(row["date_paid"][:10], "%Y-%m-%d")
                        week_num = dt.isocalendar()[1]
                        wkey = f"Week {week_num}"
                    except:
                        wkey = "Unknown"
                    weeks.setdefault(wkey, []).append(row)

                for wkey, week_rows in weeks.items():
                    week_total = sum(r["amount"] for r in week_rows)
                    wf = tk.Frame(self.hist_frame, bg=C["white"])
                    wf.pack(fill="x")
                    tk.Label(wf, text=f"  {wkey}", font=font(8), bg=C["white"], fg=C["muted"]).pack(side="left", padx=8)
                    tk.Label(wf, text=fmt_rs(week_total), font=font(8), bg=C["white"], fg=C["muted"]).pack(side="right", padx=8)

                    for row in week_rows:
                        r = tk.Frame(self.hist_frame, bg=C["white"])
                        r.pack(fill="x")

                        def make_del(rid):
                            def do_del():
                                if messagebox.askyesno("Delete Payment", "Remove this payment?"):
                                    with get_db() as conn:
                                        conn.execute("DELETE FROM payments WHERE id=?", (rid,))
                                        conn.commit()
                                    with get_db() as conn:
                                        total_paid = conn.execute("SELECT SUM(amount) as s FROM payments").fetchone()["s"] or 0
                                    auto_mark_paid(total_paid)
                                    self.app.refresh()
                            return do_del

                        del_btn = tk.Button(r, text="✕", font=font(8), bg=C["white"], fg=C["muted2"],
                                  relief="flat", cursor="hand2",
                                  command=make_del(row["id"]))
                        del_btn.pack(side="right", padx=2)
                        hover_btn(del_btn, C["red_lt"], C["white"])

                        amt_color = C["green"] if row["amount"] >= 0 else C["red"]
                        amt_text = fmt_rs(row["amount"])
                        if row["amount"] < 0:
                            amt_text = f"−{fmt_rs(abs(row['amount']))}"
                        tk.Label(r, text=amt_text, font=font(9, "bold"),
                                 bg=C["white"], fg=amt_color).pack(side="right", padx=4)
                        if row["notes"]:
                            tk.Label(r, text=row["notes"], font=font(7),
                                     bg=C["white"], fg=C["muted2"]).pack(side="right", padx=4)
                        tk.Label(r, text=f"    {fmt_date(row['date_paid'])}", font=font(8),
                                 bg=C["white"], fg=C["muted"]).pack(side="left", padx=4)

# ─── Compare Panel ────────────────────────────────────────────────────────────

class ComparePanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚡  Compare Shop's Bill", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["white"])
        body.pack(fill="x", padx=14, pady=10)

        tk.Label(body, text="Shop's bill amount (Rs)", font=font(8),
                 bg=C["white"], fg=C["muted"]).pack(anchor="w", pady=(0,2))
        row = tk.Frame(body, bg=C["white"])
        row.pack(fill="x")
        self.bill_var = tk.StringVar()
        tk.Entry(row, textvariable=self.bill_var, font=font(12, "bold"), relief="flat",
                 bg=C["bg"], fg=C["text"], justify="center").pack(side="left", ipady=5, expand=True, fill="x")
        chk_btn = tk.Button(row, text="CHECK", font=font(9, "bold"), bg=C["orange"], fg="white",
                  relief="flat", cursor="hand2", padx=10, pady=5,
                  activebackground="#b45309", activeforeground="white",
                  command=self._compare)
        chk_btn.pack(side="right", padx=(8,0))
        hover_btn(chk_btn, "#b45309", C["orange"])

        self.result_frame = tk.Frame(self, bg=C["white"])
        self.result_frame.pack(fill="x", padx=14, pady=(0, 8))

    def refresh(self):
        pass

    def _compare(self):
        for w in self.result_frame.winfo_children():
            w.destroy()
        try:
            shop_bill = float(self.bill_var.get())
            assert shop_bill > 0
        except:
            messagebox.showwarning("Invalid Amount", "Enter the shop's bill amount.")
            return
        with get_db() as conn:
            banners = conn.execute("SELECT amount FROM banners").fetchall()
        my_total = sum(b["amount"] for b in banners)
        diff = shop_bill - my_total

        if abs(diff) < 1:
            bg, fg, msg = C["green_lt"], C["green"], f"✅  Bills match!\nYours: {fmt_rs(my_total)}  |  Shop: {fmt_rs(shop_bill)}"
        elif diff > 0:
            bg, fg, msg = C["red_lt"], C["red"], f"⚠️  OVERCHARGED by {fmt_rs(diff)}!\nYours: {fmt_rs(my_total)}  |  Shop: {fmt_rs(shop_bill)}"
        else:
            bg, fg, msg = C["green_lt"], C["green"], f"ℹ️  Shop less by {fmt_rs(abs(diff))}\nYours: {fmt_rs(my_total)}  |  Shop: {fmt_rs(shop_bill)}"

        result_lbl = tk.Label(self.result_frame, text=msg, font=font(9), bg=bg, fg=fg,
                 justify="left", anchor="w", padx=10, pady=8)
        result_lbl.pack(fill="x")
        def _update_wraplength(event):
            result_lbl.config(wraplength=max(event.width - 20, 100))
        self.result_frame.bind("<Configure>", _update_wraplength)

# ─── Shop Profit Panel ────────────────────────────────────────────────────────

class ShopProfitPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._expanded = True
        self._month_expanded = {}
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14, cursor="hand2")
        hdr.pack(fill="x")
        self._arrow_lbl = tk.Label(hdr, text="▼", font=font(9), bg=C["white"], fg=C["muted"])
        self._arrow_lbl.pack(side="left", padx=(0,4))
        tk.Label(hdr, text="📊  Shop Profit Report", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        hdr.bind("<Button-1>", self._toggle)
        for child in hdr.winfo_children():
            child.bind("<Button-1>", self._toggle)
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        self.report_frame = tk.Frame(self, bg=C["white"])
        self.report_frame.pack(fill="x", padx=14, pady=8)

    def _toggle(self, event=None):
        self._expanded = not self._expanded
        self._arrow_lbl.config(text="▼" if self._expanded else "▶")
        if self._expanded:
            self.report_frame.pack(fill="x", padx=14, pady=8)
        else:
            self.report_frame.pack_forget()

    def refresh(self):
        for w in self.report_frame.winfo_children():
            w.destroy()

        if not self._expanded:
            return

        with get_db() as conn:
            banners = conn.execute("SELECT * FROM banners ORDER BY date_sent DESC").fetchall()
            total_paid_row = conn.execute("SELECT SUM(amount) as s FROM payments").fetchone()

        total_paid = float(total_paid_row["s"] or 0)

        if not banners:
            tk.Label(self.report_frame, text="No jobs recorded yet.", font=font(8),
                     bg=C["white"], fg=C["muted2"]).pack(anchor="w")
            return

        total_print_cost = sum(b["amount"] for b in banners)
        total_client_rev = sum((b["client_amount"] or 0) for b in banners)
        profit = total_client_rev - total_print_cost
        balance_due = total_print_cost - total_paid
        total_sqft = sum(b["sqft"] for b in banners)
        total_pieces = sum((b["pieces"] or 1) for b in banners)

        # Counts
        paid_count = sum(1 for b in banners if b["status"] == "paid")
        pending_count = sum(1 for b in banners if b["status"] == "pending")

        # Aging
        overdue_10, overdue_30 = [], []
        today = date.today()
        for b in banners:
            if b["status"] == "pending":
                try:
                    ds = datetime.strptime(b["date_sent"][:10], "%Y-%m-%d").date()
                    days = (today - ds).days
                    if days >= 30:
                        overdue_30.append(b)
                    elif days >= 10:
                        overdue_10.append(b)
                except:
                    pass

        # Monthly breakdown
        month_data = {}
        for b in banners:
            try:
                dt = datetime.strptime(b["date_sent"][:10], "%Y-%m-%d")
                mk = dt.strftime("%b %Y")
                if mk not in month_data:
                    month_data[mk] = {"cost": 0, "revenue": 0, "jobs": 0, "sqft": 0}
                month_data[mk]["cost"] += b["amount"]
                month_data[mk]["revenue"] += b["client_amount"] or 0
                month_data[mk]["jobs"] += 1
                month_data[mk]["sqft"] += b["sqft"]
            except:
                pass

        best_month = max(month_data, key=lambda m: month_data[m]["revenue"]) if month_data else "—"

        def stat_row(label, value, fg=None, bold=False):
            r = tk.Frame(self.report_frame, bg=C["white"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, font=font(8), bg=C["white"], fg=C["muted"]).pack(side="left")
            tk.Label(r, text=value, font=font(9, "bold" if bold else "normal"),
                     bg=C["white"], fg=fg or C["text"]).pack(side="right")

        def section_hdr(title):
            f = tk.Frame(self.report_frame, bg=C["accent_lt"])
            f.pack(fill="x", pady=(6,2))
            tk.Label(f, text=title, font=font(8, "bold"), bg=C["accent_lt"],
                     fg=C["accent"], padx=6, pady=2).pack(side="left")

        section_hdr("Overall Summary")
        stat_row("Total Jobs", str(len(banners)), C["text"], True)
        stat_row("Total Sq Ft Printed", f"{total_sqft:.1f} sqft", C["purple"], True)
        stat_row("Total Pieces", str(total_pieces), C["text"])
        stat_row("Print Cost (Total)", fmt_rs(total_print_cost), C["accent"], True)
        stat_row("Client Revenue", fmt_rs(total_client_rev), C["orange"], True)
        stat_row("Net Profit", fmt_rs(profit), C["green"] if profit >= 0 else C["red"], True)
        stat_row("Profit Margin",
                 f"{(profit/total_client_rev*100):.1f}%" if total_client_rev > 0 else "N/A",
                 C["green"] if profit >= 0 else C["red"])

        section_hdr("Payment Status")
        stat_row("Total Paid", fmt_rs(total_paid), C["green"], True)
        if balance_due > 0:
            stat_row("Balance Owed", fmt_rs(balance_due), C["red"], True)
        else:
            stat_row("Credit Balance", fmt_rs(abs(balance_due)), C["green"], True)
        stat_row("Jobs Paid", f"{paid_count} / {len(banners)}", C["green"])
        stat_row("Jobs Pending", str(pending_count), C["orange"] if pending_count else C["muted"])

        section_hdr("Overdue Jobs")
        stat_row("Overdue 10–29 days", f"{len(overdue_10)} jobs",
                 C["orange"] if overdue_10 else C["muted"])
        stat_row("Overdue 30+ days", f"{len(overdue_30)} jobs",
                 C["red"] if overdue_30 else C["muted"])

        section_hdr("Monthly Breakdown")
        for mk, mdata in list(month_data.items())[:6]:
            is_exp = self._month_expanded.get(mk, False)
            mhdr = tk.Frame(self.report_frame, bg=C["bg"], cursor="hand2")
            mhdr.pack(fill="x", pady=(2, 0))
            arrow = "▼" if is_exp else "▶"
            tk.Label(mhdr, text=f"{arrow} {mk}", font=font(8, "bold"),
                     bg=C["bg"], fg=C["text"]).pack(side="left", padx=4, pady=2)
            tk.Label(mhdr, text=f"{mdata['jobs']} jobs · {fmt_rs(mdata['revenue'])}",
                     font=font(8), bg=C["bg"], fg=C["orange"]).pack(side="right", padx=4)

            def toggle_m(m=mk):
                self._month_expanded[m] = not self._month_expanded.get(m, False)
                self.refresh()

            mhdr.bind("<Button-1>", lambda e, t=toggle_m: t())
            for child in mhdr.winfo_children():
                child.bind("<Button-1>", lambda e, t=toggle_m: t())

            if is_exp:
                mf = tk.Frame(self.report_frame, bg=C["white"])
                mf.pack(fill="x")
                for lbl, val, fg in [
                    ("  Jobs", str(mdata["jobs"]), C["text"]),
                    ("  Sq Ft", f"{mdata['sqft']:.1f}", C["purple"]),
                    ("  Print Cost", fmt_rs(mdata["cost"]), C["accent"]),
                    ("  Revenue", fmt_rs(mdata["revenue"]), C["orange"]),
                    ("  Profit", fmt_rs(mdata["revenue"] - mdata["cost"]),
                     C["green"] if mdata["revenue"] >= mdata["cost"] else C["red"]),
                ]:
                    rr = tk.Frame(mf, bg=C["white"])
                    rr.pack(fill="x")
                    tk.Label(rr, text=lbl, font=font(8), bg=C["white"], fg=C["muted"]).pack(side="left", padx=8)
                    tk.Label(rr, text=val, font=font(8, "bold"), bg=C["white"], fg=fg).pack(side="right", padx=8)

# ─── Settings Panel ───────────────────────────────────────────────────────────

class SettingsPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._expanded = False
        self._dm_expanded = False
        self._build()

    def _build(self):
        # Expandable header
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14, cursor="hand2")
        hdr.pack(fill="x")
        self._arrow_lbl = tk.Label(hdr, text="▶", font=font(9), bg=C["white"], fg=C["muted"])
        self._arrow_lbl.pack(side="left", padx=(0, 4))
        tk.Label(hdr, text="⚙️  Settings", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        hdr.bind("<Button-1>", self._toggle)
        for child in hdr.winfo_children():
            child.bind("<Button-1>", self._toggle)

        self._body_frame = tk.Frame(self, bg=C["white"])

    def _toggle(self, event=None):
        self._expanded = not self._expanded
        self._arrow_lbl.config(text="▼" if self._expanded else "▶")
        if self._expanded:
            self._body_frame.pack(fill="x")
            self._rebuild_body()
        else:
            self._body_frame.pack_forget()

    def _rebuild_body(self):
        for w in self._body_frame.winfo_children():
            w.destroy()

        tk.Frame(self._body_frame, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self._body_frame, bg=C["white"])
        body.pack(fill="x", padx=14, pady=8)

        tk.Label(body, text="Payment reminder after (days)", font=font(8),
                 bg=C["white"], fg=C["muted"]).grid(row=0, column=0, sticky="w", pady=(2,1))
        self.reminder_var = tk.StringVar(value=get_setting("reminder_days") or "10")
        re = tk.Entry(body, textvariable=self.reminder_var, font=font(10), relief="flat",
                      bg=C["bg"], fg=C["text"], width=6, justify="center")
        re.grid(row=0, column=1, sticky="ew", ipady=4, padx=(8,0))

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)

        save_btn = tk.Button(self._body_frame, text="SAVE SETTINGS", font=font(9, "bold"),
                  bg=C["accent_lt"], fg=C["accent"], relief="flat",
                  cursor="hand2", pady=6, command=self._save)
        save_btn.pack(fill="x", padx=14, pady=(0, 8))
        hover_btn(save_btn, C["accent_hv"], C["accent_lt"])

        # ── Data Management (sub-expandable) ──
        tk.Frame(self._body_frame, bg=C["border"], height=1).pack(fill="x")
        dm_hdr = tk.Frame(self._body_frame, bg=C["bg"], pady=6, padx=14, cursor="hand2")
        dm_hdr.pack(fill="x")
        self._dm_arrow = tk.Label(dm_hdr, text="▶", font=font(8), bg=C["bg"], fg=C["muted"])
        self._dm_arrow.pack(side="left", padx=(0, 4))
        tk.Label(dm_hdr, text="🗃️  Data Management", font=font(9, "bold"),
                 bg=C["bg"], fg=C["muted"]).pack(side="left")
        dm_hdr.bind("<Button-1>", self._toggle_dm)
        for child in dm_hdr.winfo_children():
            child.bind("<Button-1>", self._toggle_dm)

        self._dm_body = tk.Frame(self._body_frame, bg=C["white"])
        if self._dm_expanded:
            self._dm_body.pack(fill="x")
            self._rebuild_dm()

    def _toggle_dm(self, event=None):
        self._dm_expanded = not self._dm_expanded
        if hasattr(self, "_dm_arrow"):
            self._dm_arrow.config(text="▼" if self._dm_expanded else "▶")
        if self._dm_expanded:
            self._dm_body.pack(fill="x")
            self._rebuild_dm()
        else:
            self._dm_body.pack_forget()

    def _rebuild_dm(self):
        for w in self._dm_body.winfo_children():
            w.destroy()

        dm = self._dm_body
        padx = 14

        def add_btn(text, bg, fg, hover_c, cmd):
            b = tk.Button(dm, text=text, font=font(8, "bold"),
                          bg=bg, fg=fg, relief="flat", cursor="hand2", pady=5, command=cmd)
            b.pack(fill="x", padx=padx, pady=(0, 4))
            hover_btn(b, hover_c, bg)

        tk.Label(dm, text="Export", font=font(8, "bold"), bg=C["white"],
                 fg=C["muted"], padx=padx).pack(anchor="w", pady=(8, 2))

        add_btn("📄 Export Banner Jobs as PDF", C["accent_lt"], C["accent"], C["accent_hv"],
                self._export_banners_pdf)
        add_btn("🧾 Export Payment Records as PDF", C["green_lt"], C["green"], C["green_hv"],
                self._export_payments_pdf)
        add_btn("📊 Export Entire Database as CSV", C["purple_lt"], C["purple"], "#e9d5ff",
                self._export_db_csv)
        add_btn("📑 Export Entire Database as PDF", C["purple_lt"], C["purple"], "#e9d5ff",
                self._export_db_pdf)

        tk.Frame(dm, bg=C["border"], height=1).pack(fill="x", pady=(4, 4))
        tk.Label(dm, text="Manage Records", font=font(8, "bold"), bg=C["white"],
                 fg=C["muted"], padx=padx).pack(anchor="w", pady=(0, 2))

        add_btn("Clear All Banner Records", C["orange_lt"], C["orange"], C["orange_hv"],
                self._clear_banners)
        add_btn("Clear All Payments", C["orange_lt"], C["orange"], C["orange_hv"],
                self._clear_payments)
        add_btn("⚠  Reset Entire Database", C["red_lt"], C["red"], C["red_hv"],
                self._clear_all)
        tk.Frame(dm, bg=C["white"], height=4).pack()

    def _save(self):
        try:
            days = int(self.reminder_var.get())
            set_setting("reminder_days", days)
        except:
            pass
        self.app.refresh()
        self.app.show_toast("✓ Settings saved successfully")

    # ── Export functions ────────────────────────────────────────────────────────

    def _export_banners_pdf(self):
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM banners ORDER BY date_sent DESC, id DESC"
            ).fetchall()
        if not rows:
            messagebox.showinfo("No Data", "No banner records to export.")
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialfile=f"banner_jobs_{today_iso()}.pdf"
        )
        if not filepath:
            return
        export_banners_pdf(rows, filepath)
        self.app.show_toast("✓ Banner jobs exported")

    def _export_payments_pdf(self):
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM payments ORDER BY date_paid DESC").fetchall()
            total_billed = conn.execute("SELECT SUM(amount) as s FROM banners").fetchone()["s"] or 0
        if not rows:
            messagebox.showinfo("No Data", "No payment records to export.")
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialfile=f"payment_records_{today_iso()}.pdf"
        )
        if not filepath:
            return
        export_payments_pdf(rows, float(total_billed), filepath)
        self.app.show_toast("✓ Payment records exported")

    def _export_db_csv(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"full_database_{today_iso()}.csv"
        )
        if not filepath:
            return
        with get_db() as conn:
            banners = conn.execute(
                "SELECT id, description, client_name, date_sent, width_ft, height_ft, "
                "pieces, sqft, price_per_sqft, amount, client_rate, client_amount, "
                "status, notes FROM banners ORDER BY date_sent DESC, id DESC"
            ).fetchall()
            payments = conn.execute(
                "SELECT id, amount, date_paid, notes FROM payments ORDER BY date_paid DESC"
            ).fetchall()
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["=== BANNER JOBS ==="])
            writer.writerow(["ID", "Description", "Client", "Date Sent", "W(ft)", "H(ft)",
                             "Pieces", "SqFt", "Price/SqFt", "Print Cost",
                             "Client Rate", "Client Amount", "Status", "Notes"])
            for r in banners:
                writer.writerow([r["id"], r["description"], r["client_name"],
                                 fmt_date(r["date_sent"]), r["width_ft"], r["height_ft"],
                                 r["pieces"], r["sqft"], r["price_per_sqft"], r["amount"],
                                 r["client_rate"], r["client_amount"], r["status"], r["notes"]])
            writer.writerow([])
            writer.writerow(["=== PAYMENT RECORDS ==="])
            writer.writerow(["ID", "Amount", "Date Paid", "Notes"])
            for r in payments:
                writer.writerow([r["id"], r["amount"], fmt_date(r["date_paid"]), r["notes"]])
        self.app.show_toast("✓ Database exported as CSV")

    def _export_db_pdf(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialfile=f"full_database_{today_iso()}.pdf"
        )
        if not filepath:
            return
        with get_db() as conn:
            banners = conn.execute("SELECT * FROM banners ORDER BY date_sent DESC, id DESC").fetchall()
            payments = conn.execute("SELECT * FROM payments ORDER BY date_paid DESC").fetchall()
        export_full_db_pdf(banners, payments, filepath)
        self.app.show_toast("✓ Full database exported as PDF")

    def _clear_banners(self):
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM banners").fetchone()["c"]
        if count == 0:
            messagebox.showinfo("Nothing to Clear", "There are no banner records to clear.")
            return
        if messagebox.askyesno("Clear Banner Records",
                               f"This will permanently delete all {count} banner record(s).\n\n"
                               "Are you sure?"):
            if messagebox.askyesno("Final Confirmation",
                                   f"⚠️  FINAL WARNING: Delete ALL {count} banner records?\n\n"
                                   "This action CANNOT be undone!"):
                with get_db() as conn:
                    conn.execute("DELETE FROM banners")
                    conn.commit()
                self.app.refresh()
                self.app.show_toast(f"✓ All {count} banner record(s) deleted")

    def _clear_payments(self):
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM payments").fetchone()["c"]
        if count == 0:
            messagebox.showinfo("Nothing to Clear", "There are no payment records to clear.")
            return
        if messagebox.askyesno("Clear Payments",
                               f"This will permanently delete all {count} payment record(s).\n\n"
                               "Are you sure?"):
            if messagebox.askyesno("Final Confirmation",
                                   f"⚠️  FINAL WARNING: Delete ALL {count} payment records?\n\n"
                                   "This action CANNOT be undone!"):
                with get_db() as conn:
                    conn.execute("DELETE FROM payments")
                    conn.commit()
                self.app.refresh()
                self.app.show_toast(f"✓ All {count} payment record(s) deleted")

    def _clear_all(self):
        with get_db() as conn:
            b_count = conn.execute("SELECT COUNT(*) as c FROM banners").fetchone()["c"]
            p_count = conn.execute("SELECT COUNT(*) as c FROM payments").fetchone()["c"]
        if b_count == 0 and p_count == 0:
            messagebox.showinfo("Nothing to Clear", "The database is already empty.")
            return
        if messagebox.askyesno("Reset Entire Database",
                               f"This will permanently delete:\n"
                               f"  • {b_count} banner record(s)\n"
                               f"  • {p_count} payment record(s)\n\n"
                               "Are you sure?"):
            if messagebox.askyesno("Final Confirmation",
                                   "⚠️  FINAL WARNING: This will ERASE ALL DATA!\n\n"
                                   "This action CANNOT be undone!"):
                with get_db() as conn:
                    conn.execute("DELETE FROM banners")
                    conn.execute("DELETE FROM payments")
                    conn.commit()
                self.app.refresh()
                self.app.show_toast("✓ All data has been cleared")

# ─── Banner Table ─────────────────────────────────────────────────────────────

class BannerTable(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self.filter_status = "all"
        self.filter_from = ""
        self.filter_to = ""
        self.search_text = ""
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="All Banner Jobs", font=font(13, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")

        self.count_label = tk.Label(hdr, text="", font=font(9), bg=C["white"], fg=C["muted"])
        self.count_label.pack(side="left", padx=(8, 0))

        # Search box
        self.search_entry = tk.Entry(hdr, font=font(9), relief="flat",
                                     bg=C["bg"], fg=C["text"], width=16,
                                     insertbackground=C["accent"])
        self.search_entry.pack(side="left", padx=(12, 0), ipady=3)
        self.search_entry.insert(0, "🔍 Search...")
        self.search_entry.bind("<FocusIn>", self._search_focus_in)
        self.search_entry.bind("<FocusOut>", self._search_focus_out)
        self.search_entry.bind("<KeyRelease>", lambda e: self._on_search())

        # Filter buttons
        fbar = tk.Frame(hdr, bg=C["white"])
        fbar.pack(side="right")

        self.filter_btns = {}
        for label, key in [("All","all"),("Pending","pending"),("Partial","partial"),("Paid","paid")]:
            btn = tk.Button(fbar, text=label, font=font(8, "bold"), relief="flat",
                            bg=C["bg"], fg=C["muted"], padx=10, pady=3, cursor="hand2",
                            command=lambda k=key: self._set_filter(k))
            btn.pack(side="left", padx=2)
            self.filter_btns[key] = btn
        self._highlight_filter()

        # Date range filter
        range_bar = tk.Frame(self, bg=C["bg"], padx=14, pady=4)
        range_bar.pack(fill="x")
        tk.Label(range_bar, text="From:", font=font(8), bg=C["bg"], fg=C["muted"]).pack(side="left")
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        tk.Entry(range_bar, textvariable=self.from_var, font=font(8), relief="flat",
                 bg=C["white"], width=11, justify="center").pack(side="left", ipady=3, padx=(2,6))
        tk.Label(range_bar, text="To:", font=font(8), bg=C["bg"], fg=C["muted"]).pack(side="left")
        tk.Entry(range_bar, textvariable=self.to_var, font=font(8), relief="flat",
                 bg=C["white"], width=11, justify="center").pack(side="left", ipady=3, padx=(2,6))
        tk.Button(range_bar, text="Filter", font=font(8), bg=C["accent_lt"], fg=C["accent"],
                  relief="flat", cursor="hand2", padx=8, pady=2,
                  command=self._apply_date_filter).pack(side="left")
        tk.Button(range_bar, text="Clear", font=font(8), bg=C["bg"], fg=C["muted"],
                  relief="flat", cursor="hand2", padx=8, pady=2,
                  command=self._clear_date_filter).pack(side="left", padx=(4,0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Column headers
        cols_frame = tk.Frame(self, bg=C["bg"], pady=5, padx=8)
        cols_frame.pack(fill="x")
        cols = [("#", 3), ("Description", 18), ("Mail Send", 10),
                ("Size", 9), ("Sq Ft", 7), ("Print Cost", 9), ("Client Rev", 9),
                ("Status", 8), ("Actions", 14)]
        for i, (name, w) in enumerate(cols):
            tk.Label(cols_frame, text=name, font=font(8), bg=C["bg"], fg=C["muted"],
                     width=w, anchor="w").grid(row=0, column=i, padx=2)

        # Scrollable rows only
        scroll_wrapper = tk.Frame(self, bg=C["white"])
        scroll_wrapper.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(scroll_wrapper, bg=C["white"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_wrapper, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.rows_frame = tk.Frame(self.canvas, bg=C["white"])
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._on_rows_configure)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        # Bind mousewheel only when hovering over banner table
        self.canvas.bind("<Enter>", lambda e: self._bind_scroll())
        self.canvas.bind("<Leave>", lambda e: self._unbind_scroll())

    def _on_rows_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_scroll(self):
        self.canvas.bind_all("<MouseWheel>", self._on_scroll)

    def _unbind_scroll(self):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_scroll(self, event):
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _focus_add_form(self):
        """Scroll sidebar to top and focus the description field in add form."""
        self.app._sidebar_canvas.yview_moveto(0)
        self.app.add_form.desc.focus_set()

    def _search_focus_in(self, event):
        if self.search_entry.get() == "🔍 Search...":
            self.search_entry.delete(0, "end")

    def _search_focus_out(self, event):
        if not self.search_entry.get():
            self.search_entry.insert(0, "🔍 Search...")

    def _on_search(self):
        text = self.search_entry.get().strip()
        new_search = text if text != "🔍 Search..." else ""
        if new_search != self.search_text:
            self.search_text = new_search
            self.refresh()

    def _set_filter(self, key):
        self.filter_status = key
        self._highlight_filter()
        self.refresh()

    def _apply_date_filter(self):
        self.filter_from = (parse_date(self.from_var.get()) or "") if self.from_var.get().strip() else ""
        self.filter_to = (parse_date(self.to_var.get()) or "") if self.to_var.get().strip() else ""
        self.refresh()

    def _clear_date_filter(self):
        self.filter_from = ""
        self.filter_to = ""
        self.from_var.set("")
        self.to_var.set("")
        self.refresh()

    def _highlight_filter(self, count_map=None):
        for k, btn in self.filter_btns.items():
            is_active = k == self.filter_status
            has_items = count_map.get(k, 1) > 0 if count_map else True
            if is_active:
                btn.config(bg=C["accent"], fg="white", state="normal", cursor="hand2")
            elif not has_items and k != "all":
                btn.config(bg=C["border"], fg=C["muted2"], state="disabled", cursor="arrow")
            else:
                btn.config(bg=C["bg"], fg=C["muted"], state="normal", cursor="hand2")

    def refresh(self):
        for w in self.rows_frame.winfo_children():
            w.destroy()

        # Update filter button counts
        with get_db() as conn:
            total_count = conn.execute("SELECT COUNT(*) as c FROM banners").fetchone()["c"]
            pending_count = conn.execute("SELECT COUNT(*) as c FROM banners WHERE status='pending'").fetchone()["c"]
            partial_count = conn.execute("SELECT COUNT(*) as c FROM banners WHERE status='partial'").fetchone()["c"]
            paid_count = conn.execute("SELECT COUNT(*) as c FROM banners WHERE status='paid'").fetchone()["c"]
        count_map = {"all": total_count, "pending": pending_count, "partial": partial_count, "paid": paid_count}
        label_map = {"all": "All", "pending": "Pending", "partial": "Partial", "paid": "Paid"}
        for key, btn in self.filter_btns.items():
            btn.config(text=f"{label_map[key]} ({count_map[key]})")
        self._highlight_filter(count_map)
        self.count_label.config(text=f"({total_count} total)")

        query = "SELECT * FROM banners"
        params = []
        conditions = []

        if self.filter_status != "all":
            conditions.append("status=?")
            params.append(self.filter_status)
        if self.filter_from:
            conditions.append("date_sent >= ?")
            params.append(self.filter_from)
        if self.filter_to:
            conditions.append("date_sent <= ?")
            params.append(self.filter_to)
        if self.search_text:
            conditions.append("(description LIKE ? OR client_name LIKE ? OR notes LIKE ?)")
            params.extend([f"%{self.search_text}%", f"%{self.search_text}%", f"%{self.search_text}%"])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY date_sent DESC, id DESC"

        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()

        if not rows:
            empty = tk.Frame(self.rows_frame, bg=C["white"])
            empty.pack(expand=True, pady=40)
            tk.Label(empty, text="📋", font=font(24), bg=C["white"]).pack()
            tk.Label(empty, text="No banner jobs found", font=font(11, "bold"),
                     bg=C["white"], fg=C["text"]).pack(pady=(8, 2))
            tk.Label(empty, text="Add your first banner job using the form on the left",
                     font=font(9), bg=C["white"], fg=C["muted"]).pack()
            quick_add = tk.Button(empty, text="➕ Add Banner Job", font=font(10, "bold"),
                                  bg=C["accent"], fg="white", relief="flat",
                                  cursor="hand2", padx=16, pady=6,
                                  command=self._focus_add_form)
            quick_add.pack(pady=(12, 0))
            hover_btn(quick_add, "#1d4ed8", C["accent"])
            return

        for i, row in enumerate(rows):
            bg = C["row_alt"] if i % 2 == 0 else C["white"]
            self._make_row(row, i+1, bg)

    def _make_row(self, row, idx, bg):
        r = tk.Frame(self.rows_frame, bg=bg)
        r.pack(fill="x")

        def on_enter(e, frame=r):
            for w in frame.winfo_children():
                try: w.config(bg=C["hover"])
                except: pass
            frame.config(bg=C["hover"])
        def on_leave(e, frame=r, original_bg=bg):
            for w in frame.winfo_children():
                try: w.config(bg=original_bg)
                except: pass
            frame.config(bg=original_bg)
        r.bind("<Enter>", on_enter)
        r.bind("<Leave>", on_leave)

        s_bg = {"paid": C["green_lt"], "pending": C["red_lt"], "partial": C["orange_lt"]}
        s_fg = {"paid": C["green"], "pending": C["red"], "partial": C["orange"]}
        status = row["status"]

        size_str = f"{row['width_ft']}×{row['height_ft']}"
        if (row["pieces"] or 1) > 1:
            size_str += f"×{row['pieces']}pcs"

        client_rev = row["client_amount"] or 0

        vals = [
            (str(idx), 3, C["muted"], "normal"),
            ((row["description"] or "")[:22], 18, C["text"], "bold"),
            (fmt_date(row["date_sent"]), 10, C["muted"], "normal"),
            (size_str, 9, C["muted"], "normal"),
            (f"{row['sqft']:.1f}", 7, C["purple"], "bold"),
            (fmt_rs(row["amount"]), 9, C["accent"], "bold"),
            (fmt_rs(client_rev) if client_rev else "—", 9, C["orange"], "bold"),
        ]
        for text, width, fg, weight in vals:
            lbl = tk.Label(r, text=text, font=font(9, weight), bg=bg,
                           fg=fg, width=width, anchor="w", padx=3, pady=7)
            lbl.pack(side="left")
            lbl.bind("<Enter>", on_enter)
            lbl.bind("<Leave>", on_leave)

        # Status badge
        sbadge = tk.Label(r, text=status.upper(), font=font(7, "bold"),
                          bg=s_bg.get(status, C["bg"]), fg=s_fg.get(status, C["muted"]),
                          width=8, anchor="center", padx=3, pady=3)
        sbadge.pack(side="left", padx=2)

        # Actions
        act = tk.Frame(r, bg=bg)
        act.pack(side="left", padx=3)
        act.bind("<Enter>", on_enter)
        act.bind("<Leave>", on_leave)

        def make_paid(rid):
            def do():
                with get_db() as conn:
                    conn.execute("UPDATE banners SET status='paid' WHERE id=?", (rid,))
                    conn.commit()
                self.app.refresh()
            return do

        def make_pending(rid):
            def do():
                with get_db() as conn:
                    conn.execute("UPDATE banners SET status='pending' WHERE id=?", (rid,))
                    conn.commit()
                self.app.refresh()
            return do

        def make_del(rid):
            def do():
                if messagebox.askyesno("Delete", "Remove this banner record?"):
                    with get_db() as conn:
                        conn.execute("DELETE FROM banners WHERE id=?", (rid,))
                        conn.commit()
                    self.app.refresh()
            return do

        def make_edit(rrow):
            def do():
                EditBannerDialog(self.app, rrow)
            return do

        def make_dup(rrow):
            def do():
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with get_db() as conn:
                    conn.execute(
                        """INSERT INTO banners
                           (description, width_ft, height_ft, pieces, sqft, price_per_sqft,
                            amount, custom_amount, date_sent, date_added, status, notes,
                            client_name, client_rate, client_amount)
                           VALUES (?,?,?,?,?,?,?,0,?,?,?,?,?,?,?)""",
                        (rrow["description"], rrow["width_ft"], rrow["height_ft"],
                         rrow["pieces"], rrow["sqft"], rrow["price_per_sqft"],
                         rrow["amount"], today_iso(), now, "pending",
                         rrow["notes"], rrow["client_name"], rrow["client_rate"],
                         rrow["client_amount"])
                    )
                    conn.commit()
                self.app.refresh()
            return do

        if status != "paid":
            paid_btn = tk.Button(act, text="✓ Paid", font=font(8), bg=C["green_lt"], fg=C["green"],
                      relief="flat", cursor="hand2", padx=4, pady=1,
                      command=make_paid(row["id"]))
            paid_btn.pack(side="left", padx=1)
            hover_btn(paid_btn, C["green_hv"], C["green_lt"])
        else:
            pend_btn = tk.Button(act, text="↩ Pending", font=font(8), bg=C["orange_lt"], fg=C["orange"],
                      relief="flat", cursor="hand2", padx=4, pady=1,
                      command=make_pending(row["id"]))
            pend_btn.pack(side="left", padx=1)
            hover_btn(pend_btn, C["orange_hv"], C["orange_lt"])

        edit_btn = tk.Button(act, text="✏️", font=font(8), bg=bg, fg=C["muted"],
                  relief="flat", cursor="hand2", padx=3, pady=1,
                  command=make_edit(row))
        edit_btn.pack(side="left", padx=1)
        hover_btn(edit_btn, C["accent_lt"], bg)

        dup_btn = tk.Button(act, text="📋", font=font(8), bg=bg, fg=C["muted"],
                  relief="flat", cursor="hand2", padx=3, pady=1,
                  command=make_dup(row))
        dup_btn.pack(side="left", padx=1)
        hover_btn(dup_btn, C["accent_lt"], bg)

        del_btn = tk.Button(act, text="✕", font=font(8), bg=bg, fg=C["muted2"],
                  relief="flat", cursor="hand2", padx=3, pady=1,
                  command=make_del(row["id"]))
        del_btn.pack(side="left", padx=1)
        hover_btn(del_btn, C["red_lt"], bg)

        if row["notes"]:
            tk.Label(r, text=f"📝 {row['notes']}", font=font(7), bg=bg,
                     fg=C["muted2"], padx=6).pack(side="right")

# ─── Edit Banner Dialog ───────────────────────────────────────────────────────

class EditBannerDialog(tk.Toplevel):
    def __init__(self, app, row):
        super().__init__(app)
        self.app = app
        self.row = row
        self.title("Edit Banner")
        self.geometry("420x580")
        self.resizable(True, True)
        self.minsize(380, 480)
        self.configure(bg=C["white"])
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Edit Banner Job", font=font(13, "bold"),
                 bg=C["white"], fg=C["text"]).pack(pady=(16,4), padx=20, anchor="w")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Scrollable body
        scroll_wrapper = tk.Frame(self, bg=C["white"])
        scroll_wrapper.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_wrapper, bg=C["white"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_wrapper, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=C["white"])
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>",
            lambda ev: canvas.yview_scroll(-1 * (ev.delta // 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        body = tk.Frame(inner, bg=C["white"])
        body.pack(fill="x", padx=20, pady=10)

        tk.Label(body, text="Description", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=0, column=0, columnspan=2, sticky="w")
        self.desc = tk.Entry(body, font=font(10), relief="flat", bg=C["bg"], fg=C["text"],
                             justify="center")
        self.desc.insert(0, self.row["description"] or "")
        self.desc.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=5, pady=(0,6))

        tk.Label(body, text="W (ft)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=0, sticky="w")
        tk.Label(body, text="H (ft)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=1, sticky="w", padx=(8,0))
        self.w_var = tk.StringVar(value=str(self.row["width_ft"] or ""))
        self.h_var = tk.StringVar(value=str(self.row["height_ft"] or ""))
        self.pcs_var = tk.StringVar(value=str(self.row["pieces"] or 1))
        tk.Entry(body, textvariable=self.w_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["text"], justify="center").grid(row=3, column=0, sticky="ew", ipady=5)
        tk.Entry(body, textvariable=self.h_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["text"], justify="center").grid(row=3, column=1, sticky="ew", ipady=5, padx=(8,0), pady=(0,6))

        tk.Label(body, text="Pieces", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=4, column=0, sticky="w")
        tk.Entry(body, textvariable=self.pcs_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["text"], justify="center").grid(row=5, column=0, sticky="ew", ipady=5, pady=(0,6))

        tk.Label(body, text="Client Rate/sqft", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=4, column=1, sticky="w", padx=(8,0))
        self.client_rate_var = tk.StringVar(value=str(self.row["client_rate"] or ""))
        tk.Entry(body, textvariable=self.client_rate_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["orange"], justify="center").grid(row=5, column=1, sticky="ew", ipady=5, padx=(8,0), pady=(0,6))

        tk.Label(body, text="Client Amount (Rs)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=6, column=0, columnspan=2, sticky="w")
        self.client_amt_var = tk.StringVar(value=str(self.row["client_amount"] or ""))
        tk.Entry(body, textvariable=self.client_amt_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["green"], justify="center").grid(row=7, column=0, columnspan=2, sticky="ew", ipady=5, pady=(0,6))

        # Custom amount checkbox
        self.custom_amount_var = tk.IntVar(value=self.row["custom_amount"] or 0)
        tk.Label(body, text="Print Cost (Rs)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=8, column=0, sticky="w")
        self.amount_var = tk.StringVar(value=str(self.row["amount"] or ""))
        self.amount_entry = tk.Entry(body, textvariable=self.amount_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["accent"], justify="center")
        self.amount_entry.grid(row=9, column=0, sticky="ew", ipady=5, pady=(0,6))
        cb = tk.Checkbutton(body, text="Custom price", variable=self.custom_amount_var,
                            font=font(8), bg=C["white"], fg=C["muted"],
                            activebackground=C["white"], command=self._toggle_custom_amount)
        cb.grid(row=8, column=1, sticky="w", padx=(8,0))
        self._toggle_custom_amount()

        tk.Label(body, text="Mail Send (dd/mm/yyyy)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=10, column=0, columnspan=2, sticky="w")
        self.date_entry = tk.Entry(body, font=font(10), relief="flat", bg=C["bg"], fg=C["text"], justify="center")
        self.date_entry.insert(0, fmt_date(self.row["date_sent"]))
        self.date_entry.grid(row=11, column=0, columnspan=2, sticky="ew", ipady=5, pady=(0,6))

        tk.Label(body, text="Notes", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=12, column=0, columnspan=2, sticky="w")
        self.notes = tk.Entry(body, font=font(9), relief="flat", bg=C["bg"], fg=C["text"],
                              justify="center")
        self.notes.insert(0, self.row["notes"] or "")
        self.notes.grid(row=13, column=0, columnspan=2, sticky="ew", ipady=4)

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", pady=(6,0))
        save_btn = tk.Button(self, text="SAVE CHANGES", font=font(10, "bold"),
                  bg=C["accent"], fg="white", relief="flat",
                  cursor="hand2", pady=8, command=self._save)
        save_btn.pack(fill="x", padx=20, pady=12)
        hover_btn(save_btn, "#1d4ed8", C["accent"])

    def _toggle_custom_amount(self):
        if self.custom_amount_var.get():
            self.amount_entry.config(state="normal", bg=C["bg"])
        else:
            self.amount_entry.config(state="disabled", bg=C["border"])

    def _save(self):
        try:
            w = float(self.w_var.get())
            h = float(self.h_var.get())
            pcs = max(1, int(self.pcs_var.get() or 1))
            sqft = round(w * h * pcs, 2)
            price = self.row["price_per_sqft"] or float(get_setting("price_per_sqft") or 50)
        except:
            messagebox.showwarning("Invalid", "Check width, height, pieces values.")
            return
        is_custom = self.custom_amount_var.get()
        if is_custom:
            try:
                amount = float(self.amount_var.get() or 0)
            except:
                messagebox.showwarning("Invalid", "Enter a valid custom amount.")
                return
        else:
            amount = round(sqft * price, 2)
        date_sent = parse_date(self.date_entry.get())
        if not date_sent:
            messagebox.showwarning("Invalid Date", "Enter a valid date (dd/mm/yyyy).")
            return
        try:
            client_amt = float(self.client_amt_var.get() or 0)
        except:
            client_amt = 0
        try:
            client_rate = float(self.client_rate_var.get() or 0)
        except:
            client_rate = 0
        if client_amt == 0 and client_rate > 0 and sqft > 0:
            client_amt = round(sqft * client_rate, 2)
        elif client_rate == 0 and client_amt > 0 and sqft > 0:
            client_rate = round(client_amt / sqft, 2)
        with get_db() as conn:
            conn.execute("""UPDATE banners SET description=?, width_ft=?, height_ft=?, pieces=?,
                            sqft=?, amount=?, custom_amount=?, date_sent=?, notes=?,
                            client_rate=?, client_amount=? WHERE id=?""",
                         (self.desc.get().strip(), w, h, pcs, sqft, amount, is_custom,
                          date_sent, self.notes.get().strip(),
                          client_rate, client_amt, self.row["id"]))
            conn.commit()
        self.app.refresh()
        self.destroy()

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BannerTrackerApp()
    app.mainloop()
