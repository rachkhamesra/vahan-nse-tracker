# Refreshing the dashboard

Two data sources, both read straight from the source, no logins.

| Data | Source | Stored in |
|---|---|---|
| Registrations | vahan.ms API (VAHAN Dashboard, MoRTH), all-India, by maker | `data/vahan.json` |
| Dispatches | Monthly sales filings each OEM makes on NSE (announcements API, then the PDF) | `data/dispatch.json` |

`index.html` embeds both. `refresh.py build` rewrites the blocks between the `@@DATA` and `@@DISP` markers.

## Setup (once)

```bash
pip3 install pypdf
```

## 1 December routine (November dispatches)

```bash
python3 pipeline/refresh.py all 2026-11
```

That pulls Vahan for the last four months (Vahan restates recent months), reads November dispatches from
each OEM's filings, and rebuilds `index.html`. Then republish the page.

Each dispatch line prints the filing it was read from. A line marked `MISSING` means the OEM has not
filed yet (rerun later) or changed its layout (read the PDF by hand and add the number to `data/dispatch.json`).
Every value is screened against the previous month, so a quarterly total is rejected instead of accepted.

Run steps separately if you prefer: `vahan`, `dispatch 2026-11`, `build`.

## Notes

- Eight OEMs file monthly on NSE: Hero, TVS, Bajaj, Eicher (Royal Enfield), Maruti, Tata Motors PV, Mahindra, Hyundai.
  Honda, Kia, Toyota and Suzuki Motorcycle do not, so they are not in the dispatch charts.
- Filings appear on the 1st to 3rd of the month. Tata Motors passenger vehicles sit under the `TMPV` symbol (before Oct 2025 the
  same filings were under Tata Motors Ltd and show up under that symbol's history too).
- A Vahan month with fewer than 10 days of data is held back (`--min-days`), so the page never projects from a day or two of registrations.
- Tested by re-reading Oct-26, Sep-26, Mar-26, Dec-25 and Jun-25 from NSE: all 40 values matched the stored series.
- Not generalised yet: the seasonality, YoY and December charts are written around November 2026 as the month in progress.
  The stock chart adapts (it drops the scenario bar once the month has dispatches). Once December has 10 or more days of data
  the page needs one more pass.
- `cache/` holds downloaded PDFs and can be deleted at any time.

## Automatic daily refresh

`.github/workflows/refresh.yml` runs every day at 07:30 IST (Vahan rebuilds around 04:00 IST). It pulls the latest
registrations, rebuilds `index.html`, and commits and publishes only if something changed. On the 1st to 5th of the
month it also tries last month's NSE sales filings. NSE can throttle cloud servers, so that step is allowed to fail;
if a company shows as missing, run `python3 pipeline/refresh.py dispatch YYYY-MM` locally and push.
Run it on demand from the Actions tab with "Run workflow".
