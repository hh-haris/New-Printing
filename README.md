# Modern Printers – Banner Printing Tracker

## Run
```
python banner_tracker.py
```

## Requirements
Python 3.8+  (Tkinter included in most Python installs)
```
pip install reportlab pillow
```

## Features

### Core
- **Sidebar is fully scrollable** — all panels accessible by scrolling
- **Banner table scroll** — only scrolls rows, not headers/filters
- **Date format** is dd/mm/yyyy throughout (labeled "Mail Send")

### Banner Jobs
- Add banner jobs with description (multi-line, expandable), dimensions, pieces, client rate/total
- Edit and duplicate existing jobs
- Auto-marks banners paid oldest-first when payment recorded
- Date range filter and search

### Payments
- Record payments (positive or negative); negative amounts increase Balance Due
- Payment history grouped by month/week with right-aligned delete icons
- Balance Due shows credit when payments exceed billed amount

### Shop Profit Report
- Comprehensive breakdown: totals, margins, per-month stats
- Monthly expandable sections showing jobs, sqft, cost, revenue, profit
- Aging report (overdue 10–29 and 30+ days)

### Settings (expandable)
- Payment reminder days
- **Data Management** (sub-expandable):
  - Export Banner Jobs as PDF (professional template)
  - Export Payment Records as PDF (receipt style)
  - Export Entire Database as CSV
  - Export Entire Database as PDF
  - Clear/reset data options
