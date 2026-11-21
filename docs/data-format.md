# Data format

Every file is CSV (comma or semicolon, UTF-8 or UTF-16), column names are matched without case, spaces or accents.
`sessions.csv` and `events.csv` are required; `latency.csv` turns on the latency check.

## sessions.csv: the FIX sessions and their configuration

| Column | Also read as | Notes |
|---|---|---|
| Session | SessionID | The id used in events.csv, e.g. `SENDER->TARGET` (what `Export-FixSessionEvents.ps1` writes) |
| Counterparty, Purpose | Venue, Flow | Purpose: orders, drop copy, market data, allocations… (picks the latency limit) |
| Critical | Tier | yes: drops, silence, a hard reset or latency make it red, and its failover is checked |
| FIXVersion, HeartBtInt | BeginString, Heartbeat | The configured heartbeat interval in seconds, compared with tag 108 in the logons |
| StartTime, EndTime | | The session schedule, shown in the outputs |
| Primary, Backup, BackupTested | PrimaryHost, BackupHost, LastFailoverTest | Hosts and the date of the last failover test |
| CertExpiry | TLSExpiry | Expiry of the TLS certificate used for the session |
| Owner, Desk | Support, Business | Who receives the findings (Desk for rejects) |

## events.csv: the session-level messages of the week (`scripts/Export-FixSessionEvents.ps1`)

| Column | FIX tag | Notes |
|---|---|---|
| Time | 52 SendingTime | `2026-11-16 06:30:00` or `20261116-06:30:00.000`; the same time zone as the market hours in settings.json |
| Session | | As in sessions.csv |
| Dir | | out: we sent it; in: the counterparty did |
| MsgType | 35 | A Logon, 5 Logout, 1 TestRequest, 2 ResendRequest, 3 Reject, 4 SequenceReset, j BusinessMessageReject, or `disconnect` from the engine's event log |
| MsgSeqNum | 34 | |
| BeginSeqNo, EndSeqNo | 7, 16 | On resend requests |
| NewSeqNo, GapFill | 36, 123 | On sequence resets; GapFill N (or empty on a reset) is a hard reset |
| HeartBtInt | 108 | On logons |
| Text | 58 | Reason of a logout or reject |

Heartbeats and application messages are not needed.

## latency.csv: order round trip per session and day (optional)

Date, Session, Orders, P50ms, P99ms, MaxMs: from the engine or the monitoring, the time from a new order (35=D) to its
first execution report (35=8).

## settings.json

| Setting | Default | Meaning |
|---|---|---|
| organisation, review | | When the review runs; the week is the last `days` trading days that closed before it |
| days | 5 | Trading days looked at |
| market_open, market_close | 08:00, 17:30 | Market hours: drops inside them count for red, and the watchlist is due an hour before the open |
| drops_red | 3 | Drops in market hours that make a critical session red |
| resends_amber, test_requests_amber, rejects_amber | 5, 5, 10 | Counts in the week that make a finding |
| latency_p99_ms | orders 10, market data 5, drop copy 50, allocations 250, default 20 | p99 limit per purpose |
| latency_factor | 2 | The last day's p99 must also be this many times the earlier days' median |
| cert_days, cert_red_days | 30, 7 | Certificate expiry amber and red |
| failover_months | 6 | A critical session's failover test older than this is amber |
| score_amber, score_red, previous_score | 90, 75, none | Status and trend |
| owners | etrading, network, onboarding | Who owns each kind of finding when the session has no owner |

## Checks

| Code | When | Severity |
|---|---|---|
| DROPS | The session ended without a logout: the engine logged a disconnect, or a new logon arrived while it was up | AMBER (RED for a critical session with `drops_red` in market hours) |
| LOGON-REFUSED | The last logon was answered with a logout and the session did not come back | RED, before the open |
| SILENT | No logon on the last trading day | AMBER (RED and before the open for a critical session) |
| SEQ-GAPS | Resend requests at or above `resends_amber` | AMBER |
| SEQ-RESET | A sequence reset without gap fill: the messages in between were never resent | RED for critical sessions and drop copies, before the open |
| HB-MISSED | Test requests we sent because the counterparty's heartbeats stopped | AMBER |
| REJECTS | Session and business rejects at or above `rejects_amber` | AMBER |
| HB-MISMATCH | Logons with a HeartBtInt different from the configuration | AMBER |
| LATENCY | Last day's p99 above the purpose's limit and `latency_factor` times its own baseline | AMBER (RED and before the open for critical) |
| CERT | TLS certificate expiring within `cert_days` | AMBER (RED within `cert_red_days`) |
| FAILOVER | Critical session with no backup or a failover test older than `failover_months` | AMBER |
| UNKNOWN-SESSION | Messages for a session that is not in sessions.csv | AMBER |

## How it is worked out

1. **The week:** the last `days` weekdays whose market closed before the review; the next open is the first weekday
   `market_open` after it.
2. **Session state:** walked message by message; the state at the last close is up, down (logon refused) or silent.
3. **Score per session:** the share of its checks that pass; the organisation's score is the average. Status: RED with any
   red finding or a score below `score_red`, AMBER with any amber finding or below `score_amber`.
4. **Watchlist before the open:** one line per session with something to do before the open or a red finding: first
   what must be checked before the open, then by severity, critical sessions first.
