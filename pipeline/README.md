# How the data gets to the page

The page (`index.html`) loads two files every time it opens and every 15 minutes: `data/registrations.json` and
`data/dispatch.json`. Nothing is baked into the page, so updating those files updates the site.

| File | Source | Updated by |
|---|---|---|
| `data/registrations.json` | The official VAHAN dashboard, vahan.parivahan.gov.in (MoRTH): all-India registrations by maker, month by month, for two-wheelers, electric two-wheelers, cars, commercial vehicles and three-wheelers | The scheduled job on the owner's Mac (below), twice a day |
| `data/dispatch.json` | Monthly sales filings each company makes on NSE | GitHub Actions, on the 1st to 5th of each month |

## Registrations: the official VAHAN dashboard

`python3 pipeline/refresh.py portal` drives the dashboard's own form: an unfiltered query to start a session, then the
filter panel's Refresh with the segment's filters, then every page of makers, once per calendar year. The current year
takes about a minute; `--full` re-pulls 2022 onward. Segments use the dashboard's filters:

- Two-wheelers: vehicle categories 2WIC, 2WN, 2WT. Electric two-wheelers: the same categories with the Pure EV and
  Electric (BOV) fuel types.
- Cars: classes Motor Car, Motor Cab, Maxi Cab.
- Commercial: classes Goods Carrier, Articulated Vehicle, Bus, School Bus, Educational Institution Bus, Omni Bus (both).
- Three-wheelers: categories 3WIC, 3WN, 3WT.

Legal names are grouped to display names in `SEGMENTS` in `refresh.py`; every other maker rolls into the segment total.
The portal resets connections from cloud servers, which is why this runs on a Mac and not on GitHub.

### The Mac job

`pipeline/mac/install.sh` clones the repo to `~/vahan-nse-tracker`, installs a launch agent, and runs it at 08:00 and
20:30 (and at login). Each run pulls the portal, writes `data/registrations.json`, commits and pushes if anything
changed. A run on the morning counts data through yesterday; an evening run counts through today. If the Mac is asleep
at the scheduled time, launchd runs the job when it wakes. Logs: `~/Library/Logs/vahan-nse-tracker.log`.
Stop it with `launchctl bootout gui/$(id -u)/com.vahan-nse-tracker.refresh`.

## Dispatches: NSE filings

`python3 pipeline/refresh.py dispatch 2026-11` finds each company's sales filing from the 1st to 7th of the next month,
reads the PDF and takes the domestic figure. Every value is screened against the previous month, so a quarterly total is
rejected. A line marked `MISSING` means the company has not filed yet or changed its layout; run it again later or add the
number to `pipeline/data/dispatch.json` by hand. Reading the PDFs needs `pip install pypdf`.
