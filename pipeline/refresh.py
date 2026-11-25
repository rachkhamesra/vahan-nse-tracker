#!/usr/bin/env python3
"""Refresh the Vahan + NSE tracker.

  python3 pipeline/refresh.py portal                # registrations from the official VAHAN dashboard (current year)
  python3 pipeline/refresh.py portal --full         # ...every year since 2022
  python3 pipeline/refresh.py dispatch 2026-11      # read a month's dispatches from NSE sales filings
  python3 pipeline/refresh.py publish               # write data/registrations.json and data/dispatch.json for the page
                                                    # (--only registrations | dispatch to write just one)

Registrations come from the VAHAN dashboard itself (vahan.parivahan.gov.in), the government source, by driving the
dashboard's own form. It resets connections from cloud servers, so `portal` has to run from an ordinary connection
(see pipeline/mac/). Dispatches come from the monthly sales filings each company makes on NSE and can run anywhere.

Needs: python3 and curl. Reading the NSE PDFs also needs `pip install pypdf`.
"""
import argparse, datetime as dt, html as htmllib, json, os, re, subprocess, sys, time
import http.cookiejar, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")            # working stores
PUB = os.path.join(ROOT, "data")             # files the page loads
CACHE = os.path.join(HERE, "cache")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"

# dashboard name -> NSE symbol, per segment. Honda, Kia, Toyota, Suzuki Motorcycle do not file on NSE.
NSE = {
    "2W": {"Hero MotoCorp": ["HEROMOTOCO"], "TVS": ["TVSMOTOR"], "Bajaj": ["BAJAJ-AUTO"], "Royal Enfield": ["EICHERMOT"]},
    "CAR": {"Maruti Suzuki": ["MARUTI"], "Tata Motors": ["TMPV"], "Mahindra": ["M%26M"], "Hyundai": ["HYUNDAI"]},
    # Tata CV sat inside Tata Motors Ltd (symbol TMPV after the rename) until the Oct 2025 demerger, then TMCV.
    "CV": {"Tata Motors": ["TMCV", "TMPV"], "Mahindra": ["M%26M"], "Ashok Leyland": ["ASHOKLEY"], "VECV": ["EICHERMOT"]},
    # TVS 3W is left out: its releases state 3W volumes inconsistently and it is a small share of registrations.
    "3W": {"Bajaj": ["BAJAJ-AUTO"], "Mahindra": ["M%26M"]},
}


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




# ---------------------------------------------------------------- Registrations: the official VAHAN dashboard
PORTAL = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"
# Segments are defined with the dashboard's own filters. `cats` are Vehicle Category codes, `classes` Vehicle Class ids,
# `fuels` Fuel ids (23 pure EV, 4 battery-operated). `makers` map a display name to a regex on the legal name VAHAN
# uses; every other maker rolls into the segment total.
SEGMENTS = {
    "2W": {"cats": ("2WIC", "2WN", "2WT"), "makers": [
        ("Hero MotoCorp", r"^HERO MOTOCORP"), ("TVS", r"^TVS MOTOR"), ("Bajaj", r"^BAJAJ AUTO"),
        ("Royal Enfield", r"^(ROYAL-ENFIELD|EICHER MOTORS)"), ("Honda", r"^HONDA MOTORCYCLE"),
        ("Suzuki", r"^SUZUKI MOTORCYCLE"), ("Yamaha", r"^INDIA YAMAHA")]},
    "E2W": {"cats": ("2WIC", "2WN", "2WT"), "fuels": ("23", "4"), "makers": [
        ("TVS", r"^TVS MOTOR"), ("Bajaj", r"^BAJAJ AUTO"), ("Ather", r"^ATHER ENERGY"), ("Ola Electric", r"^OLA ELECTRIC"),
        ("Hero MotoCorp", r"^HERO MOTOCORP"), ("Ampere", r"^(GREAVES ELECTRIC|AMPERE VEHICLES)"), ("BGauss", r"^BGAUSS"),
        ("River", r"^RIVER MOBILITY"), ("Okinawa", r"^OKINAWA"), ("Hero Electric", r"^HERO ELECTRIC")]},
    # cars: Motor Car, Motor Cab, Maxi Cab
    "CAR": {"classes": ("7", "71", "70"), "makers": [
        ("Maruti Suzuki", r"^MARUTI SUZUKI"), ("Tata Motors", r"^(TATA MOTORS|TATA PASSENGER ELECTRIC)"),
        ("Mahindra", r"^(MAHINDRA & MAHINDRA|MAHINDRA ELECTRIC AUTOMOBILE)"), ("Hyundai", r"^HYUNDAI MOTOR"),
        ("Toyota", r"^TOYOTA KIRLOSKAR"), ("Kia", r"^KIA INDIA")]},
    # commercial: Goods Carrier, Articulated Vehicle, Bus, School Bus, Educational Institution Bus, Omni Bus (both)
    "CV": {"classes": ("59", "84", "73", "74", "75", "86", "23"), "makers": [
        ("Tata Motors", r"^TATA MOTORS"), ("Mahindra", r"^(MAHINDRA & MAHINDRA|MAHINDRA LAST MILE)"),
        ("Ashok Leyland", r"^ASHOK LEYLAND"), ("VECV", r"^VE COMMERCIAL")]},
    "3W": {"cats": ("3WIC", "3WN", "3WT"), "makers": [
        ("Bajaj", r"^BAJAJ AUTO"), ("Mahindra", r"^(MAHINDRA LAST MILE|MAHINDRA & MAHINDRA)"), ("TVS", r"^TVS MOTOR")]},
}
SEG_ORDER = ["2W", "E2W", "CAR", "CV", "3W"]


class Portal:
    def __init__(self):
        cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        page = self.op.open(urllib.request.Request(PORTAL, headers={"User-Agent": UA}), timeout=25).read().decode()
        self.vs = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', page).group(1)

    def post(self, data):
        req = urllib.request.Request(PORTAL, data=urllib.parse.urlencode(data).encode(), headers={
            "Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest", "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        r = self.op.open(req, timeout=120).read().decode()
        m = re.search(r'<update id="j_id1:javax.faces.ViewState:0"><!\[CDATA\[(.*?)\]\]>', r)
        if m:
            self.vs = m.group(1)
        return r

    def form(self, year, cats=(), classes=(), fuels=()):
        d = [("masterLayout_formlogin", "masterLayout_formlogin"), ("xaxisVar_input", "Month Wise"), ("yaxisVar_input", "Maker"),
             ("selectedYear_input", str(year)), ("selectedYearType_input", "C"), ("j_idt34_input", "A"), ("j_idt43_input", "-1"),
             ("selectedRto_input", "-1"), ("javax.faces.ViewState", self.vs)]
        return d + [("VhCatg", c) for c in cats] + [("VhClass", c) for c in classes] + [("fuel", f) for f in fuels]


def portal_rows(r):
    m = re.search(r'<update id="(?:combTablePnl|groupingTable)"><!\[CDATA\[(.*?)\]\]></update>', r, re.S)
    t = m.group(1) if m else r
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        c = [htmllib.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(c) >= 4 and c[0].isdigit():
            out.append((c[1], [int(x.replace(",", "")) for x in c[2:-1]]))
    return out


def portal_year(year, cats=(), classes=(), fuels=()):
    """Monthly registrations for every maker in a calendar year under the given filters: {legal name: [Jan, Feb, ...]}."""
    p = Portal()
    # the filter panel only takes effect after a first unfiltered query, then through its own Refresh button
    p.post([("javax.faces.partial.ajax", "true"), ("javax.faces.source", "j_idt75"), ("javax.faces.partial.execute", "@all"),
            ("javax.faces.partial.render", "VhCatg norms fuel VhClass combTablePnl groupingTable msg vhCatgPnl"),
            ("j_idt75", "j_idt75")] + p.form(year))
    r = p.post([("javax.faces.partial.ajax", "true"), ("javax.faces.source", "j_idt80"), ("javax.faces.partial.execute", "@all"),
                ("javax.faces.partial.render", "combTablePnl"), ("j_idt80", "j_idt80")] + p.form(year, cats, classes, fuels))
    m = re.search(r"rowCount:(\d+)", r)
    n = int(m.group(1)) if m else 0
    rows = portal_rows(r)
    for first in range(25, n, 25):
        for attempt in range(4):
            try:
                r = p.post([("javax.faces.partial.ajax", "true"), ("javax.faces.source", "groupingTable"),
                            ("javax.faces.partial.execute", "groupingTable"), ("javax.faces.partial.render", "groupingTable"),
                            ("groupingTable", "groupingTable"), ("groupingTable_pagination", "true"), ("groupingTable_first", str(first)),
                            ("groupingTable_rows", "25"), ("groupingTable_encodeFeature", "true")] + p.form(year, cats, classes, fuels))
                break
            except Exception:
                time.sleep(2)
        rows += portal_rows(r)
    if n and len(rows) != n:
        raise RuntimeError(f"VAHAN portal returned {len(rows)} of {n} makers for {year}")
    return dict(rows)


def cmd_portal(args):
    path = os.path.join(DATA, "registrations.json")
    store = json.load(open(path)) if os.path.exists(path) else {"months": []}
    now = dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)        # India time
    today = now.date()
    years = list(range(2022, today.year + 1)) if args.full or not store["months"] else ([today.year - 1] if today.month <= 2 else []) + [today.year]
    # series[seg][name][month] -> value, seeded from what is stored
    series = {}
    for seg in SEG_ORDER:
        if seg in store:
            series[seg] = {k: dict(zip(store["months"], v)) for k, v in store[seg].items()}
    only = [s for s in (args.segments or SEG_ORDER)]
    for seg in only:
        cfg = SEGMENTS[seg]
        names = [k for k, _ in cfg["makers"]]
        series.setdefault(seg, {})
        for k in ["T"] + names:
            series[seg].setdefault(k, {})
        for y in years:
            rows = portal_year(y, cfg.get("cats", ()), cfg.get("classes", ()), cfg.get("fuels", ()))
            n = len(next(iter(rows.values()), []))
            agg = {k: [0] * n for k in names}
            total = [0] * n
            for name, vals in rows.items():
                for i, x in enumerate(vals):
                    total[i] += x
                for disp, rx in cfg["makers"]:
                    if re.search(rx, name.upper()):
                        for i, x in enumerate(vals):
                            agg[disp][i] += x
                        break
            for i in range(n):
                mm = f"{y}-{i + 1:02d}"
                series[seg]["T"][mm] = total[i]
                for k in names:
                    series[seg][k][mm] = agg[k][i]
            print(f"{seg} {y}: {len(rows)} makers, {n} months, last month {total[-1] if total else 0}")
    months = sorted({m for seg in series.values() for m in seg["T"]})
    out = {"months": months}
    for seg in SEG_ORDER:
        if seg in series:
            out[seg] = {k: [series[seg][k].get(m, 0) for m in months] for k in ["T"] + [k for k, _ in SEGMENTS[seg]["makers"]]}
    # data through yesterday on a morning run and through today on an evening run
    done = today.day if now.hour >= 19 else today.day - 1
    last = months[-1]
    ly, lm = map(int, last.split("-"))
    dim = (dt.date(ly + (lm == 12), lm % 12 + 1, 1) - dt.date(ly, lm, 1)).days
    if (ly, lm) == (today.year, today.month):
        out["as_of"] = {"days_done": max(done, 0), "days_in_month": dim}
        if done < 10:    # a month with a few days of data would make the projection meaningless: hold it back
            print(f"{last} has {done} days of data; holding it back until it has 10.")
            for seg in SEG_ORDER:
                if seg in out:
                    for k in out[seg]:
                        out[seg][k] = out[seg][k][:-1]
            out["months"] = months[:-1]
            ly2, lm2 = map(int, out["months"][-1].split("-"))
            dim2 = (dt.date(ly2 + (lm2 == 12), lm2 % 12 + 1, 1) - dt.date(ly2, lm2, 1)).days
            out["as_of"] = {"days_done": dim2, "days_in_month": dim2}
    else:
        out["as_of"] = {"days_done": dim, "days_in_month": dim}
    out["fetched"] = now.strftime("%Y-%m-%dT%H:%M+05:30")
    save("registrations.json", out, separators=(",", ":"))
    print("registrations.json:", out["months"][0], "to", out["months"][-1], out["as_of"])


# ---------------------------------------------------------------- publish: the files the page loads
def cmd_publish(args):
    os.makedirs(PUB, exist_ok=True)
    only = args.only
    if only in ("all", "registrations"):
        reg = load("registrations.json")
        with open(os.path.join(PUB, "registrations.json"), "w") as f:
            json.dump(reg, f, separators=(",", ":"))
        print("published data/registrations.json (to", reg["months"][-1] + ")")
    if only == "registrations":
        return
    disp = load("dispatch.json")
    start = "2025-04"
    allm = sorted({m for seg in disp.values() for o in seg.values() for m in o})
    lastm = None
    for m in allm:
        if all(m in o for seg in disp.values() for o in seg.values()):
            lastm = m
    months = [m for m in allm if start <= m <= lastm]
    out = {"months": months, "DISP": {}}
    for seg, oems in disp.items():
        out["DISP"][seg] = {name: {"v": name, "d": [d[m] for m in months]} for name, d in oems.items()}
    with open(os.path.join(PUB, "dispatch.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("published data/dispatch.json (to", months[-1] + ")")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("portal"); a.add_argument("--full", action="store_true"); a.add_argument("--segments", nargs="*")
    b = sp.add_parser("dispatch"); b.add_argument("month", help="report month, e.g. 2026-11")
    pu = sp.add_parser("publish"); pu.add_argument("--only", choices=["all", "registrations", "dispatch"], default="all")
    args = ap.parse_args()
    if args.cmd == "portal":
        cmd_portal(args)
    elif args.cmd == "dispatch":
        cmd_dispatch(args)
    elif args.cmd == "publish":
        cmd_publish(args)


if __name__ == "__main__":
    main()
