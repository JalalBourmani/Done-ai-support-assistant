<#
.SYNOPSIS
    Lagrer Claude Code OAuth-token DPAPI-kryptert for bruk i Auto-XSALE.

.DESCRIPTION
    'claude setup-token' skriver ut en langlevd token, men logger ikke inn CLI-en
    lokalt. Tokenet ma leveres som miljovariabelen CLAUDE_CODE_OAUTH_TOKEN til den
    uovervakede kjoringen.

    Dette skriptet leser tokenet inn uten a vise det pa skjerm og lagrer det
    kryptert i secrets\claude-token.xml, pa samme mate som XSALE- og
    MySQL-legitimasjonen. run-auto-xsale.ps1 laster det inn i prosessmiljoet
    rett for CLI-en startes, slik at tokenet aldri havner i registeret,
    prosjektfiler eller Git.

.PARAMETER Force
    Overskriv selv om et token allerede er lagret.
#>
param(
    [switch] $Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$secretRoot = Join-Path $script:KitRoot "secrets"
New-Item -ItemType Directory -Force -Path $secretRoot | Out-Null
$tokenPath = Join-Path $secretRoot "claude-token.xml"

if ((Test-Path -LiteralPath $tokenPath) -and -not $Force) {
    $existing = $null
    try { $existing = Import-Clixml -LiteralPath $tokenPath } catch { }
    if ($existing -and $existing.Password -and $existing.Password.Length -gt 0) {
        Write-Host "Et token er allerede lagret i $tokenPath." -ForegroundColor Yellow
        Write-Host "Bruk -Force for a erstatte det." -ForegroundColor Yellow
        return
    }
}

Write-Host "Lim inn tokenet fra 'claude setup-token'." -ForegroundColor Cyan
Write-Host "Det vises ikke mens du limer, og skrives ikke til skjerm etterpa." -ForegroundColor DarkGray
Write-Host ""

$secure = Read-Host -Prompt "CLAUDE_CODE_OAUTH_TOKEN" -AsSecureString
if (-not $secure -or $secure.Length -eq 0) {
    throw "Ingen token angitt. Ingenting ble lagret."
}

# Lagres som PSCredential slik at Import-EncryptedCredential i common.ps1 kan
# gjenbrukes. Brukernavnet er bare en etikett.
$credential = New-Object System.Management.Automation.PSCredential("claude-oauth-token", $secure)
$credential | Export-Clixml -LiteralPath $tokenPath

$check = Import-Clixml -LiteralPath $tokenPath
if (-not $check -or -not $check.Password -or $check.Password.Length -eq 0) {
    throw "Skrev $tokenPath, men den validerte ikke etterpa."
}

Write-Host ""
Write-Host ("Token lagret kryptert ($($check.Password.Length) tegn) for Windows-brukeren $env:USERNAME.") -ForegroundColor Green
Write-Host "Neste steg: scripts\verify.ps1"
