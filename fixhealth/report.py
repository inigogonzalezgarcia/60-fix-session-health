"""Outputs: report.html (score and tiles, the watchlist before the open, decisions, every finding by area, the sessions with
their week, the days of the week and the counterparties), preopen-pack.md (one page for the electronic trading desk before
the open) and the CSVs: sessions, daily, watchlist, counterparties, findings and actions."""
from __future__ import annotations

import csv
import html
from pathlib import Path

from .checks import AREAS, Review, pl, summary
from .model import FILES, Data

e = html.escape


def write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows([{k: ("" if r.get(k) is None else r.get(k)) for k in header} for r in rows])


def _when(x) -> str:
    return "" if not x else f"{x:%a %d %b %H:%M}"


def write_findings(rv: Review, path: Path) -> None:
    write_csv(path, [{"severity": f.severity, "area": AREAS[f.area], "code": f.code, "session": f.subject, "finding": f.text,
                      "before_open": "yes" if f.preopen else "", "owner": f.owner, "due": f.due.strftime("%Y-%m-%d %H:%M") if f.due else "",
                      "action": f.action} for f in rv.findings],
              ["severity", "area", "code", "session", "finding", "before_open", "owner", "due", "action"])


def write_actions(rv: Review, path: Path) -> None:
    write_csv(path, [{"ref": f"A{n:03d}", "severity": f.severity, "action": f.action, "session": f.subject, "owner": f.owner,
                      "due": f.due.strftime("%Y-%m-%d %H:%M") if f.due else "", "done": ""} for n, f in enumerate(rv.findings, 1)],
              ["ref", "severity", "action", "session", "owner", "due", "done"])


def _trend(d: Data, rv: Review) -> str:
    p = d.settings.previous_score
    if p is None:
        return ""
    diff = round(rv.score - p, 1)
    return f"{'+' if diff >= 0 else ''}{diff} points on the last review ({p} %)"


def _period(rv: Review) -> str:
    return f"{rv.days[0]:%a %d %b} to {rv.days[-1]:%a %d %b %Y}"


def pack_md(d: Data, rv: Review, title: str) -> str:
    sm = summary(d, rv)
    out = [f"# {title}", "", f"Trading days {_period(rv)} · {sm['sessions']} FIX sessions ({sm['critical']} critical) · next open {_when(rv.open_at)}", "",
           f"**Result: {rv.status}** · session health **{rv.score} %**" + (f" · {_trend(d, rv)}" if _trend(d, rv) else ""), "",
           "## Before the open", ""]
    out += [f"{w['order']}. **{w['session']}** ({w['counterparty']}{', critical' if w['critical'] == 'yes' else ''}) · {w['why']} → {w['check']} · "
            f"{w['owner']} · by {w['by']}" for w in rv.watchlist] or ["Nothing to check."]
    out += ["", "## Headlines", "",
            f"- {pl(sm['disconnects'], 'disconnect')} without a logout this week.",
            f"- {pl(sm['down'], 'session')} not up at the last close.",
            f"- {pl(sm['resets'], 'sequence reset')} without gap fill.",
            f"- {sm['red']} red and {sm['amber']} amber findings, {pl(sm['decisions'], 'decision')}.", "", "## Decisions", ""]
    out += [f"{n}. **{x['decision']}** — {x['detail']} · {x['owner']} · by {_when(x['due'])}" for n, x in enumerate(rv.decisions, 1)] or ["None this time."]
    out += ["", "## Sessions", "", "| Session | Counterparty | Purpose | State | Drops | Resends | Test req. | Rejects | p99 ms | Score |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    out += [f"| {r['session']} | {r['counterparty']} | {r['purpose']}{' (critical)' if r['critical'] == 'yes' else ''} | {r['state']} | {r['disconnects']} | "
            f"{r['resends']} | {r['test_requests']} | {r['rejects']} | {r['p99_ms']} | {r['score']} % |" for r in rv.sessions]
    out += ["", "## Sources", ""] + [f"- {FILES[k]} ({k}): {v} rows" for k, v in d.sources.items()]
    out += ["", "## Notes", "", "- Thresholds, market hours and latency limits are this desk's own policy (settings.json).",
            "- Amber findings and actions: findings.csv and actions.csv; day by day: daily.csv.", ""]
    return "\n".join(out)


CSS = """
:root{--bg:#f2eee6;--card:#fbf8f3;--ink:#0e1a24;--muted:#5d6670;--line:#e2dccf;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--track:#e8e2d6}
@media (prefers-color-scheme:dark){:root{--bg:#0e1a24;--card:#142331;--ink:#f2eee6;--muted:#a9b3bb;--line:#24364a;--ok:#4cc38a;
--warn:#f0a83a;--bad:#f2685c;--track:#2b333b}}
*{box-sizing:border-box}body{border-top:4px solid #c4672b}h1{font-weight:800;letter-spacing:-.025em;text-transform:uppercase;line-height:1.05}h1::before{content:"IGG · IT Ops toolkit";display:block;font:600 11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:#c4672b;margin-bottom:10px}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:24px}
.overall{display:inline-block;margin-top:14px;padding:6px 14px;border-radius:99px;font-weight:700;border:2px solid currentColor}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.red{color:var(--bad)}.amber{color:var(--warn)}.green{color:var(--ok)}td.fix{font-size:13px;color:var(--muted);min-width:200px;max-width:340px}
.bar{display:inline-block;width:90px;height:8px;border-radius:4px;background:var(--track);vertical-align:middle;margin-right:8px;overflow:hidden}
.bar i{display:block;height:100%}.brk{overflow-wrap:anywhere;word-break:break-word}footer{margin-top:40px;font-size:13px}
"""


def _pill(x: str) -> str:
    return f"<span class='pill {x.lower()}'>{e(x)}</span>"


def _table(head: list[str], rows: list[str], empty: str = "Nothing to show.") -> str:
    if not rows:
        rows = [f"<tr><td colspan='{len(head)}'>{e(empty)}</td></tr>"]
    return "<div class='wrap'><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" + "".join(rows) + "</table></div>"


def _bar(score: float, s) -> str:
    cls = "ok" if score >= s.score_amber else "warn" if score >= s.score_red else "bad"
    return f"<span class='bar'><i style='width:{max(0, min(100, score)):.0f}%;background:var(--{cls})'></i></span>{score} %"


def render_html(d: Data, rv: Review, title: str) -> str:
    s, sm = d.settings, summary(d, rv)
    h = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>Trading days {e(_period(rv))} · {sm['sessions']} FIX sessions ({sm['critical']} critical) · next open "
         f"{e(_when(rv.open_at))} · " + ", ".join(f"{FILES[k]} ({v})" for k, v in d.sources.items()) + "</p>",
         f"<span class='overall {rv.status.lower()}'>{rv.status} · session health {rv.score} %</span>"
         + (f" <span class='muted'>{e(_trend(d, rv))}</span>" if _trend(d, rv) else ""), "<div class='tiles'>"]
    tiles = [("Session health", f"{rv.score} %"), ("Sessions", sm["sessions"]), ("Critical", sm["critical"]), ("Drops this week", sm["disconnects"]),
             ("Not up at the close", sm["down"]), ("Before the open", sm["watchlist"]), ("Red findings", sm["red"]), ("Decisions", sm["decisions"])]
    h += [f"<div class='tile'><span class='muted'>{e(k)}</span><b>{e(str(v))}</b></div>" for k, v in tiles] + ["</div>"]
    h.append(f"<h2>Before the open <span class='muted'>({e(_when(rv.open_at))})</span></h2>")
    h.append(_table(["#", "Session", "Counterparty", "Why", "Check", "Owner", "By"], [f"<tr><td class='num'>{w['order']}</td><td class='brk'>{e(w['session'])}</td>"
                    f"<td>{e(w['counterparty'])}{' · critical' if w['critical'] == 'yes' else ''}</td><td>{e(w['why'])}</td>"
                    f"<td class='fix'>{e(w['check'])}</td><td>{e(w['owner'])}</td><td class='num'>{e(w['by'])}</td></tr>" for w in rv.watchlist],
                    "Nothing to check before the open."))
    h.append("<h2>Decisions</h2>")
    h.append(_table(["Decision", "Detail", "Owner", "Due"], [f"<tr><td><b>{e(x['decision'])}</b></td><td class='brk'>{e(x['detail'])}</td>"
                    f"<td>{e(x['owner'])}</td><td class='num'>{e(_when(x['due']))}</td></tr>" for x in rv.decisions], "No decisions this time."))
    for area, label in AREAS.items():
        fs = [f for f in rv.findings if f.area == area]
        h.append(f"<h2>{e(label)} <span class='muted'>({len(fs)})</span></h2>")
        h.append(_table(["", "Code", "Finding", "Action", "Owner", "Due"], [f"<tr><td>{_pill(f.severity)}</td><td class='num'>{e(f.code)}</td>"
                        f"<td class='brk'>{e(f.text)}</td><td class='fix'>{e(f.action)}</td><td>{e(f.owner)}</td><td class='num'>{e(_when(f.due))}</td></tr>"
                        for f in fs], "Nothing to report."))
    h.append("<h2>Sessions this week</h2>")
    h.append(_table(["Session", "Counterparty", "Purpose", "State", "Drops (market hours)", "Resends", "Hard resets", "Test req.", "Rejects", "p99 ms", "Score"],
                    [f"<tr><td class='brk'>{e(r['session'])}</td><td>{e(r['counterparty'])}</td><td>{e(r['purpose'])}{' · critical' if r['critical'] == 'yes' else ''}</td>"
                     f"<td>{e(r['state'])}</td><td class='num'>{r['disconnects']} ({r['in_market_hours']})</td><td class='num'>{r['resends']}</td>"
                     f"<td class='num'>{r['hard_resets']}</td><td class='num'>{r['test_requests']}</td><td class='num'>{r['rejects']}</td>"
                     f"<td class='num'>{e(str(r['p99_ms']))}</td><td>{_bar(r['score'], s)}</td></tr>" for r in rv.sessions]))
    days: dict = {}
    for r in rv.daily:
        x = days.setdefault(r["date"], {"logons": 0, "disconnects": 0, "resends": 0, "resets": 0, "test_requests": 0, "rejects": 0})
        for k in x:
            x[k] += r[k]
    h.append("<h2>Day by day</h2>")
    h.append(_table(["Day", "Logons", "Drops", "Resend requests", "Sequence resets", "Test requests", "Rejects"],
                    [f"<tr><td class='num'>{e(k)}</td>" + "".join(f"<td class='num'>{v}</td>" for v in x.values()) + "</tr>" for k, x in days.items()]))
    h.append("<h2>Counterparties</h2>")
    h.append(_table(["Counterparty", "Sessions", "Critical", "Drops", "Score"], [f"<tr><td>{e(c['counterparty'])}</td><td class='num'>{c['sessions']}</td>"
                    f"<td class='num'>{c['critical']}</td><td class='num'>{c['disconnects']}</td><td>{_bar(c['score'], s)}</td></tr>" for c in rv.counterparties]))
    h.append(f"<footer class='muted'>A drop is a session that ended without a logout (the engine logged a disconnect, or a new logon arrived while the "
             f"session was up). Market hours {e(s.market_open)}-{e(s.market_close)}. Thresholds and latency limits are this desk's policy (settings.json)."
             "</footer></main></body></html>")
    return "\n".join(h)
