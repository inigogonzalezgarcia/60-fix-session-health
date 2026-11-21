"""The fictional demo: Fabrikam Markets, a broker with its electronic trading desk in Madrid, and the review of its FIX
sessions on Saturday 21 November 2026, looking back at the trading week of 16-20 November and ahead to Monday's open.
12 sessions with 10 counterparties. Every name, CompID, host, figure and time is made up; the problems are placed on purpose
among sessions that are fine. The output is deterministic: the same files every run."""
from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

REVIEW = "2026-11-21 09:00:00"
DAYS = [date(2026, 11, 16) + timedelta(days=i) for i in range(5)]

SESSIONS = [  # Session, Counterparty, Purpose, Critical, FIXVersion, HeartBtInt, StartTime, EndTime, Primary, Backup, BackupTested, CertExpiry, Owner, Desk
    ("FABMKT->TAILSPIN", "Tailspin Bank", "orders", "yes", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-01", "fixgw-bcn-01", "2026-07-11", "2027-03-15", "", "Rates"),
    ("FABMKT->TAILSPIN-AL", "Tailspin Bank", "allocations", "no", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-01", "", "", "2027-03-15", "", "Operations"),
    ("FABMKT->NWCLEAR-DC", "Northwind Clearing", "drop copy", "yes", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-02", "fixgw-bcn-02", "2026-09-19", "2027-05-02", "", "Operations"),
    ("FABMKT->LITWARE-MD", "Litware Securities", "market data", "no", "FIX.5.0SP2", 30, "06:30", "22:00", "mdgw-mad-01", "", "", "2027-01-30", "", "Rates"),
    ("FABMKT->ADATUM", "Adatum Capital", "orders", "yes", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-01", "fixgw-bcn-01", "2026-06-20", "2027-02-11", "", "Equities"),
    ("FABMKT->CONTOSO-MTF", "Contoso MTF", "orders", "yes", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-02", "fixgw-bcn-02", "2026-10-03", "2026-11-26", "", "Rates"),
    ("FABMKT->CONTOSO-DC", "Contoso MTF", "drop copy", "no", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-02", "", "", "2026-11-26", "", "Operations"),
    ("FABMKT->PROSEWARE", "Proseware MTF", "orders", "yes", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-01", "fixgw-bcn-01", "", "2027-04-20", "", "Credit"),
    ("FABMKT->WINGTIP-AL", "Wingtip Prime", "allocations", "no", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-02", "", "", "2027-06-01", "", "Operations"),
    ("FABMKT->WOODGROVE-RFQ", "Woodgrove Bank", "orders", "no", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-01", "", "", "2027-02-28", "", "Credit"),
    ("FABMKT->RELECLOUD-RFQ", "Relecloud Securities", "orders", "no", "FIX.4.4", 30, "06:30", "22:00", "fixgw-mad-02", "", "", "2027-01-15", "", "Equities"),
    ("FABMKT->TREY-MD", "Trey Research Markets", "market data", "no", "FIX.5.0SP2", 30, "06:30", "22:00", "mdgw-mad-01", "", "", "2027-08-09", "", "Equities"),
]

SETTINGS = {
    "organisation": "Fabrikam Markets",
    "review": REVIEW,
    "days": 5,
    "market_open": "08:00",
    "market_close": "17:30",
    "previous_score": 84.2,
    "owners": {"etrading": "Óscar Lara (Electronic trading support)", "network": "Nuria Pons (Network team)", "onboarding": "Clara Vidal (Client onboarding)"},
}


def _t(d: date, hm: str, sec: int = 0) -> str:
    h, m = hm.split(":")
    return (datetime(d.year, d.month, d.day, int(h), int(m)) + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S")


def events() -> list[list]:
    rnd = random.Random(60)
    rows = []
    E = lambda t, s, dr, ty, seq="", b="", e="", ns="", gf="", hb="", tx="": rows.append([t, s, dr, ty, seq, b, e, ns, gf, hb, tx])  # noqa: E731
    for d in DAYS:
        for sid, *_ in SESSIONS:
            if sid == "FABMKT->RELECLOUD-RFQ" and d.weekday() > 2:
                continue                                                     # silent since Wednesday
            hb = 60 if sid == "FABMKT->WOODGROVE-RFQ" else 30
            E(_t(d, "06:30"), sid, "out", "A", 1, hb=30)
            E(_t(d, "06:30", 1), sid, "in", "A", 1, hb=hb)
            if sid != "FABMKT->TAILSPIN" and rnd.random() < 0.25:             # an ordinary gap, filled
                at = f"{rnd.randint(9, 16):02d}:{rnd.randint(0, 59):02d}"
                n = rnd.randint(200, 900)
                E(_t(d, at), sid, "out", "2", n, n, 0)
                E(_t(d, at, 1), sid, "in", "4", n, ns=n + rnd.randint(2, 6), gf="Y")
            if sid == "FABMKT->ADATUM" and d == DAYS[-1]:
                E(_t(d, "21:40"), sid, "out", "disconnect", tx="Socket closed by peer")
                E(_t(d, "21:58"), sid, "out", "A", 1, hb=30)
                E(_t(d, "21:58", 1), sid, "in", "5", 4813, tx="MsgSeqNum too low, expecting 4812 but received 1")
                continue
            E(_t(d, "22:00"), sid, "out", "5", 9000)
            E(_t(d, "22:00", 1), sid, "in", "5", 9000)
    # Tailspin orders: five drops, four in market hours, each followed by a gap on the way back
    for d, hm in ((DAYS[0], "10:14"), (DAYS[1], "09:02"), (DAYS[3], "15:40"), (DAYS[4], "08:31"), (DAYS[4], "19:05")):
        sid = "FABMKT->TAILSPIN"
        E(_t(d, hm), sid, "out", "1", tx="TEST-" + hm.replace(":", ""))
        E(_t(d, hm, 35), sid, "out", "disconnect", tx="Heartbeat timeout")
        E(_t(d, hm, 95), sid, "out", "A", 1, hb=30)
        E(_t(d, hm, 96), sid, "in", "A", 1, hb=30)
        E(_t(d, hm, 97), sid, "out", "2", 1, 2104, 0)
        E(_t(d, hm, 98), sid, "in", "4", 1, ns=2131, gf="Y")
    E(_t(DAYS[2], "11:20"), "FABMKT->TAILSPIN", "in", "2", 1, 6011, 0)
    # Northwind drop copy: a sequence reset without gap fill on Wednesday afternoon
    E(_t(DAYS[2], "14:12"), "FABMKT->NWCLEAR-DC", "in", "4", 18322, ns=18450, gf="N")
    # Litware market data: heartbeats stop arriving around the open
    for i in range(14):
        d = DAYS[i % 5]
        E(_t(d, f"08:{5 + 4 * i:02d}"), "FABMKT->LITWARE-MD", "out", "1", tx=f"TR{i + 1:03d}")
        E(_t(d, f"08:{5 + 4 * i:02d}", 2), "FABMKT->LITWARE-MD", "in", "0")
    # Wingtip allocations: business rejects for an unknown account on Thursday
    for i in range(22):
        E(_t(DAYS[3], f"{17 + i // 12}:{(i * 5) % 60:02d}"), "FABMKT->WINGTIP-AL", "in", "j", tx="Unknown account WGT-77104")
    rows = [r for r in rows if r[3] != "0"]                                    # heartbeats are not exported
    return sorted(rows, key=lambda r: (r[0], r[1], r[2] == "in"))


def latency() -> list[list]:
    rnd = random.Random(61)
    rows = []
    for d in DAYS:
        for sid, cp, purpose, *_ in SESSIONS:
            if purpose != "orders" or (sid == "FABMKT->RELECLOUD-RFQ" and d.weekday() > 2):
                continue
            p50 = round(1.2 + rnd.random() * 0.8, 1)
            p99 = round(3.5 + rnd.random() * 2.0, 1)
            if sid == "FABMKT->TAILSPIN" and d == DAYS[-1]:
                p50, p99 = 3.4, 38.0
            rows.append([d.isoformat(), sid, rnd.randint(800, 4200), p50, p99, round(p99 * (1.6 + rnd.random()), 1)])
    return rows


def _csv(path: Path, header: list[str], rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write(folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _csv(folder / "sessions.csv", ["Session", "Counterparty", "Purpose", "Critical", "FIXVersion", "HeartBtInt", "StartTime", "EndTime", "Primary", "Backup",
                                   "BackupTested", "CertExpiry", "Owner", "Desk"], SESSIONS)
    _csv(folder / "events.csv", ["Time", "Session", "Dir", "MsgType", "MsgSeqNum", "BeginSeqNo", "EndSeqNo", "NewSeqNo", "GapFill", "HeartBtInt", "Text"], events())
    _csv(folder / "latency.csv", ["Date", "Session", "Orders", "P50ms", "P99ms", "MaxMs"], latency())
    (folder / "settings.json").write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder
