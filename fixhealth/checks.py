"""The review. For every FIX session, over the last trading days: how often it dropped without a logout (and whether it was
in market hours), the sequence gaps that needed a resend and the hard resets that may have skipped messages, the test
requests sent because the counterparty's heartbeats stopped, session and business rejects, a heartbeat interval that does
not match the configuration, order latency against the threshold and the session's own baseline, the TLS certificate and
the failover test. Then the state each session was left in at the last close, so the watchlist says which ones to look at
before the market opens. Each finding has a severity, an owner and a due time; a health score per session and
counterparty; decisions."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median

from .model import NAMES, Data, Event, Session, key

AREAS = {"stability": "Stability", "sequence": "Sequence numbers", "traffic": "Heartbeats, rejects and latency", "resilience": "Certificates and failover"}


@dataclass
class Finding:
    code: str
    severity: str
    area: str
    subject: str
    text: str
    owner: str = ""
    due: datetime | None = None
    action: str = ""
    preopen: bool = False            # look at it before the market opens


@dataclass
class Review:
    findings: list[Finding] = field(default_factory=list)
    sessions: list[dict] = field(default_factory=list)
    daily: list[dict] = field(default_factory=list)
    watchlist: list[dict] = field(default_factory=list)
    counterparties: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    days: list[date] = field(default_factory=list)
    open_at: datetime | None = None
    score: float = 0.0
    status: str = "GREEN"


def pl(n: int, word: str, plural: str | None = None) -> str:
    return f"{n:g} {word if n == 1 else plural or word + 's'}"


def _hm(s: str, default: str) -> time:
    try:
        h, m = (s or default).split(":")[:2]
        return time(int(h), int(m))
    except ValueError:
        h, m = default.split(":")
        return time(int(h), int(m))


def trading_days(review: datetime, n: int) -> list[date]:
    """The last n weekdays that ended before the review (today counts only once its market has closed)."""
    out, d = [], review.date()
    if review.time() < time(18, 0) or d.weekday() >= 5:
        d -= timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def next_open(review: datetime, open_t: time) -> datetime:
    d = review.date()
    while True:
        at = datetime.combine(d, open_t)
        if d.weekday() < 5 and at > review:
            return at
        d += timedelta(days=1)


def review(d: Data) -> Review:
    s = d.settings
    rv = Review()
    rv.days = trading_days(s.review, s.days)
    o_t, c_t = _hm(s.market_open, "08:00"), _hm(s.market_close, "17:30")
    rv.open_at = next_open(s.review, o_t)
    before_open = rv.open_at - timedelta(minutes=60)
    start = datetime.combine(rv.days[0], time(0, 0))
    own = s.owners
    by_s: dict[str, list[Event]] = defaultdict(list)
    for e in d.events:
        if start <= e.time <= s.review:
            by_s[key(e.session)].append(e)
    lat = defaultdict(dict)
    for x in d.latency:
        lat[key(x.session)][x.day] = x
    known = {key(x.id) for x in d.sessions}

    def in_hours(t: datetime) -> bool:
        return t.weekday() < 5 and o_t <= t.time() <= c_t

    def add(f: Finding):
        f.due = f.due or (before_open if f.preopen else s.review + timedelta(days=14 if f.severity == "RED" else 30))
        rv.findings.append(f)

    for x in sorted(set(e.session for e in d.events if key(e.session) not in known)):
        add(Finding("UNKNOWN-SESSION", "AMBER", "stability", x, f"{x}: messages in the logs for a session that is not in sessions.csv",
                    own["etrading"], action="Add it to the session list or switch it off"))

    for ss in d.sessions:
        evs = by_s.get(key(ss.id), [])
        name = f"{ss.counterparty} {ss.purpose}".strip() or ss.id
        checks: list[bool] = []
        day_rows = {dd: Counter() for dd in rv.days}
        up, last_t, drops, drops_hours, rejected_logons = False, None, [], [], []
        pending_logon = None
        hb_seen = set()
        for e in evs:
            dd = e.time.date()
            c = day_rows.get(dd)
            if e.type == "A" and e.dir == "out":
                pending_logon = e
            if e.type == "A" and e.dir == "in":
                if up and last_t is not None:
                    drops.append(last_t)
                up, pending_logon = True, None
                if e.hb is not None:
                    hb_seen.add(e.hb)
                if c is not None:
                    c["logons"] += 1
            elif e.type == "disconnect":
                if up:
                    drops.append(e.time)
                up = False
            elif e.type == "5":
                if e.dir == "in" and pending_logon is not None and not up:
                    rejected_logons.append(e)
                    pending_logon = None
                up = False
            elif c is not None and not (e.type == "1" and e.dir == "in"):
                c[{"1": "test_requests", "2": "resends", "3": "rejects", "j": "rejects", "4": "resets"}.get(e.type, "other")] += 1
            last_t = e.time
        for t in drops:
            if t.date() in day_rows:
                day_rows[t.date()]["disconnects"] += 1
        drops = [t for t in drops if t >= start]
        drops_hours = [t for t in drops if in_hours(t)]

        # --- stability: drops, logons refused, the state left at the last close, silence
        checks.append(not drops)
        if drops:
            sev = "RED" if ss.critical and len(drops_hours) >= s.drops_red else "AMBER"
            when = ", ".join(f"{t:%a %H:%M}" for t in drops[:6]) + ("…" if len(drops) > 6 else "")
            add(Finding("DROPS", sev, "stability", ss.id, f"{name}: {pl(len(drops), 'disconnect')} without a logout ({len(drops_hours)} in market hours: {when})",
                        ss.owner or own["etrading"], action="Open a case with the counterparty with the times; check the line and the engine host"))
        last_day = rv.days[-1]
        logged_last = any(e.type == "A" and e.dir == "in" and e.time.date() == last_day for e in evs)
        tail = [e for e in evs if e.type in ("A", "5", "disconnect")]
        down_now = bool(rejected_logons) and rejected_logons[-1] is tail[-1] if tail else False
        checks.append(not down_now)
        if down_now:
            r = rejected_logons[-1]
            add(Finding("LOGON-REFUSED", "RED", "stability", ss.id, f"{name}: logon refused on {r.time:%a %H:%M}" + (f" ({r.text})" if r.text else "")
                        + "; the session did not come back", ss.owner or own["etrading"], action="Agree the sequence numbers with the counterparty and log on before the open",
                        preopen=True))
        checks.append(logged_last or down_now)
        if not logged_last and not down_now:
            seen = max((e.time for e in evs if e.type == "A" and e.dir == "in"), default=None)
            add(Finding("SILENT", "RED" if ss.critical else "AMBER", "stability", ss.id, f"{name}: no logon on {last_day:%a %d %b}"
                        + (f"; last one {seen:%a %d %b %H:%M}" if seen else " nor in the whole period"), ss.owner or own["etrading"],
                        action="Check whether it is still needed and why it did not log on", preopen=ss.critical))

        # --- sequence numbers: resends and hard resets
        resends = [e for e in evs if e.type == "2"]
        hard = [e for e in evs if e.type == "4" and e.gap_fill is False]
        checks.append(len(resends) < s.resends_amber)
        if len(resends) >= s.resends_amber:
            add(Finding("SEQ-GAPS", "AMBER", "sequence", ss.id, f"{name}: {pl(len(resends), 'resend request')} for sequence gaps ("
                        + f"{sum(1 for e in resends if e.dir == 'out')} asked by us)", ss.owner or own["etrading"],
                        action="Find what loses messages: reconnections, the line or the counterparty's engine"))
        checks.append(not hard)
        if hard:
            e = hard[0]
            jump = f" to {e.new_seq}" if e.new_seq else ""
            add(Finding("SEQ-RESET", "RED" if ss.critical or "drop" in ss.purpose else "AMBER", "sequence", ss.id,
                        f"{name}: sequence reset without gap fill on {e.time:%a %H:%M}{jump}: the messages in between were never resent",
                        ss.owner or own["etrading"], action="Reconcile the orders and trades of that window with the counterparty", preopen=True))

        # --- heartbeats, rejects, latency
        tests = [e for e in evs if e.type == "1" and e.dir == "out"]
        checks.append(len(tests) < s.test_requests_amber)
        if len(tests) >= s.test_requests_amber:
            hours = Counter(e.time.hour for e in tests).most_common(1)[0]
            add(Finding("HB-MISSED", "AMBER", "traffic", ss.id, f"{name}: {pl(len(tests), 'test request')} sent because heartbeats stopped arriving "
                        f"(most between {hours[0]:02d}:00 and {hours[0] + 1:02d}:00)", ss.owner or own["network"],
                        action="Compare with network latency and the counterparty's load at those hours"))
        rej = [e for e in evs if e.type in ("3", "j")]
        checks.append(len(rej) < s.rejects_amber)
        if len(rej) >= s.rejects_amber:
            top = Counter(e.text or NAMES[e.type] for e in rej).most_common(1)[0]
            add(Finding("REJECTS", "AMBER", "traffic", ss.id, f"{name}: {pl(len(rej), 'reject')} ({top[1]} of them '{top[0]}')", ss.desk or own["onboarding"],
                        action="Fix the static data or the message the counterparty refuses"))
        checks.append(not hb_seen or ss.hb is None or hb_seen == {ss.hb})
        if hb_seen and ss.hb is not None and hb_seen != {ss.hb}:
            add(Finding("HB-MISMATCH", "AMBER", "traffic", ss.id, f"{name}: logons with HeartBtInt {', '.join(f'{x:g}' for x in sorted(hb_seen))} s, configured "
                        f"{ss.hb:g} s", ss.owner or own["etrading"], action="Align the heartbeat interval with the counterparty"))
        series = [lat[key(ss.id)][dd] for dd in rv.days if dd in lat[key(ss.id)] and lat[key(ss.id)][dd].p99 is not None]
        p99_last = series[-1].p99 if series and series[-1].day == last_day else None
        base = median([x.p99 for x in series[:-1]]) if len(series) > 1 else None
        limit = s.latency_p99_ms.get(ss.purpose, s.latency_p99_ms.get("default", 20))
        slow = p99_last is not None and p99_last > limit and (base is None or p99_last > base * s.latency_factor)
        checks.append(not slow)
        if slow:
            add(Finding("LATENCY", "RED" if ss.critical else "AMBER", "traffic", ss.id, f"{name}: order round trip p99 {p99_last:g} ms on {last_day:%a}"
                        + (f", {base:g} ms the days before" if base is not None else "") + f" (threshold {limit:g} ms)", ss.owner or own["network"],
                        action="Check the route, the engine host and the counterparty's gateway before the open", preopen=ss.critical))

        # --- certificates and failover
        if ss.cert:
            left = (ss.cert - s.review.date()).days
            checks.append(left > s.cert_days)
            if left <= s.cert_days:
                add(Finding("CERT", "RED" if left <= s.cert_red_days else "AMBER", "resilience", ss.id, f"{name}: TLS certificate expires on "
                            f"{ss.cert:%d %b %Y} ({left} days)", ss.owner or own["etrading"], due=datetime.combine(ss.cert, time(0)) - timedelta(days=2),
                            action="Renew it and exchange it with the counterparty in a test window"))
        if ss.critical:
            ok = bool(ss.backup) and ss.backup_tested is not None and (s.review.date() - ss.backup_tested).days <= s.failover_months * 31
            checks.append(ok)
            if not ok:
                add(Finding("FAILOVER", "AMBER", "resilience", ss.id, f"{name}: " + ("no backup host" if not ss.backup else
                            "failover to " + ss.backup + (f" last tested {ss.backup_tested:%b %Y}" if ss.backup_tested else " never tested")),
                            ss.owner or own["etrading"], action="Test the failover with the counterparty in a weekend window"))

        score = round(100 * sum(checks) / len(checks), 1) if checks else 100.0
        mine = [f for f in rv.findings if f.subject == ss.id]
        state = "down" if down_now else "silent" if not logged_last else "up"
        rv.sessions.append({"session": ss.id, "counterparty": ss.counterparty, "purpose": ss.purpose, "critical": "yes" if ss.critical else "no",
                            "state": state, "disconnects": len(drops), "in_market_hours": len(drops_hours), "resends": len(resends), "hard_resets": len(hard),
                            "test_requests": len(tests), "rejects": len(rej), "p99_ms": p99_last if p99_last is not None else "",
                            "cert_expiry": ss.cert.isoformat() if ss.cert else "", "score": score, "findings": " ".join(sorted({f.code for f in mine}))})
        for dd in rv.days:
            c = day_rows[dd]
            lx = lat[key(ss.id)].get(dd)
            rv.daily.append({"date": dd.isoformat(), "session": ss.id, "logons": c["logons"], "disconnects": c["disconnects"], "resends": c["resends"],
                             "resets": c["resets"], "test_requests": c["test_requests"], "rejects": c["rejects"],
                             "p99_ms": lx.p99 if lx and lx.p99 is not None else ""})

    # --- the watchlist before the open: what is down, what may have lost messages, then the rest of the red, critical first
    sev = {"RED": 0, "AMBER": 1}
    crit = {x.id: x.critical for x in d.sessions}
    seen = {}
    for f in sorted(rv.findings, key=lambda f: (not f.preopen, sev[f.severity], not crit.get(f.subject, False), f.subject)):
        if f.subject in seen or (f.severity != "RED" and not f.preopen):
            continue
        ss = next((x for x in d.sessions if x.id == f.subject), None)
        seen[f.subject] = True
        rv.watchlist.append({"order": len(seen), "session": f.subject, "counterparty": ss.counterparty if ss else "", "critical": "yes" if crit.get(f.subject) else "no",
                             "why": f.code, "check": f.action, "owner": f.owner, "by": f.due.strftime("%Y-%m-%d %H:%M") if f.due else ""})

    rv.sessions.sort(key=lambda r: (r["critical"] != "yes", r["score"], r["session"]))
    rv.score = round(sum(r["score"] for r in rv.sessions) / len(rv.sessions), 1) if rv.sessions else 0.0
    agg = defaultdict(list)
    for r in rv.sessions:
        agg[r["counterparty"] or "(none)"].append(r)
    for k, rows in sorted(agg.items(), key=lambda kv: (sum(r["score"] for r in kv[1]) / len(kv[1]), kv[0])):
        rv.counterparties.append({"counterparty": k, "sessions": len(rows), "critical": sum(r["critical"] == "yes" for r in rows),
                                  "disconnects": sum(r["disconnects"] for r in rows), "score": round(sum(r["score"] for r in rows) / len(rows), 1)})

    # --- decisions
    pre = [w for w in rv.watchlist]
    if pre:
        rv.decisions.append({"decision": f"Before {rv.open_at:%a %d %b %H:%M}: check {pl(len(pre), 'session')} on the watchlist",
                             "detail": ", ".join(f"{w['session']} ({w['why']})" for w in pre), "owner": own["etrading"], "due": before_open})
    drop = [f for f in rv.findings if f.code in ("DROPS", "LATENCY")]
    if drop:
        cps = sorted({next((x.counterparty for x in d.sessions if x.id == f.subject), f.subject) for f in drop})
        rv.decisions.append({"decision": f"Open cases with {pl(len(cps), 'counterparty', 'counterparties')} for drops or latency",
                             "detail": ", ".join(cps), "owner": own["etrading"], "due": s.review + timedelta(days=3)})
    rs = [f for f in rv.findings if f.code == "SEQ-RESET"]
    if rs:
        rv.decisions.append({"decision": f"Reconcile the window of {pl(len(rs), 'hard reset')} with operations", "detail": ", ".join(f.subject for f in rs),
                             "owner": own["etrading"], "due": before_open})
    cert = [f for f in rv.findings if f.code == "CERT"]
    if cert:
        rv.decisions.append({"decision": f"Renew {pl(len(cert), 'certificate')} before they expire", "detail": ", ".join(f.subject for f in cert),
                             "owner": own["etrading"], "due": min(f.due for f in cert)})
    fo = [f for f in rv.findings if f.code == "FAILOVER"]
    if fo:
        rv.decisions.append({"decision": f"Book a failover test for {pl(len(fo), 'critical session')}", "detail": ", ".join(f.subject for f in fo),
                             "owner": own["etrading"], "due": s.review + timedelta(days=30)})
    rj = [f for f in rv.findings if f.code == "REJECTS"]
    if rj:
        rv.decisions.append({"decision": f"Fix the static data behind {pl(len(rj), 'session')} with rejects", "detail": ", ".join(f.subject for f in rj),
                             "owner": own["onboarding"], "due": s.review + timedelta(days=7)})

    red = any(f.severity == "RED" for f in rv.findings)
    amber = any(f.severity == "AMBER" for f in rv.findings)
    rv.status = "RED" if red or rv.score < s.score_red else "AMBER" if amber or rv.score < s.score_amber else "GREEN"
    rv.findings.sort(key=lambda f: (sev[f.severity], list(AREAS).index(f.area), f.code, f.subject))
    return rv


def summary(d: Data, rv: Review) -> dict:
    c = Counter(f.code for f in rv.findings)
    return {"status": rv.status, "score": rv.score, "previous": d.settings.previous_score, "sessions": len(d.sessions),
            "critical": sum(1 for x in d.sessions if x.critical), "disconnects": sum(r["disconnects"] for r in rv.sessions),
            "down": sum(1 for r in rv.sessions if r["state"] != "up"), "watchlist": len(rv.watchlist), "resets": c["SEQ-RESET"],
            "red": sum(1 for f in rv.findings if f.severity == "RED"), "amber": sum(1 for f in rv.findings if f.severity == "AMBER"),
            "decisions": len(rv.decisions)}
