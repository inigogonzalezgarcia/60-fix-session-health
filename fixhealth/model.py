"""Loading: the FIX sessions with their configuration (sessions.csv), the session-level messages of the week taken from
the FIX engine logs (events.csv: logons, logouts, test requests, resend requests, sequence resets and rejects; heartbeats
and application messages are left out) and the daily order round-trip latency per session (latency.csv), plus the
desk's policy (settings.json). Forgiving column names, into plain dataclasses. sessions.csv and events.csv are required."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

SESSION_ALIASES = {
    "id": ["Session", "SessionID", "Session id"],
    "counterparty": ["Counterparty", "Venue", "Broker"],
    "purpose": ["Purpose", "Flow", "Type"],
    "critical": ["Critical", "Tier", "Criticality"],
    "version": ["FIXVersion", "BeginString", "Version"],
    "hb": ["HeartBtInt", "Heartbeat", "HeartbeatSec"],
    "start": ["StartTime", "Start"],
    "end": ["EndTime", "End"],
    "primary": ["Primary", "PrimaryHost"],
    "backup": ["Backup", "BackupHost"],
    "backup_tested": ["BackupTested", "Failover tested", "LastFailoverTest"],
    "cert": ["CertExpiry", "Certificate expiry", "TLSExpiry"],
    "owner": ["Owner", "Support"],
    "desk": ["Desk", "Business"],
}
EVENT_ALIASES = {
    "time": ["Time", "Timestamp", "SendingTime", "52"],
    "session": ["Session", "SessionID"],
    "dir": ["Dir", "Direction"],
    "type": ["MsgType", "35", "Type"],
    "seq": ["MsgSeqNum", "34", "Seq"],
    "begin": ["BeginSeqNo", "7"],
    "end": ["EndSeqNo", "16"],
    "new_seq": ["NewSeqNo", "36"],
    "gap_fill": ["GapFill", "GapFillFlag", "123"],
    "hb": ["HeartBtInt", "108"],
    "text": ["Text", "58", "Reason"],
}
LAT_ALIASES = {
    "date": ["Date", "Day"],
    "session": ["Session", "SessionID"],
    "orders": ["Orders", "Count"],
    "p50": ["P50ms", "P50", "Median"],
    "p99": ["P99ms", "P99"],
    "max": ["MaxMs", "Max"],
}
NAMES = {"A": "Logon", "5": "Logout", "1": "TestRequest", "2": "ResendRequest", "3": "Reject", "4": "SequenceReset", "j": "BusinessMessageReject",
         "disconnect": "Disconnect"}
FILES = {"sessions.csv": "FIX sessions", "events.csv": "Session messages", "latency.csv": "Order latency"}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def key(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(s))


def yes(v) -> bool:
    return _norm(v) in {"yes", "y", "true", "1", "x", "critical", "tier 1", "1 critical", "high"}


def parse_dt(v) -> datetime | None:
    s = str(v or "").strip()
    for fmt in ("%Y%m%d-%H:%M:%S.%f", "%Y%m%d-%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def parse_d(v) -> date | None:
    x = parse_dt(v)
    if x:
        return x.date()
    try:
        return datetime.strptime(str(v or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def num(v) -> float | None:
    s = str(v or "").strip().replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def msg_type(v) -> str:
    """'A', '35=A', 'Logon' -> 'A'; 'disconnect' stays."""
    s = str(v or "").strip()
    s = s.split("=", 1)[1] if s.startswith("35=") else s
    for code, name in NAMES.items():
        if _norm(s) in (code.lower(), name.lower()):
            return code
    return s


@dataclass
class Session:
    id: str
    counterparty: str = ""
    purpose: str = ""
    critical: bool = False
    version: str = ""
    hb: float | None = None
    start: str = ""
    end: str = ""
    primary: str = ""
    backup: str = ""
    backup_tested: date | None = None
    cert: date | None = None
    owner: str = ""
    desk: str = ""


@dataclass
class Event:
    time: datetime
    session: str
    dir: str            # in (from the counterparty) or out (from us)
    type: str           # FIX MsgType: A, 5, 1, 2, 3, 4, j; or disconnect
    seq: int | None = None
    begin: int | None = None
    end: int | None = None
    new_seq: int | None = None
    gap_fill: bool | None = None
    hb: float | None = None
    text: str = ""


@dataclass
class Latency:
    day: date
    session: str
    orders: float | None = None
    p50: float | None = None
    p99: float | None = None
    max: float | None = None


@dataclass
class Settings:
    organisation: str = "Your organisation"
    review: datetime = field(default_factory=datetime.now)      # when the review runs
    days: int = 5                                               # trading days looked at, back from the review
    market_open: str = "08:00"
    market_close: str = "17:30"
    drops_red: int = 3                                          # unexpected disconnects in market hours that make a critical session red
    resends_amber: int = 5
    test_requests_amber: int = 5
    rejects_amber: int = 10
    latency_p99_ms: dict = field(default_factory=lambda: {"orders": 10, "market data": 5, "drop copy": 50, "allocations": 250, "default": 20})
    latency_factor: float = 2.0                                 # last day's p99 this many times the earlier days' median
    cert_days: int = 30
    cert_red_days: int = 7
    failover_months: int = 6
    score_amber: float = 90.0
    score_red: float = 75.0
    previous_score: float | None = None
    owners: dict = field(default_factory=lambda: {"etrading": "Electronic trading support", "network": "Network team", "onboarding": "Client onboarding"})


@dataclass
class Data:
    sessions: list[Session]
    events: list[Event] = field(default_factory=list)
    latency: list[Latency] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)
    sources: dict = field(default_factory=dict)


def _read(path: Path) -> list[dict]:
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig")
    head = text.splitlines()[0] if text else ""
    delim = ";" if head.count(";") > head.count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delim))


def _rows(path: Path, aliases: dict) -> list[dict]:
    rows = _read(path)
    fields = list(rows[0].keys()) if rows else []
    lower = {_norm(f): f for f in fields if f}
    pick = {}
    for k, names in aliases.items():
        for n in names:
            if _norm(n) in lower:
                pick[k] = lower[_norm(n)]
                break
    return [{k: str(r.get(col) or "").strip() for k, col in pick.items()} for r in rows]


def _int(v) -> int | None:
    n = num(v)
    return int(n) if n is not None else None


def _settings(path: Path) -> Settings:
    s = Settings()
    if not path.exists():
        return s
    for k, v in json.loads(path.read_text(encoding="utf-8")).items():
        if k == "review":
            s.review = parse_dt(v) or s.review
        elif k in ("owners", "latency_p99_ms") and isinstance(v, dict):
            getattr(s, k).update(v)
        elif hasattr(s, k):
            setattr(s, k, v)
    return s


def load(folder: Path) -> Data:
    folder = Path(folder)
    for name in ("sessions.csv", "events.csv"):
        if not (folder / name).exists():
            raise FileNotFoundError(f"{folder / name} not found: see docs/data-format.md "
                                    + ("(the session list)" if name == "sessions.csv" else "(Export-FixSessionEvents.ps1 writes it from the engine logs)"))
    d = Data(sessions=[], settings=_settings(folder / "settings.json"))
    for r in _rows(folder / "sessions.csv", SESSION_ALIASES):
        if not r.get("id"):
            continue
        d.sessions.append(Session(r["id"], r.get("counterparty", ""), _norm(r.get("purpose")), yes(r.get("critical")), r.get("version", ""),
                                  num(r.get("hb")), r.get("start", ""), r.get("end", ""), r.get("primary", ""), r.get("backup", ""),
                                  parse_d(r.get("backup_tested")), parse_d(r.get("cert")), r.get("owner", ""), r.get("desk", "")))
    d.sources["sessions.csv"] = len(d.sessions)
    for r in _rows(folder / "events.csv", EVENT_ALIASES):
        t = parse_dt(r.get("time"))
        if not t or not r.get("session"):
            continue
        gf = r.get("gap_fill", "")
        d.events.append(Event(t, r["session"], "in" if _norm(r.get("dir")).startswith(("in", "rec", "<")) else "out", msg_type(r.get("type")),
                              _int(r.get("seq")), _int(r.get("begin")), _int(r.get("end")), _int(r.get("new_seq")),
                              None if gf == "" else _norm(gf) in ("y", "yes", "true", "1"), num(r.get("hb")), r.get("text", "")))
    d.events.sort(key=lambda e: (e.time, e.session))
    d.sources["events.csv"] = len(d.events)
    f = folder / "latency.csv"
    if f.exists():
        for r in _rows(f, LAT_ALIASES):
            day = parse_d(r.get("date"))
            if day and r.get("session"):
                d.latency.append(Latency(day, r["session"], num(r.get("orders")), num(r.get("p50")), num(r.get("p99")), num(r.get("max"))))
        d.sources["latency.csv"] = len(d.latency)
    return d
