# Running the FIX session review

## The cycle

| When | What | Who |
|---|---|---|
| Friday after the close, or Monday before 06:30 | `Export-FixSessionEvents.ps1` on each FIX gateway; latency from the engine or the monitoring; `python -m fixhealth review data/` | Electronic trading support |
| An hour before the open | The watchlist in preopen-pack.md: sessions down, hard resets, critical sessions that are slow or silent | Electronic trading support, network |
| During the week | Cases with the counterparties for drops and latency, with the times from the report | Electronic trading support |
| Before the dates | Certificates renewed and exchanged in a test window; failover tests booked for critical sessions | Electronic trading support, counterparties |
| After | This score kept as `previous_score` | Electronic trading support |

## Reading the result

1. **What is not up?** A logon refused for sequence numbers needs both sides to agree the numbers before the open; a
   silent session may simply no longer be needed, so ask before chasing it.
2. **Can messages have been lost?** Resend requests that were answered are normal. A sequence reset without gap fill on a
   drop copy or an order session means messages were skipped: reconcile orders and trades of that window first.
3. **Is it stable?** Drops in market hours, test requests at the same hour every day and latency far above the session's
   own baseline point to the line, the host or the counterparty's gateway; the times in the report are what the
   counterparty will ask for.
4. **What will break on its own?** A certificate that expires on a trading day and a failover nobody has tried.

## Changes without surprises

- Sequence numbers are reset only by agreement with the counterparty and written in the change record.
- Certificates are exchanged in a test window, not on the expiry day.
- A failover test is a change: book it outside market hours with the counterparty online.

## Evidence

findings.csv and actions.csv with their dates, the watchlist and the decisions in preopen-pack.md, sessions.csv and
daily.csv are the record of the week; keep them with the counterparty cases.
