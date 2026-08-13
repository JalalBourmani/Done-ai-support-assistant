<#
.SYNOPSIS
    Logger inn Claude Code CLI slik at Auto-XSALE kan kjore uovervaket.

.DESCRIPTION
    Desktop-appen og CLI-en har separate innlogginger. Den planlagte oppgaven
    bruker CLI-en, sa den ma autentiseres en gang for seg.

    Standard er 'setup-token', som gir en langlevd token laget for automatisering.
    Bruk -UseSessionLogin for vanlig 'claude auth login' i stedet.

    Skriptet apner nettleseren for OAuth. Fullfor innloggingen der.

.PARAMETER UseSessionLogin
    Bruk 'claude auth login' i stedet for 'setup-token'. Enklere, men sesjonen
    kan lope ut og da stopper den planlagte oppgaven stille.

.PARAMETER StatusOnly
    Vis bare naevaerende innloggingsstatus, uten a logge inn.
#>
param(
    [switch] $UseSessionLogin,
    [switch] $StatusOnly
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$claudeExe = Resolve-ClaudeCli
Write-Host "Claude Code CLI: $claudeExe" -ForegroundColor Cyan
& $claudeExe --version
Write-Host ""

Write-Host "Status for innlogging:" -ForegroundColor Cyan
& $claudeExe auth status
Write-Host ""

if ($StatusOnly) {
    return
}

if ($UseSessionLogin) {
    Write-Host "Starter 'claude auth login'. Fullfor innloggingen i nettleseren." -ForegroundColor Cyan
    & $claudeExe auth login
} else {
    Write-Host "Starter 'claude setup-token'. Fullfor innloggingen i nettleseren." -ForegroundColor Cyan
    Write-Host "Dette gir en langlevd token, egnet for den planlagte oppgaven." -ForegroundColor DarkGray
    & $claudeExe setup-token
}

Write-Host ""
Write-Host "Status etter innlogging:" -ForegroundColor Cyan
& $claudeExe auth status
