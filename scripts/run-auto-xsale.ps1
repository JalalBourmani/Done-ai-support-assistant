param(
    # 0 = ingen budsjettgrense. --max-turns finnes ikke lenger i Claude Code 2.x;
    # --max-budget-usd er naermeste tilsvarende sikring mot rundgang.
    [double] $MaxBudgetUsd = 0
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

# Ma kalles for stiene under leses. Den gamle versjonen kalte aldri denne, sa
# ingenting i prompten ble expandert - prompten gikk ut med hardkodede stier.
Import-ConfigEnv

$claudeExe = Resolve-ClaudeCli

# 'claude setup-token' logger ikke inn CLI-en lokalt; tokenet ma leveres som
# CLAUDE_CODE_OAUTH_TOKEN. Lastes fra DPAPI-lageret rett for kjoring, slik at det
# aldri havner i registeret, prosjektfiler eller Git.
$tokenPath = Join-Path $script:KitRoot "secrets\claude-token.xml"
$tokenLoaded = $false
if (Test-Path -LiteralPath $tokenPath) {
    Import-EncryptedCredential `
        -Path $tokenPath `
        -UsernameVariable "CLAUDE_TOKEN_LABEL" `
        -PasswordVariable "CLAUDE_CODE_OAUTH_TOKEN"
    $tokenLoaded = $true
}

# Preflight. En uovervaket jobb skal feile med en tydelig linje i loggen, ikke
# med "Not logged in" midt i en runde.
$authStatus = (& $claudeExe auth status 2>&1 | Out-String).Trim()
$loggedIn = $authStatus -match '"loggedIn"\s*:\s*true'
if (-not $loggedIn) {
    if ($tokenLoaded) {
        Write-Warning "auth status melder ikke loggedIn, men et lagret token er lastet. Fortsetter."
    } else {
        throw ("Claude Code CLI er ikke autentisert, og det finnes ikke noe lagret token.`n" +
            "Kjor scripts\login-claude-cli.ps1 og deretter scripts\configure-claude-token.ps1.`n" +
            "auth status: $authStatus")
    }
}

$promptPath = Join-Path $script:KitRoot "prompts\auto-xsale-saksassistent.md"
if (-not (Test-Path -LiteralPath $promptPath)) {
    throw "Mangler prompten: $promptPath"
}
$mcpConfig = Join-Path $script:KitRoot "generated\mcp.json"
if (-not (Test-Path -LiteralPath $mcpConfig)) {
    throw "Mangler $mcpConfig. Kjor scripts\install.ps1."
}

# ---------------------------------------------------------------------------
#  Stier og plassholdere
# ---------------------------------------------------------------------------
# Prompten inneholder ingen navn og ingen absolutte stier. Den bruker
# plassholdere som expanderes her, med den innloggede brukerens egne verdier.
# Hvilke SAKER som plukkes bestemmes ikke av prompten, men av XSALE-sesjonen:
# list_my_cases filtrerer pa userId hentet fra innloggingen. Prompten trenger
# derfor aldri a vite hvem brukeren er.

$autoXsaleRoot = $env:AUTO_XSALE_DIR
if ([string]::IsNullOrWhiteSpace($autoXsaleRoot)) {
    $autoXsaleRoot = Join-Path $env:USERPROFILE "Documents\Auto-XSALE"
}
New-Item -ItemType Directory -Force -Path $autoXsaleRoot | Out-Null

$serversRoot = Join-Path $script:KitRoot "servers"

$taskLedger = $env:TASK_LEDGER
if ([string]::IsNullOrWhiteSpace($taskLedger)) {
    $taskLedger = Join-Path $autoXsaleRoot "task.md"
}

$prompt = Get-Content -Raw -LiteralPath $promptPath
$prompt = $prompt.
    Replace('${AUTO_XSALE_ROOT}', $autoXsaleRoot).
    Replace('${SERVERS_ROOT}', $serversRoot).
    Replace('${TASK_LEDGER}', $taskLedger)

# En glemt plassholder ma stoppe kjoringen. Slipper den gjennom, ville agenten
# lagd en mappe som bokstavelig het "${AUTO_XSALE_ROOT}" og rapportert suksess.
$leftover = [regex]::Matches($prompt, '\$\{[A-Z_]+\}') | ForEach-Object { $_.Value } | Sort-Object -Unique
if ($leftover) {
    throw ("Prompten har plassholdere som ikke ble expandert: " + ($leftover -join ", ") + "`n" +
        "Legg til erstatningen i run-auto-xsale.ps1 for du kjorer igjen.")
}

$logRoot = Join-Path $script:KitRoot "logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logRoot "auto-xsale-$stamp.log"

# ---------------------------------------------------------------------------
#  Verktoyhviteliste — LES DETTE FOR DU ENDRER DEN
# ---------------------------------------------------------------------------
# Dette er hele grunnen til at en uovervaket kjoring er trygg. Alle
# XSALE-verktoyene under er lesende. `create_case` og `add_case_comment` er
# holdt utenfor MED VILJE: de skriver til kundens sak under brukerens navn, og
# skal bare brukes nar et menneske ber om det i en samtale.
#
# Legg aldri til et skrivende verktoy her for a "spare et steg". Kjoringen har
# ingen godkjenningsport, ingen gjennomgang og ingen angremulighet.
#
# Write/Edit/Bash er med fordi agenten ma kunne skrive saksmappen. Det betyr at
# kjoringen KAN endre filer lokalt - inkludert denne fila og prompten. Det er en
# kjent begrensning, ikke en garanti vi gir. Se FORUTSETNINGER.md.
$allowedTools = @(
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash(python:*)",
    "mcp__xsale-crm__list_my_cases",
    "mcp__xsale-crm__get_case_by_serial",
    "mcp__xsale-crm__get_case_communications",
    "mcp__xsale-crm__get_customer_details",
    "mcp__xsale-crm__get_customer_timeline",
    "mcp__xsale-crm__get_customer_orders",
    "mcp__xsale-crm__get_order_details",
    "mcp__xsale-crm__get_installation_context",
    "mcp__mysql-query-server__execute_query",
    "mcp__notebooklm-mcp__notebook_list",
    "mcp__notebooklm-mcp__notebook_query",
    "mcp__notebooklm-mcp__notebook_query_start",
    "mcp__notebooklm-mcp__notebook_query_status"
)

# Sikkerhetsnett: hvis noen likevel har lagt inn et skrivende XSALE-verktoy,
# stopp for kjoringen starter framfor a oppdage det i ettertid i en kundesak.
$forbidden = @("create_case", "add_case_comment", "delete", "close_case", "send_email")
$violations = $allowedTools | Where-Object {
    $t = $_
    ($forbidden | Where-Object { $t -like "*$_*" })
}
if ($violations) {
    throw ("Hvitelisten inneholder skrivende verktoy, som ikke er tillatt i en uovervaket kjoring: " +
        ($violations -join ", "))
}

# --strict-mcp-config: bruk bare $mcpConfig, ignorer andre MCP-kilder, slik at
# den uovervakede kjoringen alltid far noyaktig de tre serverne - og ikke arver
# servere fra brukerens personlige .mcp.json.
$claudeArgs = @(
    "-p", $prompt,
    "--mcp-config", $mcpConfig,
    "--strict-mcp-config",
    "--output-format", "text",
    "--allowedTools"
) + $allowedTools

if ($MaxBudgetUsd -gt 0) {
    $claudeArgs += @("--max-budget-usd", $MaxBudgetUsd)
}

Write-Host "Claude Code CLI : $claudeExe"
Write-Host "Saksmappe       : $autoXsaleRoot"
Write-Host "Oppgavelogg     : $taskLedger"
Write-Host "Logg            : $logPath"

$projectRoot = $env:PROJECT_ROOT
if ([string]::IsNullOrWhiteSpace($projectRoot)) { $projectRoot = $script:KitRoot }

Push-Location $projectRoot
try {
    & $claudeExe @claudeArgs 2>&1 | Tee-Object -FilePath $logPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
