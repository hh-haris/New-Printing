"""
Modern Printers - Banner Printing Tracker
Run: python banner_tracker.py
Requires: pip install pillow  (optional)
Data stored in: ~/banner_tracker.db (SQLite)
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
import csv
import os
from datetime import datetime, date, timedelta
from pathlib import Path

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
        conn.execute("INSERT OR IGNORE INTO settings VALUES ('carry_forward', '0')")
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

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "SF Pro Display" if "darwin" in os.sys.platform else "Ubuntu"

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
    """Accept dd/mm/yyyy or yyyy-mm-dd"""
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except:
            pass
    return s

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
    """Mark banners as paid oldest-first up to total_paid amount."""
    price = float(get_setting("price_per_sqft") or 50)
    with get_db() as conn:
        banners = conn.execute(
            "SELECT id, amount, status FROM banners ORDER BY date_sent ASC, id ASC"
        ).fetchall()
        remaining = total_paid
        for b in banners:
            amt = b["amount"] if b["amount"] else 0
            if remaining <= 0:
                # Mark rest as pending if previously paid by auto
                break
            if remaining >= amt:
                conn.execute("UPDATE banners SET status='paid' WHERE id=?", (b["id"],))
                remaining -= amt
            else:
                conn.execute("UPDATE banners SET status='partial' WHERE id=?", (b["id"],))
                remaining = 0
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

# ─── Main Application ─────────────────────────────────────────────────────────

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

        # Right: price setting
        tf = tk.Frame(header, bg=C["white"])
        tf.place(relx=1.0, x=-24, y=18, anchor="ne")
        tk.Label(tf, text="Price / sq ft (Rs)", font=font(9), bg=C["white"], fg=C["muted"]).pack(side="left", padx=(0,6))
        self.price_entry = tk.Entry(tf, textvariable=self.price_var, width=8,
                                    font=font(11, "bold"), relief="flat",
                                    bg=C["accent_lt"], fg=C["accent"],
                                    insertbackground=C["accent"], justify="center")
        self.price_entry.pack(side="left")
        self.price_entry.bind("<Return>", lambda e: self._save_price())
        self.price_entry.bind("<FocusOut>", lambda e: self._save_price())
        tk.Label(tf, text="↵ save", font=font(8), bg=C["white"], fg=C["muted2"]).pack(side="left", padx=(4,0))

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

    def _bind_sidebar_scroll(self):
        self._sidebar_canvas.bind_all("<MouseWheel>", self._on_sidebar_scroll)

    def _unbind_sidebar_scroll(self):
        self._sidebar_canvas.unbind_all("<MouseWheel>")

    def _on_sidebar_scroll(self, event):
        self._sidebar_canvas.yview_scroll(-1 * (event.delta // 120), "units")

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

# ─── Summary Bar ─────────────────────────────────────────────────────────────

class SummaryBar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg"])
        self.cards = {}
        defs = [
            ("total_billed",   "Total Print Cost",   C["accent"],  C["accent_lt"]),
            ("total_paid",     "Total Paid",          C["green"],   C["green_lt"]),
            ("balance_due",    "Balance Due",         C["red"],     C["red_lt"]),
            ("carry_fwd",      "Carry Forward",       C["purple"],  C["purple_lt"]),
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
        carry = float(get_setting("carry_forward") or 0)
        effective_paid = total_paid + carry
        balance_due = max(0, total_billed - effective_paid)
        total_revenue = sum((b["client_amount"] or 0) for b in banners)
        net_profit = total_revenue - total_billed
        paid_count = sum(1 for b in banners if b["status"] == "paid")

        self.cards["total_billed"].set(fmt_rs(total_billed))
        self.cards["total_paid"].set(fmt_rs(total_paid), f"{paid_count} banners paid")
        self.cards["balance_due"].set(fmt_rs(balance_due))
        cf_label = f"Debt: {fmt_rs(abs(carry))}" if carry < 0 else f"Credit: {fmt_rs(carry)}"
        self.cards["carry_fwd"].set(cf_label)
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

        # Description
        tk.Label(body, text="Description", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(2,1))
        self.desc = tk.Entry(body, font=font(10), relief="flat",
                             bg=C["bg"], fg=C["text"], insertbackground=C["accent"])
        self.desc.grid(row=1, column=0, columnspan=4, sticky="ew", ipady=5)
        self.desc.insert(0, "e.g. Eid Sale Banner")
        self.desc.bind("<FocusIn>", lambda e: self._clear_ph())

        # Width, Height, Pieces
        tk.Label(body, text="W (ft)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=0, sticky="w", pady=(6,1))
        tk.Label(body, text="H (ft)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=1, sticky="w", pady=(6,1), padx=(6,0))
        tk.Label(body, text="Pcs", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=2, sticky="w", pady=(6,1), padx=(6,0))
        tk.Label(body, text="Client", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=2, column=3, sticky="w", pady=(6,1), padx=(6,0))

        self.w_var = tk.StringVar()
        self.h_var = tk.StringVar()
        self.pcs_var = tk.StringVar(value="1")
        self.client_var = tk.StringVar()

        self.w_entry = tk.Entry(body, textvariable=self.w_var, font=font(10), relief="flat",
                                bg=C["bg"], fg=C["text"], width=6, justify="center")
        self.h_entry = tk.Entry(body, textvariable=self.h_var, font=font(10), relief="flat",
                                bg=C["bg"], fg=C["text"], width=6, justify="center")
        self.pcs_entry = tk.Entry(body, textvariable=self.pcs_var, font=font(10), relief="flat",
                                  bg=C["bg"], fg=C["text"], width=4, justify="center")
        self.client_entry = ttk.Combobox(body, textvariable=self.client_var, font=font(9),
                                         width=8, values=get_client_names())
        self.w_entry.grid(row=3, column=0, sticky="ew", ipady=5)
        self.h_entry.grid(row=3, column=1, sticky="ew", ipady=5, padx=(6,0))
        self.pcs_entry.grid(row=3, column=2, sticky="ew", ipady=5, padx=(6,0))
        self.client_entry.grid(row=3, column=3, sticky="ew", ipady=5, padx=(6,0))
        self.client_entry.bind("<<ComboboxSelected>>", self._on_client_selected)

        self.w_var.trace_add("write", lambda *a: self._update_preview())
        self.h_var.trace_add("write", lambda *a: self._update_preview())
        self.pcs_var.trace_add("write", lambda *a: self._update_preview())

        # Client Rate / Custom Amount
        tk.Label(body, text="Client Rate/sqft", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6,1))
        tk.Label(body, text="Client Total (auto)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=4, column=2, columnspan=2, sticky="w", pady=(6,1), padx=(6,0))

        self.client_rate_var = tk.StringVar()
        self.client_total_var = tk.StringVar()
        self.client_rate_entry = tk.Entry(body, textvariable=self.client_rate_var, font=font(10),
                                          relief="flat", bg=C["bg"], fg=C["orange"],
                                          width=8, justify="center")
        self.client_total_entry = tk.Entry(body, textvariable=self.client_total_var, font=font(10),
                                           relief="flat", bg=C["bg"], fg=C["green"],
                                           width=8, justify="center")
        self.client_rate_entry.grid(row=5, column=0, columnspan=2, sticky="ew", ipady=5)
        self.client_total_entry.grid(row=5, column=2, columnspan=2, sticky="ew", ipady=5, padx=(6,0))
        self.client_rate_var.trace_add("write", lambda *a: self._update_client_total())
        self.client_total_var.trace_add("write", lambda *a: self._update_client_rate())
        self._updating_client = False

        # Date
        tk.Label(body, text="Date Sent (dd/mm/yyyy)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(6,1))
        self.date_entry = tk.Entry(body, font=font(10), relief="flat",
                                   bg=C["bg"], fg=C["text"], justify="center")
        self.date_entry.insert(0, today_str())
        self.date_entry.grid(row=7, column=0, columnspan=4, sticky="ew", ipady=5)

        # Notes
        tk.Label(body, text="Notes (optional)", font=font(8), bg=C["white"], fg=C["muted"]).grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(6,1))
        self.notes_entry = tk.Entry(body, font=font(9), relief="flat", bg=C["bg"], fg=C["text"])
        self.notes_entry.grid(row=9, column=0, columnspan=4, sticky="ew", ipady=4)

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)
        body.columnconfigure(3, weight=1)

        # Quick size presets
        qf = tk.Frame(self, bg=C["white"])
        qf.pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(qf, text="Quick sizes:", font=font(7), bg=C["white"], fg=C["muted2"]).pack(side="left")
        for size_label, sw, sh in [("2×3", 2, 3), ("3×6", 3, 6), ("4×8", 4, 8), ("5×10", 5, 10), ("8×12", 8, 12)]:
            def make_set(wv, hv):
                def do():
                    self.w_var.set(str(wv))
                    self.h_var.set(str(hv))
                return do
            tk.Button(qf, text=size_label, font=font(7), bg=C["bg"], fg=C["muted"],
                      relief="flat", cursor="hand2", padx=6, pady=1,
                      command=make_set(sw, sh)).pack(side="left", padx=2)

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
        for entry in [self.desc, self.w_entry, self.h_entry, self.pcs_entry,
                       self.date_entry, self.notes_entry]:
            entry.bind("<Return>", lambda e: self._add())

    def _clear_ph(self):
        if self.desc.get() == "e.g. Eid Sale Banner":
            self.desc.delete(0, "end")

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
        desc = self.desc.get().strip()
        if not desc or desc == "e.g. Eid Sale Banner":
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
        client = self.client_var.get().strip()
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
                 notes, client, client_rate, client_amount)
            )
            conn.commit()
        self.desc.delete(0, "end")
        self.w_var.set("")
        self.h_var.set("")
        self.pcs_var.set("1")
        self.client_var.set("")
        self.client_rate_var.set("")
        self.client_total_var.set("")
        self.notes_entry.delete(0, "end")
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, today_str())
        self.preview.config(text="Enter size to preview amount", bg=C["bg"], fg=C["muted"])
        self.app.refresh()
        self._show_success(f"✓ Added: {desc}")
        self._refresh_client_list()

    def _show_success(self, msg):
        self.success_label.config(text=msg, bg=C["green_lt"], pady=4)
        self.after(3000, lambda: self.success_label.config(text="", bg=C["white"], pady=0))

    def _on_client_selected(self, event=None):
        client = self.client_var.get().strip()
        if client:
            rate = get_last_client_rate(client)
            if rate and not self.client_rate_var.get().strip():
                self.client_rate_var.set(str(rate))

    def _refresh_client_list(self):
        self.client_entry['values'] = get_client_names()

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

        tk.Label(body, text="Amount (Rs) — use negative for debt owed",
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
                        tk.Label(r, text=f"    {fmt_date(row['date_paid'])}", font=font(8),
                                 bg=C["white"], fg=C["muted"]).pack(side="left", padx=4)
                        tk.Label(r, text=fmt_rs(row["amount"]), font=font(9, "bold"),
                                 bg=C["white"], fg=C["green"] if row["amount"] >= 0 else C["red"]).pack(side="right", padx=4)
                        if row["notes"]:
                            tk.Label(r, text=row["notes"], font=font(7),
                                     bg=C["white"], fg=C["muted2"]).pack(side="right", padx=4)

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

                        tk.Button(r, text="✕", font=font(8), bg=C["white"], fg=C["muted2"],
                                  relief="flat", cursor="hand2",
                                  command=make_del(row["id"])).pack(side="right")

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

        tk.Label(self.result_frame, text=msg, font=font(9), bg=bg, fg=fg,
                 justify="left", anchor="w", padx=10, pady=8, wraplength=300).pack(fill="x")

# ─── Shop Profit Panel ────────────────────────────────────────────────────────

class ShopProfitPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📊  Shop Profit Report", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        self.report_frame = tk.Frame(self, bg=C["white"])
        self.report_frame.pack(fill="x", padx=14, pady=8)

    def refresh(self):
        for w in self.report_frame.winfo_children():
            w.destroy()

        with get_db() as conn:
            banners = conn.execute("SELECT * FROM banners ORDER BY date_sent DESC").fetchall()
            payments = conn.execute("SELECT SUM(amount) as s FROM payments").fetchone()

        if not banners:
            tk.Label(self.report_frame, text="No jobs recorded yet.", font=font(8),
                     bg=C["white"], fg=C["muted2"]).pack(anchor="w")
            return

        total_print_cost = sum(b["amount"] for b in banners)
        total_client_rev = sum((b["client_amount"] or 0) for b in banners)
        total_paid = float(payments["s"] or 0)
        profit = total_client_rev - total_print_cost

        # Best month
        month_rev = {}
        for b in banners:
            try:
                dt = datetime.strptime(b["date_sent"][:10], "%Y-%m-%d")
                mk = dt.strftime("%b %Y")
                month_rev[mk] = month_rev.get(mk, 0) + (b["client_amount"] or 0)
            except:
                pass

        best_month = max(month_rev, key=month_rev.get) if month_rev else "—"

        # Aging
        overdue_10 = []
        overdue_30 = []
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

        rows_data = [
            ("Print Cost (Total)", fmt_rs(total_print_cost), C["accent"]),
            ("Client Revenue", fmt_rs(total_client_rev), C["orange"]),
            ("Net Profit", fmt_rs(profit), C["green"] if profit >= 0 else C["red"]),
            ("Paid to Printer", fmt_rs(total_paid), C["purple"]),
            ("Balance Owed", fmt_rs(max(0, total_print_cost - total_paid)), C["red"]),
            ("Best Month", best_month, C["text"]),
            ("Overdue 10–29 days", str(len(overdue_10)) + " jobs", C["orange"]),
            ("Overdue 30+ days", str(len(overdue_30)) + " jobs", C["red"]),
        ]

        for label, value, fg in rows_data:
            r = tk.Frame(self.report_frame, bg=C["white"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, font=font(8), bg=C["white"], fg=C["muted"]).pack(side="left")
            tk.Label(r, text=value, font=font(9, "bold"), bg=C["white"], fg=fg).pack(side="right")

# ─── Settings Panel ───────────────────────────────────────────────────────────

class SettingsPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["white"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.app = app
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["white"], pady=10, padx=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙️  Settings", font=font(11, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["white"])
        body.pack(fill="x", padx=14, pady=8)

        # Reminder days
        tk.Label(body, text="Payment reminder after (days)", font=font(8),
                 bg=C["white"], fg=C["muted"]).grid(row=0, column=0, sticky="w", pady=(2,1))
        self.reminder_var = tk.StringVar(value=get_setting("reminder_days") or "10")
        re = tk.Entry(body, textvariable=self.reminder_var, font=font(10), relief="flat",
                      bg=C["bg"], fg=C["text"], width=6, justify="center")
        re.grid(row=0, column=1, sticky="ew", ipady=4, padx=(8,0))

        # Carry forward
        tk.Label(body, text="Auto Carry-Forward Balance (Rs)", font=font(8),
                 bg=C["white"], fg=C["muted"]).grid(row=1, column=0, sticky="w", pady=(8,1))
        tk.Label(body, text="(negative = debt on us)", font=font(7),
                 bg=C["white"], fg=C["muted2"]).grid(row=2, column=0, sticky="w")
        self.carry_var = tk.StringVar(value=get_setting("carry_forward") or "0")
        ce = tk.Entry(body, textvariable=self.carry_var, font=font(10), relief="flat",
                      bg=C["bg"], fg=C["text"], width=10, justify="center")
        ce.grid(row=1, column=1, rowspan=2, sticky="ew", ipady=4, padx=(8,0))

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)

        tk.Button(self, text="SAVE SETTINGS", font=font(9, "bold"),
                  bg=C["accent_lt"], fg=C["accent"], relief="flat",
                  cursor="hand2", pady=6, command=self._save).pack(fill="x", padx=14, pady=8)

        # ── Data Management ──
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        dm_hdr = tk.Frame(self, bg=C["white"], pady=6, padx=14)
        dm_hdr.pack(fill="x")
        tk.Label(dm_hdr, text="🗑️  Data Management", font=font(9, "bold"),
                 bg=C["white"], fg=C["muted"]).pack(side="left")

        dm_body = tk.Frame(self, bg=C["white"])
        dm_body.pack(fill="x", padx=14, pady=(0, 8))

        clr_rec_btn = tk.Button(dm_body, text="Clear All Banner Records", font=font(8, "bold"),
                  bg=C["orange_lt"], fg=C["orange"], relief="flat",
                  cursor="hand2", pady=5, command=self._clear_banners)
        clr_rec_btn.pack(fill="x", pady=(0, 4))
        hover_btn(clr_rec_btn, C["orange_hv"], C["orange_lt"])

        clr_pay_btn = tk.Button(dm_body, text="Clear All Payments", font=font(8, "bold"),
                  bg=C["orange_lt"], fg=C["orange"], relief="flat",
                  cursor="hand2", pady=5, command=self._clear_payments)
        clr_pay_btn.pack(fill="x", pady=(0, 4))
        hover_btn(clr_pay_btn, C["orange_hv"], C["orange_lt"])

        clr_all_btn = tk.Button(dm_body, text="⚠  Reset Entire Database", font=font(8, "bold"),
                  bg=C["red_lt"], fg=C["red"], relief="flat",
                  cursor="hand2", pady=5, command=self._clear_all)
        clr_all_btn.pack(fill="x")
        hover_btn(clr_all_btn, C["red_hv"], C["red_lt"])

    def _save(self):
        try:
            days = int(self.reminder_var.get())
            set_setting("reminder_days", days)
        except:
            pass
        try:
            carry = float(self.carry_var.get())
            set_setting("carry_forward", carry)
        except:
            pass
        self.app.refresh()
        messagebox.showinfo("Saved", "Settings saved successfully.")

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
                messagebox.showinfo("Cleared", f"All {count} banner record(s) have been deleted.")

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
                messagebox.showinfo("Cleared", f"All {count} payment record(s) have been deleted.")

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
                messagebox.showinfo("Database Reset", "All data has been cleared.")

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

        export_btn = tk.Button(fbar, text="📥 Export CSV", font=font(8), bg=C["accent_lt"],
                    fg=C["accent"], relief="flat", cursor="hand2", padx=8, pady=3,
                    command=self._export_csv)
        export_btn.pack(side="left", padx=(0, 8))
        hover_btn(export_btn, C["accent_hv"], C["accent_lt"])

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
        cols = [("#", 3), ("Description", 18), ("Client", 8), ("Date", 10),
                ("Size", 9), ("Sq Ft", 7), ("Print Cost", 9), ("Client Rev", 9),
                ("Status", 8), ("Actions", 12)]
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
        self.filter_from = parse_date(self.from_var.get()) if self.from_var.get().strip() else ""
        self.filter_to = parse_date(self.to_var.get()) if self.to_var.get().strip() else ""
        self.refresh()

    def _clear_date_filter(self):
        self.filter_from = ""
        self.filter_to = ""
        self.from_var.set("")
        self.to_var.set("")
        self.refresh()

    def _export_csv(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"banner_jobs_{today_iso()}.csv"
        )
        if not filepath:
            return
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, description, client_name, date_sent, width_ft, height_ft, "
                "pieces, sqft, price_per_sqft, amount, client_rate, client_amount, "
                "status, notes FROM banners ORDER BY date_sent DESC, id DESC"
            ).fetchall()
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Description", "Client", "Date Sent", "Width (ft)",
                             "Height (ft)", "Pieces", "Sq Ft", "Price/SqFt",
                             "Print Cost", "Client Rate", "Client Amount",
                             "Status", "Notes"])
            for row in rows:
                writer.writerow([row["id"], row["description"], row["client_name"],
                                 fmt_date(row["date_sent"]), row["width_ft"],
                                 row["height_ft"], row["pieces"], row["sqft"],
                                 row["price_per_sqft"], row["amount"],
                                 row["client_rate"], row["client_amount"],
                                 row["status"], row["notes"]])
        messagebox.showinfo("Exported", f"Successfully exported {len(rows)} records to:\n{filepath}")

    def _highlight_filter(self):
        for k, btn in self.filter_btns.items():
            btn.config(bg=C["accent"] if k == self.filter_status else C["bg"],
                       fg="white" if k == self.filter_status else C["muted"])

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
        self._highlight_filter()
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
            ((row["client_name"] or "")[:8], 8, C["muted"], "normal"),
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
        self.geometry("380x480")
        self.resizable(False, False)
        self.configure(bg=C["white"])
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Edit Banner Job", font=font(13, "bold"),
                 bg=C["white"], fg=C["text"]).pack(pady=(16,4), padx=20, anchor="w")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["white"])
        body.pack(fill="x", padx=20, pady=10)

        tk.Label(body, text="Description", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=0, column=0, columnspan=2, sticky="w")
        self.desc = tk.Entry(body, font=font(10), relief="flat", bg=C["bg"], fg=C["text"])
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

        tk.Label(body, text="Client Name", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=6, column=0, sticky="w")
        tk.Label(body, text="Client Amount (Rs)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=6, column=1, sticky="w", padx=(8,0))
        self.client_var = tk.StringVar(value=self.row["client_name"] or "")
        self.client_amt_var = tk.StringVar(value=str(self.row["client_amount"] or ""))
        tk.Entry(body, textvariable=self.client_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["text"]).grid(row=7, column=0, sticky="ew", ipady=5)
        tk.Entry(body, textvariable=self.client_amt_var, font=font(10), relief="flat",
                 bg=C["bg"], fg=C["text"], justify="center").grid(row=7, column=1, sticky="ew", ipady=5, padx=(8,0), pady=(0,6))

        tk.Label(body, text="Date Sent (dd/mm/yyyy)", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=8, column=0, columnspan=2, sticky="w")
        self.date_entry = tk.Entry(body, font=font(10), relief="flat", bg=C["bg"], fg=C["text"], justify="center")
        self.date_entry.insert(0, fmt_date(self.row["date_sent"]))
        self.date_entry.grid(row=9, column=0, columnspan=2, sticky="ew", ipady=5, pady=(0,6))

        tk.Label(body, text="Notes", font=font(8), bg=C["white"], fg=C["muted"]).grid(row=10, column=0, columnspan=2, sticky="w")
        self.notes = tk.Entry(body, font=font(9), relief="flat", bg=C["bg"], fg=C["text"])
        self.notes.insert(0, self.row["notes"] or "")
        self.notes.grid(row=11, column=0, columnspan=2, sticky="ew", ipady=4)

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", pady=(6,0))
        save_btn = tk.Button(self, text="SAVE CHANGES", font=font(10, "bold"),
                  bg=C["accent"], fg="white", relief="flat",
                  cursor="hand2", pady=8, command=self._save)
        save_btn.pack(fill="x", padx=20, pady=12)
        hover_btn(save_btn, "#1d4ed8", C["accent"])

    def _save(self):
        try:
            w = float(self.w_var.get())
            h = float(self.h_var.get())
            pcs = max(1, int(self.pcs_var.get() or 1))
            sqft = round(w * h * pcs, 2)
            price = self.row["price_per_sqft"] or float(get_setting("price_per_sqft") or 50)
            amount = round(sqft * price, 2)
        except:
            messagebox.showwarning("Invalid", "Check width, height, pieces values.")
            return
        date_sent = parse_date(self.date_entry.get())
        try:
            client_amt = float(self.client_amt_var.get() or 0)
        except:
            client_amt = 0
        client_rate = round(client_amt / sqft, 2) if sqft > 0 else 0
        with get_db() as conn:
            conn.execute("""UPDATE banners SET description=?, width_ft=?, height_ft=?, pieces=?,
                            sqft=?, amount=?, date_sent=?, notes=?, client_name=?,
                            client_rate=?, client_amount=? WHERE id=?""",
                         (self.desc.get().strip(), w, h, pcs, sqft, amount, date_sent,
                          self.notes.get().strip(), self.client_var.get().strip(),
                          client_rate, client_amt, self.row["id"]))
            conn.commit()
        self.app.refresh()
        self.destroy()

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BannerTrackerApp()
    app.mainloop()
