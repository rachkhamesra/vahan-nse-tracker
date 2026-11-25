#!/usr/bin/env python3
"""Refresh the Dispatch vs Registration Monitor.

  python3 pipeline/refresh.py vahan                 # re-pull the last 4 months of Vahan registrations
  python3 pipeline/refresh.py vahan --full          # re-pull every month since 2022-01
  python3 pipeline/refresh.py dispatch 2026-11      # read November dispatches from NSE sales filings
  python3 pipeline/refresh.py build                 # write both datasets into index.html
  python3 pipeline/refresh.py all 2026-11           # vahan + dispatch + build

Needs: python3, curl, and `pip install pypdf`.
Registrations come from the vahan.ms API (VAHAN Dashboard, MoRTH). Dispatches come from the
monthly sales filings each OEM makes on NSE (corporate-announcements API, then the PDF).
"""
import argparse, datetime as dt, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, "cache")
HTML = os.path.join(ROOT, "index.html")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"
MONTHS3 = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

# dashboard name -> NSE symbol, per segment. Honda, Kia, Toyota, Suzuki Motorcycle do not file on NSE.
NSE = {
    "2W": {"Hero MotoCorp": ["HEROMOTOCO"], "TVS": ["TVSMOTOR"], "Bajaj": ["BAJAJ-AUTO"], "Royal Enfield": ["EICHERMOT"]},
    "CAR": {"Maruti Suzuki": ["MARUTI"], "Tata Motors": ["TMPV"], "Mahindra": ["M%26M"], "Hyundai": ["HYUNDAI"]},
    # Tata CV sat inside Tata Motors Ltd (symbol TMPV after the rename) until the Oct 2025 demerger, then TMCV.
    "CV": {"Tata Motors": ["TMCV", "TMPV"], "Mahindra": ["M%26M"], "Ashok Leyland": ["ASHOKLEY"], "VECV": ["EICHERMOT"]},
    # TVS 3W is left out: its releases state 3W volumes inconsistently and it is a small share of registrations.
    "3W": {"Bajaj": ["BAJAJ-AUTO"], "Mahindra": ["M%26M"]},
}
VAHAN_SEG = {"2W": "2W", "CAR": "CAR", "CV": "CV", "3W": "3W"}


def curl(url, out=None, tries=3):
    cmd = ["curl", "-sS", "-m", "60", "-A", UA, "-H", "accept: application/json", "-H", "referer: https://www.nseindia.in/"]
    if out:
        cmd += ["-o", out]
    for _ in range(tries):
        r = subprocess.run(cmd + [url], capture_output=True)
        if r.returncode == 0 and (out or r.stdout):
            return None if out else r.stdout.decode("utf-8", "replace")
    raise RuntimeError("curl failed: " + url)


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def save(name, obj, **kw):
    with open(os.path.join(DATA, name), "w") as f:
        json.dump(obj, f, **kw)


# ---------------------------------------------------------------- Vahan
def vahan_month(seg, y, m):
    u = f"https://vahan.ms/api/share?level=IN&segment={seg}&fuel=ALL&dim=Maker&power=ALL&year={y}&span=month&month={m}&top=25"
    r = json.loads(curl(u))
    return r["total"], {x["oem"]: x["qty"] for x in r.get("rows", [])}, r["selection"].get("partial", False)


def cmd_vahan(args):
    v = load("vahan.json")
    meta = json.loads(curl("https://vahan.ms/api/meta"))
    last_rev = dt.date.fromisoformat(meta["last_revision"]["date"])
    today_month = (last_rev.year, last_rev.month)
    start = (2022, 1)
    months = []
    y, m = start
    while (y, m) <= today_month:
        months.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    # Vahan restates recent months, so by default refetch only the last 4.
    fetch = months if args.full or v["months"][:1] != months[:1] else months[-4:]
    fetch = [x for x in months if x in fetch]
    # drop a barely started month: a few days of data would make the page's projection meaningless
    partial_days = last_rev.day
    hold = partial_days < args.min_days
    jobs = [(s, mm) for s in VAHAN_SEG for mm in fetch]

    def one(j):
        s, mm = j
        y, m = map(int, mm.split("-"))
        return j, vahan_month(VAHAN_SEG[s], y, m)

    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(one, jobs))
    # extend / overwrite arrays
    allm = months
    for s in VAHAN_SEG:
        names = [k for k in v[s] if k != "T"]
        old = dict(zip(v["months"], v[s]["T"]))
        olds = {n: dict(zip(v["months"], v[s][n])) for n in names}
        for mm in fetch:
            tot, oems, _ = res[(s, mm)]
            old[mm] = tot
            for n in names:
                olds[n][mm] = oems.get(n, 0)
        v[s]["T"] = [old.get(mm, 0) for mm in allm]
        for n in names:
            v[s][n] = [olds[n].get(mm, 0) for mm in allm]
    v["months"] = allm
    if hold:
        # keep the in-progress month out of the page until it has enough days
        print(f"latest Vahan month {allm[-1]} has only {partial_days} days; holding it back (--min-days {args.min_days}).")
        for s in VAHAN_SEG:
            for k in v[s]:
                v[s][k] = v[s][k][:-1]
        v["months"] = allm[:-1]
        v["as_of"] = {"days_done": cal_days(allm[-2]), "days_in_month": cal_days(allm[-2])}
    else:
        v["as_of"] = {"days_done": partial_days if last_rev.month == int(allm[-1][5:]) and last_rev.day < cal_days(allm[-1]) else cal_days(allm[-1]),
                      "days_in_month": cal_days(allm[-1])}
    save("vahan.json", v, separators=(",", ":"))
    print("vahan.json:", v["months"][0], "to", v["months"][-1], v["as_of"])


def cal_days(mm):
    y, m = map(int, mm.split("-"))
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.date(y, m, 1)).days


# ---------------------------------------------------------------- NSE
def nse_list(symbol, d1, d2):
    u = f"https://www.nseindia.in/api/corporate-announcements?index=equities&symbol={symbol}&from_date={d1}&to_date={d2}"
    try:
        return json.loads(curl(u))
    except Exception:
        return []


def pdf_text(path):
    import pypdf, logging
    logging.disable(logging.CRITICAL)
    r = pypdf.PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in r.pages[:6])


def n(s):
    return int(re.sub(r"[^\d]", "", s))


# Each parser returns candidate monthly domestic figures found in one filing.
def p_hero(t, t1):
    return [n(a) for a, b in re.findall(r"Domestic\s+(\d[\d,]{5,})\s+(\d[\d,]{5,})", t1)][:1]


def p_tvs(t, t1):
    out = []
    for r in re.finditer(r"Domestic two[- ]+wheelers?\s+registered(.{0,200})", t1):
        nums = re.findall(r"([\d,]{5,})\s*units", r.group(1))
        if re.search(r"sales\s+of", r.group(1)[:80]) and nums:
            out.append(n(nums[0]))
        elif len(nums) > 1:
            out.append(n(nums[1]))
    return out[:1]


def p_bajaj(t, t1):
    m = re.search(r"DOMESTIC\s+([\d,]+)", t)
    return [n(m.group(1))] if m else []


def p_re(t, t1):
    tm = re.search(r"Total ([\d,]+) ([\d,]+) -?\d+% ([\d,]+) ([\d,]+) -?\d+%", t1)
    ib = re.search(r"International Business.{0,60}?([\d,]{4,}) ([\d,]{4,}) -?\d+% ([\d,]{4,}) ([\d,]{4,}) -?\d+%", t1)
    return [n(tm.group(1)) - n(ib.group(1))] if tm and ib else []


def p_maruti(t, t1):
    m = re.search(r"Total Domestic Passenger Vehicle Sales \(PV\)\s+([\d,]+)", t1)
    return [n(m.group(1))] if m else []


def p_tmpv(t, t1):
    m = re.search(r"PV Domestic(?: \(includes EV\))?\s+([\d,]+)", t1)
    return [n(m.group(1))] if m else []


def p_mm(t, t1):
    m = re.search(r"sold ([\d,]+) vehicles in the domestic market", t1) or re.search(r"domestic sales of ([\d,]+)", t1, re.I)
    return [n(m.group(1))] if m else []


def p_hyundai(t, t1):
    pats = [r"domestic (?:monthly )?sales of ([\d,][\d, ]*\d) units", r"\(domestic: ([\d,][\d, ]*\d) units", r"Domestic sales stood at ([\d,][\d, ]*\d) units"]
    out = []
    for p in pats:
        out += [n(x) for x in re.findall(p, t1, re.I)]
    return out


def p_al(t, t1):
    m = re.search(r"DOMESTIC.*?Total Vehicles ([\d,]+)", t1)
    return [n(m.group(1))] if m else []


def p_tmcv(t, t1):
    m = re.search(r"(?:Total )?CV Domestic\s+([\d,]+)", t1) or re.search(r"SCV cargo and pickup [\d,]+ [\d,]+ [\d.\-]+% (?:[\d,]+ [\d,]+ [\d.\-]+% )?Domestic Sales ([\d,]+)", t1)
    return [n(m.group(1))] if m else []


def p_vecv(t, t1):
    if "Eicher Trucks" not in t1:
        return []
    m = re.search(r"Total Domestic\s+([\d,]+)", t1)
    return [n(m.group(1))] if m else []


def p_mm_cv(t, t1):
    a = re.search(r"LCV\s*<\s*2\s*T\W{0,4}\s+([\d,]+)\s+[\d,]+\s+-?\d+%", t1)
    b = re.search(r"LCV\s*2\s*T\s*[\u2013\u2014-]\s*3\.5\s*T\W{0,4}\s+([\d,]+)\s+[\d,]+\s+-?\d+%", t1)
    return [n(a.group(1)) + n(b.group(1))] if a and b else []


def p_mm_3w(t, t1):
    m = re.search(r"3 Wheelers\s*(?:\(including electric 3?Ws\))?\W{0,6}\s*([\d,]{3,7})\s+[\d,]{3,7}\s+-?\d+%", t1) or re.search(r"\b3W\W{0,4}\s+([\d,]{3,7})\s+[\d,]{3,7}\s+-?\d+%", t1)
    return [n(m.group(1))] if m else []


def p_bajaj_3w(t, t1):
    ms = re.findall(r"DOMESTIC\s+([\d,]+)", t)
    return [n(ms[1])] if len(ms) > 1 else []


def p_tvs_3w(t, t1):
    # domestic 3W = total 3W - international 3W (international total less international 2W)
    tot = re.search(r"registered\s+\d+\s*%\s+increase in sales with\s+([\d,]+) units", t1) or re.search(r"increase in sales with\s+([\d,]+) units", t1)
    two = re.search(r"Total two-wheelers registered.{0,40}?sales\s+of\s+([\d,]+)\s+units", t1)
    intl = re.search(r"Total International Business sales.{0,40}?sales of\s+([\d,]+)\s+units", t1)
    intl2 = re.search(r"International Business.{0,200}?Two-wheelers sales registered.{0,40}?sales of\s+([\d,]+)\s+units", t1)
    if tot and two and intl and intl2:
        return [(n(tot.group(1)) - n(two.group(1))) - (n(intl.group(1)) - n(intl2.group(1)))]
    return []


PARSERS = {("2W", "Hero MotoCorp"): p_hero, ("2W", "TVS"): p_tvs, ("2W", "Bajaj"): p_bajaj, ("2W", "Royal Enfield"): p_re,
           ("CAR", "Maruti Suzuki"): p_maruti, ("CAR", "Tata Motors"): p_tmpv, ("CAR", "Mahindra"): p_mm, ("CAR", "Hyundai"): p_hyundai,
           ("CV", "Tata Motors"): p_tmcv, ("CV", "Mahindra"): p_mm_cv, ("CV", "Ashok Leyland"): p_al, ("CV", "VECV"): p_vecv,
           ("3W", "Bajaj"): p_bajaj_3w, ("3W", "Mahindra"): p_mm_3w}


def cmd_dispatch(args):
    disp = load("dispatch.json")
    y, m = map(int, args.month.split("-"))
    fy, fm = (y + 1, 1) if m == 12 else (y, m + 1)
    d1, d2 = f"01-{fm:02d}-{fy}", f"07-{fm:02d}-{fy}"
    prev = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
    os.makedirs(CACHE, exist_ok=True)
    report = []
    for seg, oems in NSE.items():
        for name, syms in oems.items():
            disp.setdefault(seg, {}).setdefault(name, {})
            items = [x for sym in syms for x in nse_list(sym, d1, d2)]
            files = []
            for x in items:
                u = x.get("attchmntFile") or ""
                if u.endswith(".pdf") and not re.search(r"transcript|newspaper|investor|analyst|ESOP|Reg74|Allot", u, re.I):
                    files.append((x["an_dt"][:11], u))
            files = sorted(set(files))
            prevv = disp[seg][name].get(prev)
            found = None
            for day, u in files:
                fn = os.path.join(CACHE, u.split("/")[-1])
                if not os.path.exists(fn) or os.path.getsize(fn) < 1000:
                    curl(u, out=fn)
                try:
                    t = pdf_text(fn)
                except Exception:
                    continue
                cands = PARSERS[(seg, name)](t, re.sub(r"\s+", " ", t))
                for c in cands:
                    # a monthly figure sits near the previous month; this screens out quarterly totals
                    if prevv is None or 0.4 < c / prevv < 2.5:
                        found = (c, u.split("/")[-1])
                        break
                if found:
                    break
            if found:
                disp[seg][name][args.month] = found[0]
                report.append((seg + " " + name, found[0], found[1], "ok"))
            else:
                report.append((seg + " " + name, None, f"{len(files)} filings checked in {d1}..{d2}", "MISSING: not filed yet, or a new layout. Check by hand."))
    save("dispatch.json", disp, indent=1)
    for r in report:
        print(f"{r[0]:20} {str(r[1]):>9}  {r[3]:8} {r[2]}")


# ---------------------------------------------------------------- build
def swap(html, tag, body):
    a, b = html.index(f"// @@{tag}_START"), html.index(f"// @@{tag}_END")
    head = html[a:html.index("\n", a) + 1]
    return html[:a] + head + body + "\n" + html[b:]


def cmd_build(args):
    v = load("vahan.json")
    disp = load("dispatch.json")
    as_of = v.pop("as_of", {"days_done": 25, "days_in_month": 30})
    start = "2025-04"
    # dispatch arrays run from Apr-25 to the latest month that every OEM has
    lastm = None
    allm = sorted({m for seg in disp.values() for o in seg.values() for m in o})
    for m in allm:
        if all(m in o for seg in disp.values() for o in seg.values()):
            lastm = m
    months = [m for m in allm if start <= m <= lastm]
    lines = ["const DISP={"]
    for seg, oems in disp.items():
        lines.append(f'"{seg}":{{')
        for name, d in oems.items():
            arr = [d[m] for m in months]
            lines.append(f'"{name}":{{v:"{name}",d:{json.dumps(arr, separators=(",", ":"))}}},')
        lines.append("},")
    lines.append("};")
    html = open(HTML).read()
    html = swap(html, "DISP", "// Domestic dispatches per OEM from the monthly sales filings on NSE, from Apr-25. Written by pipeline/refresh.py.\n" + "\n".join(lines))
    data = "const DATA=" + json.dumps(v, separators=(",", ":")) + f";\nconst AS_OF={json.dumps(as_of, separators=(',', ':'))};"
    html = swap(html, "DATA", data)
    open(HTML, "w").write(html)
    print("index.html updated. Vahan to", v["months"][-1], "| dispatches to", lastm, "| as_of", as_of)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("vahan"); a.add_argument("--full", action="store_true"); a.add_argument("--min-days", type=int, default=10)
    b = sp.add_parser("dispatch"); b.add_argument("month", help="report month, e.g. 2026-11")
    sp.add_parser("build")
    c = sp.add_parser("all"); c.add_argument("month"); c.add_argument("--full", action="store_true"); c.add_argument("--min-days", type=int, default=10)
    args = ap.parse_args()
    if args.cmd in ("vahan", "all"):
        cmd_vahan(args)
    if args.cmd in ("dispatch", "all"):
        cmd_dispatch(args)
    if args.cmd in ("build", "all"):
        cmd_build(args)


if __name__ == "__main__":
    main()
