import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from fixhealth import simulate
from fixhealth.checks import next_open, review, summary, trading_days
from fixhealth.cli import OUTPUTS, run
from fixhealth.model import load, msg_type, parse_dt

SH = ["Session", "Counterparty", "Purpose", "Critical", "FIXVersion", "HeartBtInt", "Primary", "Backup", "BackupTested", "CertExpiry"]
EH = ["Time", "Session", "Dir", "MsgType", "MsgSeqNum", "BeginSeqNo", "EndSeqNo", "NewSeqNo", "GapFill", "HeartBtInt", "Text"]
DAYS = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]


def sess(i="US->THEM", critical="no", purpose="orders", hb="30", backup="", tested="", cert="2027-06-01"):
    return [i, "Them", purpose, critical, "FIX.4.4", hb, "gw1", backup, tested, cert]


def day(i, d, hb="30", close=True):
    rows = [[f"{d} 06:30:00", i, "out", "A", "1", "", "", "", "", "30", ""], [f"{d} 06:30:01", i, "in", "A", "1", "", "", "", "", hb, ""]]
    if close:
        rows += [[f"{d} 22:00:00", i, "out", "5", "", "", "", "", "", "", ""], [f"{d} 22:00:01", i, "in", "5", "", "", "", "", "", "", ""]]
    return rows


def week(i="US->THEM", **kw):
    return [r for d in DAYS for r in day(i, d, **kw)]


def ev(t, i, dr, ty, **kw):
    row = dict(zip(EH, [t, i, dr, ty, "", "", "", "", "", "", ""]))
    row.update(kw)
    return [row[h] for h in EH]


def write(folder: Path, sessions, events, latency=None, settings=None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, header, rows in (("sessions.csv", SH, sessions), ("events.csv", EH, events),
                               ("latency.csv", ["Date", "Session", "Orders", "P50ms", "P99ms", "MaxMs"], latency or [])):
        with (folder / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
    (folder / "settings.json").write_text(json.dumps({"organisation": "Test", "review": "2026-11-21 09:00:00", **(settings or {})}))
    return folder


def codes(folder):
    d = load(folder)
    rv = review(d)
    return d, rv, {f.code for f in rv.findings}


def test_parsers_and_calendar():
    assert msg_type("35=A") == "A" and msg_type("Logon") == "A" and msg_type("SequenceReset") == "4" and msg_type("j") == "j"
    assert parse_dt("20261116-06:30:00.125") == datetime(2026, 11, 16, 6, 30, 0, 125000)
    assert [str(x) for x in trading_days(datetime(2026, 11, 21, 9), 5)] == DAYS
    assert [str(x) for x in trading_days(datetime(2026, 11, 20, 12), 2)] == ["2026-11-18", "2026-11-19"]     # Friday before the close
    assert next_open(datetime(2026, 11, 21, 9), datetime(2026, 1, 1, 8).time()) == datetime(2026, 11, 23, 8)


def test_a_quiet_week_has_no_findings(tmp_path):
    f = write(tmp_path, [sess(critical="yes", backup="gw2", tested="2026-10-01")], week())
    d, rv, c = codes(f)
    assert c == set() and rv.score == 100.0 and rv.status == "GREEN" and rv.sessions[0]["state"] == "up" and not rv.watchlist


def test_drops_explicit_and_inferred(tmp_path):
    evs = week() + [ev("2026-11-17 10:00:00", "US->THEM", "out", "disconnect"), ev("2026-11-17 10:02:00", "US->THEM", "in", "A"),
                    ev("2026-11-18 11:00:00", "US->THEM", "out", "1"), ev("2026-11-18 11:01:00", "US->THEM", "in", "A"),       # no disconnect logged
                    ev("2026-11-19 12:00:00", "US->THEM", "out", "disconnect"), ev("2026-11-19 12:01:00", "US->THEM", "in", "A")]
    f = write(tmp_path, [sess(critical="yes", backup="gw2", tested="2026-10-01")], sorted(evs))
    d, rv, c = codes(f)
    drops = next(x for x in rv.findings if x.code == "DROPS")
    assert drops.severity == "RED" and rv.sessions[0]["disconnects"] == 3 and rv.sessions[0]["in_market_hours"] == 3


def test_logon_refused_at_the_close_goes_first_on_the_watchlist(tmp_path):
    evs = [r for d_ in DAYS[:4] for r in day("US->THEM", d_)] + day("US->THEM", DAYS[4], close=False) + [
        ev("2026-11-20 21:40:00", "US->THEM", "out", "disconnect"), ev("2026-11-20 21:58:00", "US->THEM", "out", "A"),
        ev("2026-11-20 21:58:01", "US->THEM", "in", "5", Text="MsgSeqNum too low, expecting 4812 but received 1")]
    f = write(tmp_path, [sess(critical="yes", backup="gw2", tested="2026-10-01"), sess("US->OTHER")], evs + week("US->OTHER"))
    d, rv, c = codes(f)
    assert "LOGON-REFUSED" in c and rv.sessions[0]["state"] == "down"
    assert rv.watchlist[0]["session"] == "US->THEM" and rv.watchlist[0]["by"] == "2026-11-23 07:00"


def test_silent_session(tmp_path):
    f = write(tmp_path, [sess()], [r for d_ in DAYS[:3] for r in day("US->THEM", d_)])
    d, rv, c = codes(f)
    assert c == {"SILENT"} and rv.sessions[0]["state"] == "silent"


def test_gaps_and_hard_reset(tmp_path):
    gaps = [ev(f"{d_} 11:00:00", "US->THEM", "out", "2", BeginSeqNo="10", EndSeqNo="0") for d_ in DAYS]
    reset = [ev("2026-11-18 14:12:00", "US->THEM", "in", "4", MsgSeqNum="100", NewSeqNo="230", GapFill="N"),
             ev("2026-11-19 14:12:00", "US->THEM", "in", "4", MsgSeqNum="100", NewSeqNo="103", GapFill="Y")]
    f = write(tmp_path, [sess(purpose="drop copy")], sorted(week() + gaps + reset))
    d, rv, c = codes(f)
    r = next(x for x in rv.findings if x.code == "SEQ-RESET")
    assert "SEQ-GAPS" in c and r.severity == "RED" and r.preopen and "230" in r.text and rv.sessions[0]["hard_resets"] == 1


def test_missed_heartbeats_rejects_and_heartbeat_mismatch(tmp_path):
    tr = [ev(f"{DAYS[i % 5]} 08:{10 + i:02d}:00", "US->THEM", "out", "1") for i in range(6)]
    rj = [ev("2026-11-19 17:00:00", "US->THEM", "in", "j", Text="Unknown account") for _ in range(10)]
    f = write(tmp_path, [sess()], sorted(week(hb="60") + tr + rj))
    d, rv, c = codes(f)
    assert {"HB-MISSED", "REJECTS", "HB-MISMATCH"} <= c
    assert "between 08:00 and 09:00" in next(x for x in rv.findings if x.code == "HB-MISSED").text
    assert "Unknown account" in next(x for x in rv.findings if x.code == "REJECTS").text


def test_latency_against_threshold_and_baseline(tmp_path):
    lat = [[d_, "US->THEM", 1000, 1.5, 4.0, 9.0] for d_ in DAYS[:4]] + [[DAYS[4], "US->THEM", 1000, 3.0, 38.0, 60.0]]
    lat += [[d_, "US->SLOW", 1000, 1.5, 15.0, 20.0] for d_ in DAYS]          # always slow: above the threshold, not above its own baseline
    f = write(tmp_path, [sess(critical="yes", backup="gw2", tested="2026-10-01"), sess("US->SLOW")], sorted(week() + week("US->SLOW")), lat)
    d, rv, c = codes(f)
    late = [x for x in rv.findings if x.code == "LATENCY"]
    assert [x.subject for x in late] == ["US->THEM"] and late[0].severity == "RED" and late[0].preopen


def test_certificate_and_failover(tmp_path):
    f = write(tmp_path, [sess(critical="yes", cert="2026-11-26"), sess("US->B", critical="yes", backup="gw2", tested="2025-12-01", cert="2026-12-15")],
              week() + week("US->B"))
    d, rv, c = codes(f)
    certs = {x.subject: x.severity for x in rv.findings if x.code == "CERT"}
    fo = {x.subject: x.text for x in rv.findings if x.code == "FAILOVER"}
    assert certs == {"US->THEM": "RED", "US->B": "AMBER"} and "no backup host" in fo["US->THEM"] and "last tested Dec 2025" in fo["US->B"]


def test_unknown_session_in_the_logs(tmp_path):
    f = write(tmp_path, [sess()], week() + week("US->GHOST"))
    d, rv, c = codes(f)
    assert c == {"UNKNOWN-SESSION"}


def test_other_column_names_and_semicolons(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "sessions.csv").write_text("SessionID;Venue;Flow;Tier;HeartbeatSec\nUS->THEM;Them;orders;no;30\n")
    lines = ["Timestamp;SessionID;Direction;35;34;108;58"] + [x for d_ in DAYS for x in (f"{d_.replace('-', '')}-06:30:01.000;US->THEM;in;A;1;30;",
                                                                                        f"{d_.replace('-', '')}-22:00:01.000;US->THEM;in;Logout;9;;")]
    (tmp_path / "events.csv").write_text("\n".join(lines) + "\n")
    d, rv, c = codes(tmp_path)
    assert len(d.events) == 10 and d.events[1].type == "5" and d.events[0].type == "A" and d.events[0].dir == "in" and c == set()


def test_missing_files(tmp_path):
    (tmp_path / "sessions.csv").write_text("Session\nA->B\n")
    try:
        load(tmp_path)
        assert False
    except FileNotFoundError as exc:
        assert "events.csv" in str(exc)


def test_demo_end_to_end(tmp_path):
    data = simulate.write(tmp_path / "data")
    sm = run(data, tmp_path / "out")
    for name in OUTPUTS:
        assert (tmp_path / "out" / name).exists(), name
    d = load(data)
    rv = review(d)
    assert {"DROPS", "LOGON-REFUSED", "SILENT", "SEQ-GAPS", "SEQ-RESET", "HB-MISSED", "REJECTS", "HB-MISMATCH", "LATENCY", "CERT", "FAILOVER"} <= {f.code for f in rv.findings}
    assert sm["status"] == "RED" and sm["sessions"] == 12 and sm["disconnects"] == 6 and sm["watchlist"] == 5 and sm["decisions"] == 6
    assert rv.watchlist[0]["session"] == "FABMKT->ADATUM"


def test_demo_is_deterministic(tmp_path):
    def digest(folder):
        return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}
    a = run(simulate.write(tmp_path / "a"), tmp_path / "oa")
    b = run(simulate.write(tmp_path / "b"), tmp_path / "ob")
    assert a == b and digest(tmp_path / "a") == digest(tmp_path / "b") and digest(tmp_path / "oa") == digest(tmp_path / "ob")
