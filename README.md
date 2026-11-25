# Vahan + NSE tracker

A single-page dashboard that sets retail registrations (VAHAN Dashboard, MoRTH) against domestic dispatches that
listed OEMs report in their monthly sales filings on NSE. It covers two-wheelers, cars, commercial vehicles and
three-wheelers, and estimates dealer stock in days of retail.

Open `index.html`, or use the GitHub Pages site for this repo. There is no build step.

## Refreshing the data

See [`pipeline/README.md`](pipeline/README.md). In short, on the 1st of each month:

```bash
pip3 install pypdf
python3 pipeline/refresh.py all 2026-11   # report month = the month that just ended
git add -A && git commit -m "Refresh data" && git push
```

## Notes

- Dispatch figures are domestic only, so they compare like for like with Vahan registrations.
- Dealer stock is an estimate built from an assumed opening stock, not a reported number.
- Data sources are public. Honda, Kia, Toyota, Suzuki Motorcycle and TVS three-wheelers do not file on NSE and are excluded from the dispatch charts.
