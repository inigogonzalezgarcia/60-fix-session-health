"""Command line: `demo` writes the fictional Fabrikam Markets data to sample_data/ and builds the outputs; `review` runs on
your own files."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report, simulate
from .checks import pl, review, summary
from .model import load

OUTPUTS = ("report.html", "preopen-pack.md", "sessions.csv", "daily.csv", "watchlist.csv", "counterparties.csv", "findings.csv", "actions.csv")


def run(data: Path, out: Path, title: str | None = None) -> dict:
    d = load(data)
    rv = review(d)
    title = title or f"{d.settings.organisation} · FIX session health"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, rv, title), encoding="utf-8")
    (out / "preopen-pack.md").write_text(report.pack_md(d, rv, title), encoding="utf-8")
    report.write_csv(out / "sessions.csv", rv.sessions, ["session", "counterparty", "purpose", "critical", "state", "disconnects", "in_market_hours", "resends",
                                                         "hard_resets", "test_requests", "rejects", "p99_ms", "cert_expiry", "score", "findings"])
    report.write_csv(out / "daily.csv", rv.daily, ["date", "session", "logons", "disconnects", "resends", "resets", "test_requests", "rejects", "p99_ms"])
    report.write_csv(out / "watchlist.csv", rv.watchlist, ["order", "session", "counterparty", "critical", "why", "check", "owner", "by"])
    report.write_csv(out / "counterparties.csv", rv.counterparties, ["counterparty", "sessions", "critical", "disconnects", "score"])
    report.write_findings(rv, out / "findings.csv")
    report.write_actions(rv, out / "actions.csv")
    return summary(d, rv)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fixhealth", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="write the fictional data to sample_data/ and build the outputs")
    dm.add_argument("--data", type=Path, default=Path("sample_data"))
    dm.add_argument("--out", type=Path, default=Path("output"))
    rv = sub.add_parser("review", help="build the outputs from your own files")
    rv.add_argument("data", type=Path, help="folder with sessions.csv, events.csv and optionally latency.csv")
    rv.add_argument("--out", type=Path, default=Path("output"))
    rv.add_argument("--title", help="title of the report and the pack")
    a = p.parse_args(argv)
    try:
        if a.cmd == "demo":
            simulate.write(a.data)
            sm = run(a.data, a.out)
        else:
            sm = run(a.data, a.out, a.title)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{sm['status']}: session health {sm['score']} % across {pl(sm['sessions'], 'FIX session')} ({sm['critical']} critical), "
          f"{pl(sm['disconnects'], 'disconnect')}, {pl(sm['down'], 'session')} not up at the last close, {sm['watchlist']} to check before the open, "
          f"{sm['red']} red and {sm['amber']} amber findings, {pl(sm['decisions'], 'decision')}")
    print(f"outputs in {a.out}/: {', '.join(OUTPUTS)}")
    return 0
