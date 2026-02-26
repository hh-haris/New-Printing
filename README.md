# Modern Printers – Banner Printing Tracker

## Run
```
python banner_tracker.py
```

## Requirements
Python 3.8+  (Tkinter included in most Python installs)

## New Features in This Version

### Core Fixes
- **Sidebar is now fully scrollable** — all panels accessible by scrolling
- **Banner table scroll is fixed** — only scrolls rows, not headers/filters
- **Date format** is dd/mm/yyyy throughout

### New Features
1. **Auto Payment Mark** — When you record a payment, banners are auto-marked paid (oldest first); partial payment marks banner as "partial"
2. **Expandable Payment History** — Click a month to expand weekly/daily breakdown
3. **Price Change Prompt** — Changing the rate asks whether to update old banners or just future ones
4. **Pieces per Banner** — Add number of pieces (default 1); sqft auto-multiplies
5. **Auto Date** — Today's date is pre-filled (editable in dd/mm/yyyy)
6. **Payment Reminder** — On startup, warns if any banner is unpaid 10+ days (configurable)
7. **Carry-Forward Balance** — Enter a negative amount to track debt owed to printer
8. **Client Profit Tracking** — Set client name + rate or total per job; auto-calculates the other
9. **Shop Profit Report** — See total print cost, client revenue, net profit, best month, aging report
10. **Date Range Filter** — Filter banner list by custom date range
11. **Edit Banner** — Edit all fields of any existing banner
12. **Aging Report** — Shows overdue 10–29 day and 30+ day jobs in profit panel
13. **Negative Payment** — Enter negative amounts to record debt owed to printer

### UI Changes
- Title: **Modern Printers** with subtitle *Banner Printing Tracker*
- Clean white theme, no dark backgrounds
- Summary bar shows: Print Cost, Paid, Balance, Carry Forward, Client Revenue, Net Profit
