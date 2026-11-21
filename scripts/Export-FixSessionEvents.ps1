<#
.SYNOPSIS
    Reads the FIX engine logs of the last days and writes the session-level messages to events.csv.
.DESCRIPTION
    Read-only. For QuickFIX/J and QuickFIX/n style logs: one messages log and one event log per session, named
    <BeginString>-<SenderCompID>-<TargetCompID>.messages[.current].log and ...event[.current].log. From the messages log it
    keeps only the session-level messages (35=A Logon, 5 Logout, 1 TestRequest, 2 ResendRequest, 3 Reject, 4 SequenceReset)
    and BusinessMessageReject (35=j), with the tags the review needs (34, 52, 7, 16, 36, 123, 108, 58); heartbeats and
    application messages are left out, so the file stays small. From the event log it keeps the disconnects. The direction
    is "out" when tag 49 is your SenderCompID. Writes events.csv for `python -m fixhealth review`. Changes nothing.
.EXAMPLE
    .\Export-FixSessionEvents.ps1 -LogFolder D:\fixgw\log -Days 7 -OutputFolder .\data
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $LogFolder,
    [int] $Days = 7,
    [string] $OutputFolder = '.'
)
$ErrorActionPreference = 'Stop'
$since = (Get-Date).Date.AddDays(-$Days)
$keep = @('A', '5', '1', '2', '3', '4', 'j')
$soh = [char]1

function ConvertFrom-FixTime([string] $v) {
    foreach ($f in 'yyyyMMdd-HH:mm:ss.fff', 'yyyyMMdd-HH:mm:ss') {
        $t = [datetime]::MinValue
        if ([datetime]::TryParseExact($v, $f, [Globalization.CultureInfo]::InvariantCulture, 'AssumeUniversal,AdjustToUniversal', [ref] $t)) { return $t }
    }
    return $null
}

$rows = foreach ($log in Get-ChildItem -Path $LogFolder -Filter '*.messages*.log' -File) {
    if ($log.Name -notmatch '^(?<ver>FIX[T]?\.[0-9.]+(SP\d)?)-(?<snd>[^-]+)-(?<tgt>[^.]+)\.messages') { continue }
    $sender, $session = $Matches.snd, "$($Matches.snd)->$($Matches.tgt)"
    foreach ($line in Get-Content -Path $log.FullName -ReadCount 0) {
        $i = $line.IndexOf('8=FIX')
        if ($i -lt 0) { continue }
        $tags = @{}
        foreach ($pair in $line.Substring($i).Split(@($soh, '|'), 'RemoveEmptyEntries')) {
            $k, $v = $pair.Split('=', 2)
            if (-not $tags.ContainsKey($k)) { $tags[$k] = $v }
        }
        if ($keep -notcontains $tags['35']) { continue }
        $t = ConvertFrom-FixTime $tags['52']
        if (-not $t -or $t -lt $since) { continue }
        [pscustomobject]@{
            Time = $t.ToString('yyyy-MM-dd HH:mm:ss'); Session = $session; Dir = $(if ($tags['49'] -eq $sender) { 'out' } else { 'in' })
            MsgType = $tags['35']; MsgSeqNum = $tags['34']; BeginSeqNo = $tags['7']; EndSeqNo = $tags['16']; NewSeqNo = $tags['36']
            GapFill = $tags['123']; HeartBtInt = $tags['108']; Text = $tags['58']
        }
    }
    $events = Join-Path $log.DirectoryName ($log.Name -replace '\.messages', '.event')
    if (Test-Path $events) {
        foreach ($line in Get-Content -Path $events -ReadCount 0) {
            if ($line -notmatch '^(?<ts>\d{8}-\d{2}:\d{2}:\d{2}(\.\d+)?)\s*:?\s*(?<msg>.*disconnect.*)$') { continue }
            $t = ConvertFrom-FixTime ($Matches.ts.Substring(0, [Math]::Min(21, $Matches.ts.Length)))
            if (-not $t -or $t -lt $since) { continue }
            [pscustomobject]@{ Time = $t.ToString('yyyy-MM-dd HH:mm:ss'); Session = $session; Dir = 'out'; MsgType = 'disconnect'; MsgSeqNum = ''
                BeginSeqNo = ''; EndSeqNo = ''; NewSeqNo = ''; GapFill = ''; HeartBtInt = ''; Text = $Matches.msg.Trim() }
        }
    }
}
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null
$out = Join-Path $OutputFolder 'events.csv'
$rows | Sort-Object Time, Session | Export-Csv -Path $out -NoTypeInformation -Encoding UTF8
Write-Host "$(@($rows).Count) session-level messages and disconnects written to $out"
Write-Host "FIX times (tag 52) are UTC: set the market hours in settings.json in UTC too, or convert the Time column."
