param(
    [ValidatePattern("^([01]\d|2[0-3]):[0-5]\d$")]
    [string] $DailyAt = "08:00",

    # Angi for a kjore med fast intervall i stedet for en gang daglig.
    # -EveryMinutes 30 gir samme kadens som Codex-heartbeaten hadde.
    [ValidateRange(5, 1440)]
    [int] $EveryMinutes = 0,

    # Registrer uten tidsplan. Oppgaven blir staende som Ready og kan startes med
    # Start-ScheduledTask eller "Kjor" i Oppgaveplanlegging, men fyrer aldri av seg selv.
    # Merk: Disable-ScheduledTask er IKKE et alternativ - en deaktivert oppgave
    # nekter ogsa manuell start ("The task is disabled").
    [switch] $Manual,

    [string] $TaskName = "Auto-XSALE Claude Code"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
Import-ConfigEnv

$runner = Join-Path $PSScriptRoot "run-auto-xsale.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory (Get-ProjectRoot)
if ($Manual) {
    $trigger = $null
    $schedule = "kun manuell start - ingen tidsplan"
    $timeLimit = New-TimeSpan -Hours 1
} elseif ($EveryMinutes -gt 0) {
    # Startpunkt midnatt i dag gir forutsigbare grenser: med 30 minutter treffer
    # kjoringene :00 og :30. StartWhenAvailable tar igjen hvis maskinen sov.
    # RepetitionDuration utelates bevisst: tom varighet betyr ubegrenset gjentakelse.
    # [TimeSpan]::MaxValue gir P99999999DT23H59M59S, som Oppgaveplanlegging avviser
    # som utenfor gyldig omrade ved registrering.
    $trigger = New-ScheduledTaskTrigger `
        -Once -At (Get-Date).Date `
        -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
    $schedule = "hvert $EveryMinutes. minutt"
    $timeLimit = New-TimeSpan -Hours 1
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
    $schedule = "kl. $DailyAt daglig"
    $timeLimit = New-TimeSpan -Hours 2
}

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# IgnoreNew: hvis en runde varer lenger enn intervallet, hopper vi over neste
# start i stedet for a kjore to runder samtidig mot samme sakskoe.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit $timeLimit

# -Trigger utelates helt i manuell modus; Register-ScheduledTask godtar det.
$registerArgs = @{
    TaskName    = $TaskName
    Action      = $action
    Principal   = $principal
    Settings    = $settings
    Description = "Behandler maks en ny Auto-XSALE-sak med Claude Code og tre MCP-servere."
    Force       = $true
    ErrorAction = "Stop"
}
if ($trigger) { $registerArgs.Trigger = $trigger }

Register-ScheduledTask @registerArgs | Out-Null

# Registreringen kan feile uten a stoppe skriptet, og da ma vi ikke melde suksess.
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $registered) {
    throw "Registreringen av '$TaskName' ser ut til a ha feilet - oppgaven finnes ikke etterpa."
}

Write-Host "Opprettet planlagt oppgave '$TaskName' - $schedule." -ForegroundColor Green
Write-Host "Tilstand: $($registered.State)"

$info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
if ($info -and $info.NextRunTime) {
    Write-Host "Neste kjoring: $($info.NextRunTime)"
} else {
    Write-Host "Neste kjoring: <ingen - startes manuelt>"
    Write-Host "Start med:     Start-ScheduledTask -TaskName `"$TaskName`""
}

